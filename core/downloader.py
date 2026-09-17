"""
Multi-Threaded Download Manager for Universal Video Downloader.
Handles chunked HTTP downloads with Range headers, yt-dlp streaming downloads,
pause/resume, progress, speed, ETA, and state persistence in SQLite.
"""

import os
import re
import time
import uuid
import threading
from typing import Dict, Any, Optional
import requests
import yt_dlp
from core.database import Database
from core.storage_manager import format_bytes
from core.paths import get_default_download_dir


def sanitize_filename(name: str) -> str:
    """Sanitize string to be safe for filenames across OS platforms."""
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    clean = clean.replace(" ", "_").strip(" ._")
    return clean[:100] or "video"


class DownloadTask:
    def __init__(self, task_id: str, url: str, title: str, format_selector: str,
                 direct_url: Optional[str], output_dir: str, db: Database):
        self.task_id = task_id
        self.url = url
        self.title = title
        self.format_selector = format_selector
        self.direct_url = direct_url
        self.output_dir = output_dir
        self.db = db

        self.is_paused = False
        self.is_cancelled = False
        self.thread: Optional[threading.Thread] = None

        # Speed calculation trackers
        self.last_time = time.time()
        self.last_bytes = 0
        self.current_speed = 0.0

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False
        self.start()

    def cancel(self):
        self.is_cancelled = True
        self.is_paused = False

    def _run(self):
        try:
            if self.is_paused or self.is_cancelled:
                return
            self.db.update_download_progress(
                self.task_id, status="downloading", progress=0.0,
                downloaded_bytes=0, total_bytes=0, speed=0.0
            )

            # Strategy 1: Direct HTTP download if direct_url is a direct file (.mp4, .webm)
            if self.direct_url and any(self.direct_url.endswith(ext) for ext in [".mp4", ".webm", ".mkv", ".mov"]):
                self._download_direct_http()
            else:
                # Strategy 2: yt-dlp download with progress hook
                self._download_via_ytdlp()

        except Exception as e:
            try:
                if self.is_cancelled:
                    self.db.update_download_progress(
                        self.task_id, status="cancelled", progress=0.0,
                        downloaded_bytes=0, total_bytes=0, speed=0.0,
                        error_message="Download cancelled by user."
                    )
                elif self.is_paused:
                    pass
                else:
                    self.db.update_download_progress(
                        self.task_id, status="failed", progress=0.0,
                        downloaded_bytes=0, total_bytes=0, speed=0.0,
                        error_message=str(e)
                    )
            except Exception:
                pass

    def _download_direct_http(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*"
        }
        clean_title = sanitize_filename(self.title)
        part_path = os.path.join(self.output_dir, f"{clean_title}_{self.task_id[:6]}.part")
        final_path = os.path.join(self.output_dir, f"{clean_title}_{self.task_id[:6]}.mp4")

        downloaded = 0
        if os.path.exists(part_path):
            downloaded = os.path.getsize(part_path)
            headers["Range"] = f"bytes={downloaded}-"

        resp = requests.get(self.direct_url, headers=headers, stream=True, timeout=20)
        total_size = downloaded
        if "content-length" in resp.headers:
            total_size += int(resp.headers["content-length"])

        mode = "ab" if downloaded > 0 else "wb"
        chunk_size = 1024 * 128  # 128 KB
        self.last_time = time.time()
        self.last_bytes = downloaded

        with open(part_path, mode) as f:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if self.is_cancelled:
                    f.close()
                    if os.path.exists(part_path):
                        os.remove(part_path)
                    self.db.update_download_progress(
                        self.task_id, status="cancelled", progress=0.0,
                        downloaded_bytes=0, total_bytes=total_size, speed=0.0
                    )
                    return

                if self.is_paused:
                    self.db.update_download_progress(
                        self.task_id, status="paused",
                        progress=(downloaded / total_size * 100) if total_size else 0,
                        downloaded_bytes=downloaded, total_bytes=total_size, speed=0.0
                    )
                    return

                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    now = time.time()
                    elapsed = now - self.last_time
                    if elapsed >= 0.8:  # Update UI every 800ms
                        speed = (downloaded - self.last_bytes) / elapsed
                        self.last_time = now
                        self.last_bytes = downloaded
                        prog = (downloaded / total_size * 100) if total_size else 0
                        self.db.update_download_progress(
                            self.task_id, status="downloading", progress=round(prog, 1),
                            downloaded_bytes=downloaded, total_bytes=total_size, speed=round(speed, 1)
                        )

        # Download completed
        if os.path.exists(part_path):
            if os.path.exists(final_path):
                os.remove(final_path)
            os.rename(part_path, final_path)
            file_size = os.path.getsize(final_path)
            self.db.update_download_filepath(self.task_id, final_path, file_size)
            self.db.update_download_progress(
                self.task_id, status="completed", progress=100.0,
                downloaded_bytes=file_size, total_bytes=file_size, speed=0.0
            )

    def _download_via_ytdlp(self):
        clean_title = sanitize_filename(self.title)
        outtmpl = os.path.join(self.output_dir, f"{clean_title}_%(id)s.%(ext)s")

        def hook(d):
            if self.is_cancelled:
                raise Exception("Download cancelled by user.")
            if self.is_paused:
                raise Exception("Download paused by user.")

            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                speed = d.get("speed") or 0.0
                prog = (downloaded / total * 100) if total else 0
                self.db.update_download_progress(
                    self.task_id, status="downloading", progress=round(prog, 1),
                    downloaded_bytes=downloaded, total_bytes=total, speed=round(speed, 1)
                )
            elif d["status"] == "finished":
                final_filename = d.get("filename")
                if final_filename and os.path.exists(final_filename):
                    file_size = os.path.getsize(final_filename)
                    self.db.update_download_filepath(self.task_id, final_filename, file_size)
                    self.db.update_download_progress(
                        self.task_id, status="completed", progress=100.0,
                        downloaded_bytes=file_size, total_bytes=file_size, speed=0.0
                    )

        ydl_opts = {
            "format": self.format_selector or "best",
            "outtmpl": outtmpl,
            "progress_hooks": [hook],
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "geo_bypass": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([self.url])


class DownloadManager:
    def __init__(self, db: Database):
        self.db = db
        self.tasks: Dict[str, DownloadTask] = {}
        self.download_folder = self.db.get_setting(
            "download_folder",
            get_default_download_dir()
        )
        os.makedirs(self.download_folder, exist_ok=True)

    def create_download(self, url: str, title: str, quality_label: str,
                        format_selector: str, direct_url: Optional[str],
                        thumbnail: str = "", duration: int = 0,
                        auto_start: bool = True) -> str:
        download_id = str(uuid.uuid4())
        item = {
            "id": download_id,
            "url": url,
            "title": title or "Universal Video",
            "thumbnail": thumbnail,
            "duration": duration,
            "quality": quality_label,
            "format": "mp4",
            "status": "queued",
            "progress": 0.0,
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "speed": 0.0,
        }
        self.db.add_download(item)

        task = DownloadTask(
            task_id=download_id,
            url=url,
            title=title,
            format_selector=format_selector,
            direct_url=direct_url,
            output_dir=self.download_folder,
            db=self.db
        )
        self.tasks[download_id] = task
        if auto_start:
            task.start()
        return download_id

    def pause_download(self, download_id: str):
        if download_id in self.tasks:
            self.tasks[download_id].pause()
        self.db.update_download_progress(
            download_id, status="paused", progress=0.0,
            downloaded_bytes=0, total_bytes=0, speed=0.0
        )

    def resume_download(self, download_id: str):
        record = self.db.get_download(download_id)
        if not record:
            return
        task = DownloadTask(
            task_id=download_id,
            url=record["url"],
            title=record["title"],
            format_selector=record.get("quality", "best"),
            direct_url=None,
            output_dir=self.download_folder,
            db=self.db
        )
        self.tasks[download_id] = task
        task.resume()

    def cancel_download(self, download_id: str):
        if download_id in self.tasks:
            self.tasks[download_id].cancel()
            del self.tasks[download_id]
        self.db.update_download_progress(
            download_id, status="cancelled", progress=0.0,
            downloaded_bytes=0, total_bytes=0, speed=0.0
        )
