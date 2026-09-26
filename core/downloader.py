"""
Multi-Threaded Download Manager for Universal Video Downloader.
Handles chunked HTTP downloads with Range headers, yt-dlp streaming downloads,
pause/resume, progress, speed, ETA, and state persistence in SQLite.
"""

import os
import sys
import re
import time
import uuid
import threading
import urllib.parse
import warnings
from typing import Dict, Any, Optional
import requests
from core.database import Database
from core.storage_manager import format_bytes
from core.paths import get_default_download_dir, is_directory_writable, get_base_data_dir
from core.mega import is_mega_url, get_mega_file_info, download_mega_file, parse_mega_url
from core.terabox import is_terabox_url, get_terabox_file_info
from core.detector import DIRECT_DOWNLOAD_EXTS, is_direct_download_url

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*Support for Python version.*deprecated.*")


class SafeStreamWrapper:
    """Wraps sys.stdout / sys.stderr so any .write() or .flush() calls never crash."""
    def __init__(self, target):
        self._target = target

    def write(self, s):
        try:
            if hasattr(self._target, "write") and callable(self._target.write):
                return self._target.write(str(s))
        except Exception:
            pass
        return len(s) if isinstance(s, (str, bytes)) else 0

    def flush(self):
        try:
            if hasattr(self._target, "flush") and callable(self._target.flush):
                self._target.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._target, name, None)


# Safeguard standard error and standard output against string or non-stream replacements on Android
if not hasattr(sys.stderr, "write") or isinstance(sys.stderr, str):
    sys.stderr = SafeStreamWrapper(sys.stderr)
if not hasattr(sys.stdout, "write") or isinstance(sys.stdout, str):
    sys.stdout = SafeStreamWrapper(sys.stdout)


class SafeYtdlLogger:
    """Safe logger for yt-dlp that never relies on sys.stderr or sys.stdout having a write attribute."""
    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        try:
            print(f"[yt-dlp] {msg}")
        except Exception:
            pass

    def write(self, msg):
        pass

    def flush(self):
        pass



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
    def _get_context(cls):
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            if PythonActivity.mActivity:
                return PythonActivity.mActivity.getApplicationContext() or PythonActivity.mActivity
        except Exception:
            pass
        try:
            from jnius import autoclass
            PythonService = autoclass("org.kivy.android.PythonService")
            if PythonService.mService:
                return PythonService.mService.getApplicationContext() or PythonService.mService
        except Exception:
            pass
        return None

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
            context = cls._get_context()
            if not context:
                return
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
            context = cls._get_context()
            if not context:
                return
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
    def show_error(cls, notification_id: int, title: str, error_msg: str = ""):
        try:
            from jnius import autoclass, cast
            context = cls._get_context()
            if not context:
                return
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

            err_text = error_msg if error_msg else "Download failed"
            builder.setContentTitle(cast("java.lang.CharSequence", String("❌ Download Failed")))
            builder.setContentText(cast("java.lang.CharSequence", String(f"{title[:30]}: {err_text[:40]}")))

            icon_id = 0
            try:
                icon_id = context.getApplicationInfo().icon
            except Exception:
                pass
            if not icon_id:
                try:
                    android_R = autoclass("android.R$drawable")
                    icon_id = getattr(android_R, "stat_notify_error", 17301624)
                except Exception:
                    icon_id = 17301624
            builder.setSmallIcon(int(icon_id))
            builder.setProgress(0, 0, False)
            builder.setOngoing(False)
            builder.setAutoCancel(True)

            nm.notify(int(notification_id), builder.build())
        except Exception as e:
            print(f"[Notifications] show_error notice: {e}")

    @classmethod
    def cancel(cls, notification_id: int):
        try:
            from jnius import autoclass
            context = cls._get_context()
            if not context:
                return
            NotificationManager = autoclass("android.app.NotificationManager")
            Context = autoclass("android.content.Context")
            nm = context.getSystemService(Context.NOTIFICATION_SERVICE)
            nm.cancel(int(notification_id))
        except Exception as e:
            print(f"[Notifications] cancel notice: {e}")


def open_video_in_external_player(file_path: str) -> bool:
    """Launches the downloaded file in the phone's native app (player, installer, viewer)."""
    if not file_path or not os.path.exists(file_path):
        return False

    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".apk":
        mime_type = "application/vnd.android.package-archive"
    elif ext in [".zip", ".rar", ".7z", ".tar", ".gz"]:
        mime_type = "application/zip"
    elif ext == ".pdf":
        mime_type = "application/pdf"
    elif ext in [".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg"]:
        mime_type = "audio/*"
    elif ext in [".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".3gp"]:
        mime_type = "video/*"
    else:
        import mimetypes
        mime_type = mimetypes.guess_type(file_path)[0] or "*/*"

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
                    intent.setDataAndType(uri, mime_type)
                    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    activity.startActivity(intent)
                    print(f"[OpenPlayer] Launched external app ({mime_type}) for {file_path}")
            except Exception as ex:
                print(f"[OpenPlayer] Launch exception: {ex}")
        _open()
        return True
    except Exception as e:
        # Desktop / Windows fallback testing
        try:
            if sys.platform == "win32":
                os.startfile(file_path)
                return True
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", file_path])
                return True
            elif sys.platform.startswith("linux") and not os.path.exists("/system/build.prop"):
                import subprocess
                subprocess.Popen(["xdg-open", file_path])
                return True
        except Exception:
            pass
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
        self._direct_http_tried = False
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

            # Ensure output directory is actually writable before starting write operations
            if not is_directory_writable(self.output_dir):
                print(f"[Downloader] self.output_dir '{self.output_dir}' is NOT writable! Migrating...")
                self.output_dir = get_default_download_dir()
                if not is_directory_writable(self.output_dir):
                    self.output_dir = os.path.join(get_base_data_dir(), "downloads")
                    os.makedirs(self.output_dir, exist_ok=True)
                print(f"[Downloader] Migrated output_dir to: '{self.output_dir}'")

            self.db.update_download_progress(
                self.task_id, status="downloading", progress=0.0,
                downloaded_bytes=0, total_bytes=0, speed=0.0
            )

            # Strategy 1: Native MEGA.nz cloud download with AES-CTR decryption
            if is_mega_url(self.url) or self.format_selector == "mega":
                self._download_mega()
                return

            # Strategy 2: TeraBox cloud share link resolution
            if is_terabox_url(self.url) or self.format_selector in ("terabox_direct", "terabox_gw"):
                if not self.direct_url:
                    tb_info = get_terabox_file_info(self.url)
                    if tb_info.get("success"):
                        self.direct_url = tb_info.get("direct_url")
                        if tb_info.get("title"):
                            self.title = tb_info.get("title")
                self._download_direct_http(custom_referer="https://www.terabox.com/")
                return

            # Strategy 3: HLS / DASH stream manifests (.m3u8, .mpd) -> must use streaming engine
            clean_direct = (self.direct_url or "").split("?")[0].lower()
            clean_url = (self.url or "").split("?")[0].lower()
            is_hls = clean_direct.endswith(".m3u8") or clean_direct.endswith(".mpd") or clean_url.endswith(".m3u8") or clean_url.endswith(".mpd")
            if is_hls:
                self._download_via_ytdlp(override_url=self.direct_url or self.url)
                return

            # Strategy 4: Direct file download (.mp4, .zip, .apk, etc.) OR explicitly selected/detected direct stream
            is_direct_input = is_direct_download_url(self.url)
            is_direct_stream = any(clean_direct.endswith(ext) for ext in DIRECT_DOWNLOAD_EXTS)
            if self.format_selector == "direct" or is_direct_input or is_direct_stream:
                try:
                    self._direct_http_tried = True
                    self._download_direct_http()
                    return
                except Exception as direct_err:
                    print(f"[Downloader] Direct HTTP download notice ({direct_err}), falling back to streaming engine...")
                    if self.is_cancelled or self.is_paused:
                        return
                    # Fallback to yt-dlp on direct_url or url
                    try:
                        self._download_via_ytdlp(override_url=self.direct_url or self.url)
                        return
                    except Exception:
                        raise direct_err

            # Strategy 5: Resilient yt-dlp download for all platforms (YouTube, Twitter, TikTok, Tube sites, etc.)
            self._download_via_ytdlp(override_url=self.url)

        except Exception as e:
            try:
                if self.is_cancelled:
                    AndroidNotificationHelper.cancel(self.notification_id)
                    self.db.update_download_progress(
                        self.task_id, status="cancelled", progress=0.0,
                        downloaded_bytes=0, total_bytes=0, speed=0.0,
                        error_message="Download cancelled by user."
                    )
                elif self.is_paused:
                    pass
                else:
                    AndroidNotificationHelper.show_error(self.notification_id, self.title, str(e))
                    self.db.update_download_progress(
                        self.task_id, status="failed", progress=0.0,
                        downloaded_bytes=0, total_bytes=0, speed=0.0,
                        error_message=str(e)
                    )
            except Exception:
                pass

    def _download_mega(self):
        """Executes native streaming download and AES-CTR decryption for MEGA.nz files."""
        info = get_mega_file_info(self.url)
        if not info.get("success"):
            raise ValueError(info.get("error_message", "Failed to resolve MEGA link."))

        filename = info.get("filename") or f"{sanitize_filename(self.title)}.bin"
        direct_url = info.get("direct_url")
        fmt = info.get("formats", [{}])[0]
        key_bytes = fmt.get("mega_key_bytes")
        initial_counter = fmt.get("mega_initial_counter")

        clean_fn = sanitize_filename(filename)
        final_path = os.path.join(self.output_dir, clean_fn)

        def _mega_progress(downloaded, total):
            pct = (downloaded / total * 100.0) if total > 0 else 0.0
            now = time.time()
            elapsed = now - self.last_time
            if elapsed >= 0.5 or pct >= 100.0:
                speed = (downloaded - self.last_bytes) / elapsed if elapsed > 0 else 0.0
                self.last_time = now
                self.last_bytes = downloaded
                self.current_speed = speed
                speed_str = f"{(speed / (1024*1024)):.2f} MB/s" if speed > 0 else "0 MB/s"
                AndroidNotificationHelper.update_progress(self.notification_id, self.title, pct, speed_str)
                self.db.update_download_progress(
                    self.task_id, status="downloading", progress=pct,
                    downloaded_bytes=downloaded, total_bytes=total, speed=speed
                )

        success = download_mega_file(
            task=self,
            direct_url=direct_url,
            key_bytes=key_bytes,
            initial_counter=initial_counter,
            output_path=final_path,
            progress_callback=_mega_progress
        )
        if success:
            final_size = os.path.getsize(final_path)
            self.db.update_download_progress(
                self.task_id, status="completed", progress=100.0,
                downloaded_bytes=final_size, total_bytes=final_size, speed=0.0
            )
            self.db.update_download_filepath(self.task_id, final_path, final_size)
            AndroidNotificationHelper.show_complete(self.notification_id, self.title)
            scan_media_file(final_path)

    def _download_direct_http(self, custom_referer: str = ""):
        target_url = self.direct_url or self.url
        if not target_url:
            raise ValueError("No download URL provided.")

        clean_target = (target_url or "").split("?")[0].lower()
        ext = "mp4"
        for candidate in DIRECT_DOWNLOAD_EXTS:
            if clean_target.endswith(candidate):
                ext = candidate.lstrip('.')
                break

        clean_title = sanitize_filename(self.title)
        if "." in clean_title and len(clean_title.rsplit(".", 1)[1]) in (2, 3, 4, 5):
            final_filename = clean_title
        else:
            final_filename = f"{clean_title}_{self.task_id[:6]}.{ext}"

        part_path = os.path.join(self.output_dir, f"{final_filename}.part")
        final_path = os.path.join(self.output_dir, final_filename)

        # Determine appropriate referer
        referer = custom_referer
        if not referer:
            clean_url = (self.url or "").split("?")[0].lower()
            if self.url and not any(clean_url.endswith(e) for e in DIRECT_DOWNLOAD_EXTS):
                referer = self.url
            elif target_url:
                try:
                    parts = urllib.parse.urlsplit(target_url)
                    referer = f"{parts.scheme}://{parts.netloc}/"
                except Exception:
                    pass

        user_agents = [
            "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ]

        session = requests.Session()
        domain = urllib.parse.urlsplit(self.url or target_url).netloc
        try:
            from core.detector import MediaDetector
            stored_cookies = MediaDetector._cookie_jar.get(domain, {})
            if stored_cookies:
                session.cookies.update(stored_cookies)
            elif referer and referer.startswith("http"):
                session.get(referer, headers={"User-Agent": user_agents[0]}, timeout=8, allow_redirects=True)
        except Exception:
            pass

        resp = None
        for ua in user_agents:
            headers = {
                "User-Agent": ua,
                "Accept": "video/webm,video/ogg,video/*;q=0.9,application/ogg;q=0.7,audio/*;q=0.6,*/*;q=0.5",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "identity",
                "Connection": "keep-alive",
                "Sec-Fetch-Dest": "video",
                "Sec-Fetch-Mode": "no-cors"
            }
            if referer:
                headers["Referer"] = referer
                try:
                    parts = urllib.parse.urlsplit(referer)
                    headers["Origin"] = f"{parts.scheme}://{parts.netloc}"
                except Exception:
                    pass

            downloaded = 0
            if os.path.exists(part_path):
                downloaded = os.path.getsize(part_path)
                headers["Range"] = f"bytes={downloaded}-"

            try:
                r = session.get(target_url, headers=headers, stream=True, timeout=25)
                if r.status_code in (200, 206):
                    c_type = r.headers.get("content-type", "").lower()
                    if not ("image/" in c_type or "svg" in c_type or "text/html" in c_type):
                        resp = r
                        break
                elif r.status_code in (403, 470, 401):
                    continue
            except Exception:
                continue

        if not resp:
            headers = {
                "User-Agent": user_agents[0],
                "Accept": "video/webm,video/ogg,video/*;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "identity",
            }
            if referer:
                headers["Referer"] = referer
            resp = session.get(target_url, headers=headers, stream=True, timeout=25)

        # Strictly validate response status code
        if resp.status_code not in (200, 206):
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except Exception:
                    pass
            raise ValueError(f"HTTP Server returned status {resp.status_code}: {resp.reason}")

        # Strictly validate content type
        c_type = resp.headers.get("content-type", "").lower()
        if "image/" in c_type or "svg" in c_type or "text/html" in c_type:
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except Exception:
                    pass
            raise ValueError(f"Server returned non-video content type ({c_type}).")

        total_size = downloaded
        if "content-length" in resp.headers:
            total_size += int(resp.headers["content-length"])

        mode = "ab" if downloaded > 0 else "wb"
        chunk_size = 1024 * 256  # 256 KB chunks for high throughput
        self.last_time = time.time()
        self.last_bytes = downloaded

        first_chunk = True
        with open(part_path, mode) as f:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if first_chunk and chunk:
                    first_chunk = False
                    head_sample = chunk[:512].lower()
                    if b"<svg" in head_sample or b"<!doctype html" in head_sample or b"<html" in head_sample:
                        f.close()
                        if os.path.exists(part_path):
                            try:
                                os.remove(part_path)
                            except Exception:
                                pass
                        raise ValueError("Server returned an HTML block page (bot protection / age check) instead of video.")

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
                            raise ValueError("Server returned an HTML block page (bot protection / age check) instead of video.")
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

    def _download_via_ytdlp(self, override_url: Optional[str] = None):
        target_to_use = override_url or self.url
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
            "logtostderr": False,
            "logger": SafeYtdlLogger(),
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
                info = ydl.extract_info(target_to_use, download=True)
            except Exception as primary_err:
                clean_target = (self.direct_url or "").split("?")[0].lower()
                is_direct = any(clean_target.endswith(ext) for ext in [".mp4", ".webm", ".mkv", ".mov", ".ts", ".m4v", ".m3u8", ".mpd"])
                if self.direct_url and self.direct_url != target_to_use:
                    print(f"[Downloader] Primary URL error ({primary_err}), trying direct stream URL with yt-dlp...")
                    try:
                        info = ydl.extract_info(self.direct_url, download=True)
                    except Exception as sec_err:
                        if not getattr(self, "_direct_http_tried", False) and is_direct:
                            self._direct_http_tried = True
                            self._download_direct_http()
                            return
                        raise ValueError("Stream protected or blocked by site (Cloudflare/Bot/Age check). Tap 'Open in Browser' to play/download.")
                else:
                    if not getattr(self, "_direct_http_tried", False) and is_direct:
                        self._direct_http_tried = True
                        self._download_direct_http()
                        return
                    raise ValueError("Stream protected or blocked by site (Cloudflare/Bot/Age check). Tap 'Open in Browser' to play/download.")

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
        if not saved_dir or not is_directory_writable(saved_dir):
            saved_dir = default_dir
            if not is_directory_writable(saved_dir):
                saved_dir = os.path.join(get_base_data_dir(), "downloads")
                os.makedirs(saved_dir, exist_ok=True)
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

