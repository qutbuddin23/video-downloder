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
import warnings
from typing import Dict, Any, Optional
import requests
from core.database import Database
from core.storage_manager import format_bytes
from core.paths import get_default_download_dir

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*Support for Python version.*deprecated.*")


def sanitize_filename(name: str) -> str:
    """Sanitize string to be safe for filenames across OS platforms."""
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    clean = clean.replace(" ", "_").strip(" ._")
    return clean[:100] or "video"


def scan_file_to_android_gallery(file_path: str):
    """Notify Android MediaStore so the video appears in Gallery, Photos, and Downloads immediately."""
    if not file_path or not os.path.exists(file_path):
        return
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        if activity:
            MediaScannerConnection = autoclass("android.media.MediaScannerConnection")
            String = autoclass("java.lang.String")
            paths = [String(file_path)]
            MediaScannerConnection.scanFile(activity.getApplicationContext(), paths, None, None)
            print(f"[MediaScanner] Scanned {file_path} into Android MediaStore/Gallery")
    except Exception as e:
        print(f"[MediaScanner] Scan notice: {e}")


def get_android_sdk_level() -> int:
    """Safely retrieves Android SDK API level across all PyJNIus / Android versions."""
    try:
        import sys
        if hasattr(sys, 'getandroidapilevel'):
            return int(sys.getandroidapilevel())
    except Exception:
        pass
    try:
        from jnius import autoclass
        BuildVersion = autoclass("android.os.Build$VERSION")
        return int(BuildVersion.SDK_INT)
    except Exception:
        pass
    return 30


class AndroidNotificationHelper:
    """Live Android status bar notifications with real-time download progress bar."""
    CHANNEL_ID = "universal_downloader_channel"
    CHANNEL_NAME = "Video Downloads"
    _channel_created = False

    @classmethod
    def _init_channel(cls, context):
        if cls._channel_created or not context:
            return
        try:
            from jnius import autoclass
            if get_android_sdk_level() >= 26:
                NotificationChannel = autoclass("android.app.NotificationChannel")
                NotificationManager = autoclass("android.app.NotificationManager")
                Context = autoclass("android.content.Context")
                String = autoclass("java.lang.String")
                nm = context.getSystemService(Context.NOTIFICATION_SERVICE)
                channel = NotificationChannel(
                    String(cls.CHANNEL_ID),
                    String(cls.CHANNEL_NAME),
                    NotificationManager.IMPORTANCE_LOW
                )
                channel.setDescription(String("Progress and completion of video downloads"))
                channel.enableVibration(False)
                channel.setSound(None, None)
                nm.createNotificationChannel(channel)
            cls._channel_created = True
        except Exception as e:
            print(f"[Notifications] Channel init notice: {e}")

    @classmethod
    def update_progress(cls, notification_id: int, title: str, progress: float, speed_str: str = ""):
        try:
            from jnius import autoclass, cast
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            if not activity:
                return
            context = activity.getApplicationContext()
            cls._init_channel(context)

            NotificationManager = autoclass("android.app.NotificationManager")
            Notification = autoclass("android.app.Notification")
            Context = autoclass("android.content.Context")
            String = autoclass("java.lang.String")
            nm = context.getSystemService(Context.NOTIFICATION_SERVICE)

            title_str = String(f"⬇ {title[:40]}")
            sub_text = f"Downloading: {progress:.1f}%"
            if speed_str:
                sub_text += f" • {speed_str}"
            body_str = String(sub_text)

            if get_android_sdk_level() >= 26:
                builder = Notification.Builder(context, String(cls.CHANNEL_ID))
            else:
                builder = Notification.Builder(context)

            builder.setContentTitle(cast("java.lang.CharSequence", title_str))
            builder.setContentText(cast("java.lang.CharSequence", body_str))

            icon_id = 0
            try:
                icon_id = context.getApplicationInfo().icon
            except Exception:
                pass
            if not icon_id:
                try:
                    android_R = autoclass("android.R$drawable")
                    icon_id = getattr(android_R, "stat_sys_download", 17301634)
                except Exception:
                    icon_id = 17301634
            builder.setSmallIcon(int(icon_id))
            builder.setProgress(100, int(progress), False)
            builder.setOngoing(True)
            builder.setOnlyAlertOnce(True)

            nm.notify(int(notification_id), builder.build())
        except Exception as e:
            print(f"[Notifications] update_progress notice: {e}")

    @classmethod
    def show_complete(cls, notification_id: int, title: str):
        try:
            from jnius import autoclass, cast
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            if not activity:
                return
            context = activity.getApplicationContext()
            cls._init_channel(context)

            NotificationManager = autoclass("android.app.NotificationManager")
            Notification = autoclass("android.app.Notification")
            Context = autoclass("android.content.Context")
            String = autoclass("java.lang.String")
            nm = context.getSystemService(Context.NOTIFICATION_SERVICE)

            if get_android_sdk_level() >= 26:
                builder = Notification.Builder(context, String(cls.CHANNEL_ID))
            else:
                builder = Notification.Builder(context)

            builder.setContentTitle(cast("java.lang.CharSequence", String("✅ Download Complete!")))
            builder.setContentText(cast("java.lang.CharSequence", String(title[:50])))

            icon_id = 0
            try:
                icon_id = context.getApplicationInfo().icon
            except Exception:
                pass
            if not icon_id:
                try:
                    android_R = autoclass("android.R$drawable")
                    icon_id = getattr(android_R, "stat_sys_download_done", 17301633)
                except Exception:
                    icon_id = 17301633
            builder.setSmallIcon(int(icon_id))
            builder.setProgress(0, 0, False)
            builder.setOngoing(False)
            builder.setAutoCancel(True)

            nm.notify(int(notification_id), builder.build())
        except Exception as e:
            print(f"[Notifications] show_complete notice: {e}")

    @classmethod
    def cancel(cls, notification_id: int):
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            if not activity:
                return
            context = activity.getApplicationContext()
            NotificationManager = autoclass("android.app.NotificationManager")
            Context = autoclass("android.content.Context")
            nm = context.getSystemService(Context.NOTIFICATION_SERVICE)
            nm.cancel(int(notification_id))
        except Exception as e:
            print(f"[Notifications] cancel notice: {e}")


def open_video_in_external_player(file_path: str) -> bool:
    """Launches the video file in the phone's native video player (VLC, MX Player, Gallery)."""
    if not file_path or not os.path.exists(file_path):
        return False
    try:
        from jnius import autoclass
        from android.runnable import run_on_ui_thread

        @run_on_ui_thread
        def _open():
            try:
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                activity = PythonActivity.mActivity
                if activity:
                    Intent = autoclass("android.content.Intent")
                    Uri = autoclass("android.net.Uri")
                    File = autoclass("java.io.File")
                    file_obj = File(file_path)

                    # Disable StrictMode VmPolicy to allow Uri.fromFile without FileUriExposedException
                    try:
                        StrictMode = autoclass("android.os.StrictMode")
                        VmPolicyBuilder = autoclass("android.os.StrictMode$VmPolicy$Builder")
                        builder = VmPolicyBuilder()
                        StrictMode.setVmPolicy(builder.build())
                    except Exception as sme:
                        print(f"[OpenPlayer] StrictMode policy notice: {sme}")

                    intent = Intent(Intent.ACTION_VIEW)
                    uri = Uri.fromFile(file_obj)
                    intent.setDataAndType(uri, "video/*")
                    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    activity.startActivity(intent)
                    print(f"[OpenPlayer] Launched external player for {file_path}")
            except Exception as ex:
                print(f"[OpenPlayer] Launch exception: {ex}")
        _open()
        return True
    except Exception as e:
        print(f"[OpenPlayer] Error: {e}")
        return False


class DownloadTask:
    def __init__(self, task_id: str, url: str, title: str, format_selector: str,
                 direct_url: Optional[str], output_dir: str, db: Database):
        self.task_id = task_id
        self.notification_id = abs(hash(task_id)) % 100000 + 1
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
        AndroidNotificationHelper.cancel(self.notification_id)

    def resume(self):
        self.is_paused = False
        self.start()

    def cancel(self):
        self.is_cancelled = True
        self.is_paused = False
        AndroidNotificationHelper.cancel(self.notification_id)

    def _run(self):
        try:
            if self.is_paused or self.is_cancelled:
                return

            # Strict guard: Reject image or SVG URLs immediately
            target_to_check = (self.direct_url or self.url).split("?")[0].lower()
            if any(target_to_check.endswith(ext) for ext in [".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico"]):
                raise ValueError(f"Target URL is an image/asset ({target_to_check.split('.')[-1]}), not a valid video.")

            self.db.update_download_progress(
                self.task_id, status="downloading", progress=0.0,
                downloaded_bytes=0, total_bytes=0, speed=0.0
            )

            # Strategy 1: Attempt direct HTTP chunked download if direct_url has direct media extension
            download_succeeded = False
            clean_direct = (self.direct_url or "").split("?")[0].lower()
            if self.direct_url and any(clean_direct.endswith(ext) for ext in [".mp4", ".webm", ".mkv", ".mov", ".ts", ".m4v"]):
                try:
                    self._download_direct_http()
                    download_succeeded = True
                except Exception as direct_err:
                    print(f"[Downloader] Direct HTTP download notice ({direct_err}), falling back to yt-dlp...")
                    if self.is_cancelled or self.is_paused:
                        return

            # Strategy 2: Resilient yt-dlp download with progress hook
            if not download_succeeded:
                self._download_via_ytdlp()

        except Exception as e:
            try:
                AndroidNotificationHelper.cancel(self.notification_id)
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
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Connection": "keep-alive"
        }
        if self.url:
            headers["Referer"] = self.url
            try:
                parts = urllib.parse.urlsplit(self.url)
                headers["Origin"] = f"{parts.scheme}://{parts.netloc}"
            except Exception:
                pass
        clean_title = sanitize_filename(self.title)
        part_path = os.path.join(self.output_dir, f"{clean_title}_{self.task_id[:6]}.part")
        final_path = os.path.join(self.output_dir, f"{clean_title}_{self.task_id[:6]}.mp4")

        downloaded = 0
        if os.path.exists(part_path):
            downloaded = os.path.getsize(part_path)
            headers["Range"] = f"bytes={downloaded}-"

        session = requests.Session()
        resp = session.get(self.direct_url, headers=headers, stream=True, timeout=25)
        
        # Verify content type is not an image or SVG
        c_type = resp.headers.get("content-type", "").lower()
        if "image/" in c_type or "svg" in c_type or "text/html" in c_type:
            raise ValueError(f"Server returned non-video content type ({c_type}).")

        total_size = downloaded
        if "content-length" in resp.headers:
            total_size += int(resp.headers["content-length"])

        mode = "ab" if downloaded > 0 else "wb"
        chunk_size = 1024 * 256  # 256 KB chunks for high throughput
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
                    AndroidNotificationHelper.cancel(self.notification_id)
                    return

                if self.is_paused:
                    self.db.update_download_progress(
                        self.task_id, status="paused",
                        progress=(downloaded / total_size * 100) if total_size else 0,
                        downloaded_bytes=downloaded, total_bytes=total_size, speed=0.0
                    )
                    AndroidNotificationHelper.cancel(self.notification_id)
                    return

                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    now = time.time()
                    elapsed = now - self.last_time
                    if elapsed >= 0.8:
                        speed = (downloaded - self.last_bytes) / elapsed
                        self.last_time = now
                        self.last_bytes = downloaded
                        prog = (downloaded / total_size * 100) if total_size else 0
                        speed_str = f"{speed / (1024*1024):.1f} MB/s" if speed > 0 else ""
                        self.db.update_download_progress(
                            self.task_id, status="downloading", progress=round(prog, 1),
                            downloaded_bytes=downloaded, total_bytes=total_size, speed=round(speed, 1)
                        )
                        AndroidNotificationHelper.update_progress(
                            self.notification_id, self.title, prog, speed_str
                        )

        # Download completed
        if os.path.exists(part_path):
            if os.path.exists(final_path):
                os.remove(final_path)
            os.rename(part_path, final_path)
            file_size = os.path.getsize(final_path)

            # Security sanity check: Disallow tiny files that contain HTML/SVG markup
            if file_size < 1024:
                try:
                    with open(final_path, "rb") as check_f:
                        head = check_f.read(256).lower()
                        if b"<svg" in head or b"<!doctype html" in head or b"<html" in head:
                            os.remove(final_path)
                            raise ValueError("Downloaded file is HTML/SVG markup, not a valid video.")
                except Exception as ve:
                    if os.path.exists(final_path):
                        os.remove(final_path)
                    raise ve

            self.db.update_download_filepath(self.task_id, final_path, file_size)
            self.db.update_download_progress(
                self.task_id, status="completed", progress=100.0,
                downloaded_bytes=file_size, total_bytes=file_size, speed=0.0
            )
            scan_file_to_android_gallery(final_path)
            AndroidNotificationHelper.show_complete(self.notification_id, self.title)
            try:
                from core.overlay import show_android_toast
                show_android_toast(f"✅ Video saved to phone: {clean_title}")
            except Exception:
                pass

    def _download_via_ytdlp(self):
        clean_title = sanitize_filename(self.title)
        outtmpl = os.path.join(self.output_dir, f"{clean_title}_%(id)s.%(ext)s")

        def hook(d):
            if self.is_cancelled:
                AndroidNotificationHelper.cancel(self.notification_id)
                raise Exception("Download cancelled by user.")
            if self.is_paused:
                AndroidNotificationHelper.cancel(self.notification_id)
                raise Exception("Download paused by user.")

            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                speed = d.get("speed") or 0.0
                prog = (downloaded / total * 100) if total else 0
                now = time.time()
                if now - self.last_time >= 0.8:
                    self.last_time = now
                    speed_str = f"{speed / (1024*1024):.1f} MB/s" if speed > 0 else ""
                    self.db.update_download_progress(
                        self.task_id, status="downloading", progress=round(prog, 1),
                        downloaded_bytes=downloaded, total_bytes=total, speed=round(speed, 1)
                    )
                    AndroidNotificationHelper.update_progress(
                        self.notification_id, self.title, prog, speed_str
                    )

        # Build resilient format selector that guarantees video+audio without selecting storyboards/images
        format_sel = self.format_selector or "b"
        if "sb" in format_sel or format_sel == "best":
            format_sel = "b/18/best[vcodec!=none][acodec!=none][format_id!^=sb]/bestvideo[format_id!^=sb]+bestaudio/best[format_id!^=sb]/best"
        elif "+" in format_sel:
            format_sel = f"{format_sel}/b/18/best[vcodec!=none][acodec!=none][format_id!^=sb]/best[format_id!^=sb]/best"
        else:
            format_sel = f"{format_sel}/b/18/best[vcodec!=none][acodec!=none][format_id!^=sb]/best[format_id!^=sb]/best"

        http_hdrs = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if self.url:
            http_hdrs["Referer"] = self.url

        ydl_opts = {
            "format": format_sel,
            "outtmpl": outtmpl,
            "progress_hooks": [hook],
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "geo_bypass": True,
            "concurrent_fragment_downloads": 4,  # High speed multi-part downloads
            "buffersize": 1024 * 1024,          # 1 MB buffer for fast writes
            "retries": 10,
            "fragment_retries": 10,
            "http_headers": http_hdrs,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "android_vr", "web"]
                }
            }
        }

        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(self.url, download=True)
            except Exception as primary_err:
                if self.direct_url and self.direct_url != self.url:
                    print(f"[Downloader] Primary URL error ({primary_err}), trying direct stream URL with yt-dlp...")
                    info = ydl.extract_info(self.direct_url, download=True)
                else:
                    raise primary_err

        # Reliably resolve final file path after download completes
        final_file = None
        if info:
            req_dls = info.get("requested_downloads") or []
            for req in req_dls:
                fp = req.get("filepath") or req.get("filename")
                if fp and os.path.exists(fp):
                    final_file = fp
                    break
            if not final_file:
                fp = info.get("_filename")
                if fp and os.path.exists(fp):
                    final_file = fp
            if not final_file:
                try:
                    prepared = ydl.prepare_filename(info)
                    if prepared and os.path.exists(prepared):
                        final_file = prepared
                except Exception:
                    pass

        if not final_file and os.path.exists(self.output_dir):
            for fname in os.listdir(self.output_dir):
                if clean_title in fname and not fname.endswith(".part"):
                    candidate = os.path.join(self.output_dir, fname)
                    if os.path.isfile(candidate):
                        final_file = candidate
                        break

        if final_file and os.path.exists(final_file):
            file_size = os.path.getsize(final_file)

            # Security sanity check: Disallow tiny files that contain HTML/SVG markup
            if file_size < 1024:
                try:
                    with open(final_file, "rb") as check_f:
                        head = check_f.read(256).lower()
                        if b"<svg" in head or b"<!doctype html" in head or b"<html" in head:
                            os.remove(final_file)
                            raise ValueError("Downloaded file is HTML/SVG markup, not a valid video.")
                except Exception as ve:
                    if os.path.exists(final_file):
                        os.remove(final_file)
                    raise ve

            self.db.update_download_filepath(self.task_id, final_file, file_size)
            self.db.update_download_progress(
                self.task_id, status="completed", progress=100.0,
                downloaded_bytes=file_size, total_bytes=file_size, speed=0.0
            )
            scan_file_to_android_gallery(final_file)
            AndroidNotificationHelper.show_complete(self.notification_id, self.title)
            try:
                from core.overlay import show_android_toast
                show_android_toast(f"✅ Video saved to phone: {clean_title}")
            except Exception:
                pass
        else:
            raise Exception("File was not saved to output directory.")


class DownloadManager:
    def __init__(self, db: Database):
        self.db = db
        self.tasks: Dict[str, DownloadTask] = {}
        default_dir = get_default_download_dir()
        saved_dir = self.db.get_setting("download_folder", default_dir)

        # Auto-migrate away from internal sandbox or non-writable paths
        if not saved_dir or "/data/user/0" in saved_dir or ".universal_downloader" in saved_dir or not os.path.exists(saved_dir) or not os.access(saved_dir, os.W_OK):
            saved_dir = default_dir
            self.db.set_setting("download_folder", saved_dir)

        self.download_folder = saved_dir
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

    def open_in_player(self, download_id: str) -> bool:
        """Launches the downloaded video directly in an external video player or gallery."""
        item = self.db.get_download(download_id)
        if item and item.get("file_path") and os.path.exists(item["file_path"]):
            return open_video_in_external_player(item["file_path"])
        return False

