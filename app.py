"""
Universal Video Downloader & Private Media Manager.
Core HTTP Server powered by Python standard library (http.server.ThreadingHTTPServer).
Provides zero external C/Rust dependencies for rock-solid Android (Buildozer) and Desktop execution.
"""

import os
import sys
import json
import time
import mimetypes
import threading
import urllib.parse
import warnings
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any
import requests

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*Support for Python version.*deprecated.*")

from core.paths import (
    get_base_data_dir,
    get_db_path,
    get_vault_dir,
    get_temp_playback_dir,
    get_default_download_dir
)
from core.database import Database
from core.detector import MediaDetector
from core.downloader import DownloadManager
from core.vault import VaultManager
from core.storage_manager import StorageManager, format_bytes
from core.overlay import FloatingOverlayManager, detect_video_url, get_android_clipboard_text, is_running_on_android

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "ui", "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "ui", "templates")

# Initialize Singletons
db = Database()
detector = MediaDetector()
downloader = DownloadManager(db)
vault = VaultManager(db)
storage = StorageManager(db)

overlay_assistant: Optional[FloatingOverlayManager] = None
latest_sniffed_url: Optional[str] = None
latest_auto_download_title: Optional[str] = None
latest_auto_download_id: Optional[str] = None
http_server_instance: Optional[ThreadingHTTPServer] = None


def trigger_auto_download(url: str):
    global latest_auto_download_title, latest_auto_download_id
    try:
        url = url.strip()
        result = detector.analyze_url(url)
        if result.get("success"):
            title = result.get("title", "Universal Video")
            formats = result.get("formats", [])
            best_format = formats[0]["format_id"] if formats else "best"
            dl_id = downloader.create_download(
                url=url,
                title=title,
                quality_label="Auto/Best",
                format_selector=best_format,
                direct_url=result.get("direct_url"),
                thumbnail=result.get("thumbnail", ""),
                duration=result.get("duration", 0),
                auto_start=True
            )
            latest_auto_download_title = title
            latest_auto_download_id = dl_id
            print(f"🚀 [Auto-Download Started] {title} (ID: {dl_id})")
            return True, title, dl_id
    except Exception as e:
        print(f"Auto-download error: {e}")
    return False, "", ""


class UniversalHTTPHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        """Suppress noisy request logs, print errors only."""
        if len(args) > 1 and str(args[1]).startswith(('4', '5')):
            sys.stderr.write(f"[HTTP {args[1]}] {args[0]}\n")

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Range")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def send_json(self, data: Any, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message: str, status: int = 400):
        self.send_json({"error": message, "detail": message}, status=status)

    def read_json_body(self) -> Dict[str, Any]:
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len <= 0:
            return {}
        raw = self.rfile.read(content_len).decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def serve_file(self, file_path: str, content_type: Optional[str] = None):
        if not os.path.isfile(file_path):
            self.send_error_json("File not found", 404)
            return

        if not content_type:
            content_type, _ = mimetypes.guess_type(file_path)
        content_type = content_type or "application/octet-stream"

        file_size = os.path.getsize(file_path)
        range_header = self.headers.get("Range")

        if range_header and range_header.startswith("bytes="):
            try:
                byte_range = range_header.split("=")[1].strip()
                parts = byte_range.split("-")
                start = int(parts[0]) if parts[0] else 0
                end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1

                if start >= file_size or end >= file_size or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{file_size}")
                    self.end_headers()
                    return

                chunk_len = end - start + 1
                self.send_response(206)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Content-Length", str(chunk_len))
                self.send_header("Accept-Ranges", "bytes")
                self.send_cors_headers()
                self.end_headers()

                with open(file_path, "rb") as f:
                    f.seek(start)
                    remaining = chunk_len
                    buffer_size = 64 * 1024
                    while remaining > 0:
                        read_bytes = min(remaining, buffer_size)
                        buf = f.read(read_bytes)
                        if not buf:
                            break
                        self.wfile.write(buf)
                        remaining -= len(buf)
                return
            except (ConnectionResetError, BrokenPipeError):
                return
            except Exception:
                pass

        # Standard 200 response
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Accept-Ranges", "bytes")
        self.send_cors_headers()
        self.end_headers()

        try:
            with open(file_path, "rb") as f:
                while True:
                    buf = f.read(64 * 1024)
                    if not buf:
                        break
                    self.wfile.write(buf)
        except (ConnectionResetError, BrokenPipeError):
            pass

    # --- GET Routes ---
    def do_GET(self):
        global overlay_assistant, latest_sniffed_url, latest_auto_download_title, latest_auto_download_id
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. UI Root
        if path == "/" or path == "/index.html":
            index_path = os.path.join(TEMPLATES_DIR, "index.html")
            self.serve_file(index_path, "text/html; charset=utf-8")
            return

        # 2. Static Assets
        if path.startswith("/static/"):
            rel_path = path[len("/static/"):].lstrip("/\\")
            safe_path = os.path.abspath(os.path.join(STATIC_DIR, rel_path))
            if safe_path.startswith(STATIC_DIR) and os.path.isfile(safe_path):
                self.serve_file(safe_path)
            else:
                self.send_error_json("Asset not found", 404)
            return

        # 3. Media Streams
        if path.startswith("/media/stream/"):
            download_id = path[len("/media/stream/"):].strip("/")
            item = db.get_download(download_id)
            if not item or not item.get("file_path") or not os.path.exists(item["file_path"]):
                self.send_error_json("Media not found", 404)
                return
            self.serve_file(item["file_path"], "video/mp4")
            return

        if path.startswith("/media/vault_temp/"):
            filename = os.path.basename(path[len("/media/vault_temp/"):])
            temp_path = os.path.join(get_temp_playback_dir(), filename)
            if not os.path.isfile(temp_path):
                self.send_error_json("Temp playback file not found", 404)
                return
            self.serve_file(temp_path, "video/mp4")
            return

        # 4. API Endpoints
        if path == "/api/downloads":
            filter_status = query.get("filter", [None])[0]
            search = query.get("search", [None])[0]
            sort = query.get("sort", ["newest"])[0]
            items = db.get_downloads(filter_status=filter_status, include_vault=False, search=search, sort_by=sort)
            self.send_json(items)
            return

        if path == "/api/vault/status":
            vault.check_auto_lock()
            self.send_json(vault.get_vault_stats())
            return

        if path == "/api/vault/items":
            vault.check_auto_lock()
            if not vault.is_unlocked:
                self.send_error_json("Vault is locked", 403)
                return
            items = db.get_vault_items()
            stats = storage.get_storage_stats()
            for it in items:
                it["file_size_str"] = stats.get("downloads_size_str", "0 B")
            self.send_json(items)
            return

        if path.startswith("/api/vault/play/"):
            vault_id = path[len("/api/vault/play/"):].strip("/")
            try:
                temp_file = vault.decrypt_for_playback(vault_id)
                filename = os.path.basename(temp_file)
                self.send_json({"success": True, "stream_url": f"/media/vault_temp/{filename}"})
            except PermissionError as pe:
                self.send_error_json(str(pe), 403)
            except Exception as e:
                self.send_error_json(str(e), 400)
            return

        if path == "/api/storage/stats":
            self.send_json(storage.get_storage_stats())
            return

        if path == "/api/thumbnail-proxy":
            img_url = query.get("url", [""])[0]
            if not img_url:
                self.send_error_json("Missing URL", 400)
                return
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
                resp = requests.get(img_url, headers=headers, timeout=8)
                if resp.status_code == 200:
                    c_type = resp.headers.get("Content-Type", "image/jpeg")
                    self.send_response(200)
                    self.send_header("Content-Type", c_type)
                    self.send_header("Content-Length", str(len(resp.content)))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(resp.content)
                    return
            except Exception:
                pass
            self.send_error_json("Thumbnail fetch failed", 502)
            return

        if path == "/api/overlay/latest-url":
            url = latest_sniffed_url
            title = latest_auto_download_title
            dl_id = latest_auto_download_id
            latest_sniffed_url = None
            latest_auto_download_title = None
            latest_auto_download_id = None
            self.send_json({"url": url, "auto_downloaded": bool(title), "title": title, "download_id": dl_id})
            return

        if path == "/api/settings":
            self.send_json(db.get_all_settings())
            return

        if path == "/api/overlay/status":
            can_draw = overlay_assistant.can_draw_overlays() if overlay_assistant else True
            is_active = overlay_assistant.is_active() if overlay_assistant else False
            self.send_json({
                "enabled": is_active,
                "can_draw": can_draw,
                "is_android": is_running_on_android()
            })
            return

        if path == "/api/clipboard/detect":
            clip_text = get_android_clipboard_text() if is_running_on_android() else ""
            video_url = detect_video_url(clip_text)
            self.send_json({
                "has_video": bool(video_url),
                "url": video_url or "",
                "raw_text": clip_text[:80] if clip_text else ""
            })
            return

        self.send_error_json("Not found", 404)

    # --- POST Routes ---
    def do_POST(self):
        global overlay_assistant
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self.read_json_body()

        if path == "/api/analyze":
            url = body.get("url", "").strip()
            if not url:
                self.send_error_json("Empty URL provided", 400)
                return
            result = detector.analyze_url(url)
            if result.get("success"):
                db.record_history(url, result.get("title", ""), result.get("thumbnail", ""))
            self.send_json(result)
            return

        if path == "/api/download":
            url = body.get("url", "").strip()
            title = body.get("title", "Universal Video")
            quality_label = body.get("quality_label", "720p")
            format_selector = body.get("format_selector", "best")
            direct_url = body.get("direct_url")
            thumbnail = body.get("thumbnail", "")
            duration = body.get("duration", 0)

            download_id = downloader.create_download(
                url=url,
                title=title,
                quality_label=quality_label,
                format_selector=format_selector,
                direct_url=direct_url,
                thumbnail=thumbnail,
                duration=duration
            )
            self.send_json({"success": True, "download_id": download_id})
            return

        if path == "/api/auto-download":
            url = body.get("url", "").strip()
            if not url:
                self.send_error_json("Empty URL provided", 400)
                return
            success, title, dl_id = trigger_auto_download(url)
            self.send_json({"success": success, "title": title, "download_id": dl_id})
            return

        if path.startswith("/api/downloads/") and path.endswith("/pause"):
            parts = path.split("/")
            download_id = parts[3]
            downloader.pause_download(download_id)
            self.send_json({"success": True})
            return

        if path.startswith("/api/downloads/") and path.endswith("/resume"):
            parts = path.split("/")
            download_id = parts[3]
            downloader.resume_download(download_id)
            self.send_json({"success": True})
            return

        if path.startswith("/api/downloads/") and path.endswith("/cancel"):
            parts = path.split("/")
            download_id = parts[3]
            downloader.cancel_download(download_id)
            self.send_json({"success": True})
            return

        if path == "/api/vault/set-pin":
            pin = body.get("pin", "")
            if len(pin) < 4:
                self.send_error_json("PIN must be at least 4 digits", 400)
                return
            vault.set_pin(pin)
            self.send_json({"success": True})
            return

        if path == "/api/vault/unlock":
            pin = body.get("pin", "")
            if vault.verify_and_unlock(pin):
                self.send_json({"success": True})
            else:
                self.send_error_json("Invalid PIN", 401)
            return

        if path == "/api/vault/lock":
            vault.lock()
            self.send_json({"success": True})
            return

        if path == "/api/vault/hide":
            download_id = body.get("download_id", "")
            try:
                item = vault.hide_video(download_id)
                self.send_json({"success": True, "vault_item": item})
            except PermissionError as pe:
                self.send_error_json(str(pe), 403)
            except Exception as e:
                self.send_error_json(str(e), 400)
            return

        if path.startswith("/api/vault/restore/"):
            vault_id = path[len("/api/vault/restore/"):].strip("/")
            try:
                restored_path = vault.restore_video(vault_id)
                self.send_json({"success": True, "restored_path": restored_path})
            except Exception as e:
                self.send_error_json(str(e), 400)
            return

        if path == "/api/storage/clean-temp":
            freed = storage.clean_temp_files()
            self.send_json({"success": True, "freed_bytes": freed, "freed_str": format_bytes(freed)})
            return

        if path == "/api/overlay/toggle":
            enabled = bool(body.get("enabled", False))
            db.set_setting("floating_button_enabled", "true" if enabled else "false")
            if enabled:
                start_overlay()
            else:
                if overlay_assistant:
                    overlay_assistant.stop()
                    overlay_assistant = None
            self.send_json({"success": True, "enabled": enabled})
            return

        if path == "/api/overlay/request-permission":
            if overlay_assistant is None:
                start_overlay()
            res = overlay_assistant.open_overlay_settings() if overlay_assistant else False
            self.send_json({"success": res})
            return

        self.send_error_json("Endpoint not found", 404)

    # --- DELETE Routes ---
    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/downloads/"):
            download_id = path[len("/api/downloads/"):].strip("/")
            item = db.get_download(download_id)
            if item and item.get("file_path") and os.path.exists(item["file_path"]):
                try:
                    os.remove(item["file_path"])
                except Exception:
                    pass
            db.delete_download(download_id)
            self.send_json({"success": True})
            return

        self.send_error_json("Endpoint not found", 404)


def on_floating_bubble_click(detected_url: str):
    global latest_sniffed_url
    print(f"[Floating Button Clicked] Detected URL: {detected_url}")
    if detected_url:
        latest_sniffed_url = detected_url
        threading.Thread(target=trigger_auto_download, args=(detected_url,), daemon=True).start()


def start_overlay():
    global overlay_assistant
    if overlay_assistant is None:
        try:
            overlay_assistant = FloatingOverlayManager(on_trigger_callback=on_floating_bubble_click)
            overlay_assistant.start()
        except Exception as e:
            print(f"Overlay notice: {e}")


def run_server(host: str = "127.0.0.1", port: int = 5824):
    """Starts the multi-threaded standard library HTTP server with bind retry."""
    global http_server_instance
    ThreadingHTTPServer.allow_reuse_address = True
    for attempt in range(5):
        try:
            http_server_instance = ThreadingHTTPServer((host, port), UniversalHTTPHandler)
            print(f"Universal Downloader HTTP Server running at http://{host}:{port}")
            http_server_instance.serve_forever()
            break
        except OSError as oe:
            print(f"Server bind attempt {attempt+1} on {port} failed ({oe}), retrying in 0.5s...")
            time.sleep(0.5)
        except Exception as e:
            print(f"Server stopped: {e}")
            break


def main():
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(1.0)

    if db.get_setting("floating_button_enabled", "true") == "true":
        try:
            start_overlay()
        except Exception as e:
            print(f"Overlay initialization notice: {e}")

    print("=" * 60)
    print("⚡ UNIVERSAL VIDEO DOWNLOADER & PRIVATE MEDIA VAULT")
    print("Web UI running at: http://127.0.0.1:5824")
    print("=" * 60)

    try:
        import webview
        window = webview.create_window(
            "Universal Downloader",
            "http://127.0.0.1:5824",
            width=420,
            height=840,
            resizable=True
        )
        webview.start()
    except Exception as e:
        print(f"PyWebView closed or unavailable ({e}). Server alive at http://127.0.0.1:5824")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Shutting down...")


if __name__ == "__main__":
    main()
