"""
Universal Video Downloader & Private Media Manager.
Main entry point serving FastAPI backend, Android-styled UI,
and background floating overlay assistant.
"""

import os
import sys
import time
import threading
from typing import Optional, Dict, Any
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from core.database import Database
from core.detector import MediaDetector
from core.downloader import DownloadManager
from core.vault import VaultManager
from core.storage_manager import StorageManager
from core.overlay import DesktopFloatingOverlay

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "ui", "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "ui", "templates")

# Initialize Core Services
db = Database()
detector = MediaDetector()
downloader = DownloadManager(db)
vault = VaultManager(db)
storage = StorageManager(db)

# Floating overlay
overlay_assistant: Optional[DesktopFloatingOverlay] = None

app = FastAPI(title="Universal Downloader API")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# --- Models ---
class AnalyzeRequest(BaseModel):
    url: str

class DownloadRequest(BaseModel):
    url: str
    title: str
    quality_label: str
    format_selector: str
    direct_url: Optional[str] = None
    thumbnail: Optional[str] = ""
    duration: Optional[int] = 0

class PinRequest(BaseModel):
    pin: str

class HideVaultRequest(BaseModel):
    download_id: str

class ToggleOverlayRequest(BaseModel):
    enabled: bool


# --- Web UI Routes ---
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(TEMPLATES_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()


# --- Media Detection API ---
@app.post("/api/analyze")
async def analyze_url(req: AnalyzeRequest):
    if not req.url or not req.url.strip():
        raise HTTPException(status_code=400, detail="Empty URL provided.")
    result = detector.analyze_url(req.url.strip())
    if result.get("success"):
        db.record_history(req.url.strip(), result.get("title", ""), result.get("thumbnail", ""))
    return result


# --- Downloader API ---
@app.post("/api/download")
async def start_download(req: DownloadRequest):
    download_id = downloader.create_download(
        url=req.url,
        title=req.title,
        quality_label=req.quality_label,
        format_selector=req.format_selector,
        direct_url=req.direct_url,
        thumbnail=req.thumbnail or "",
        duration=req.duration or 0
    )
    return {"success": True, "download_id": download_id}

@app.get("/api/downloads")
async def get_downloads(filter: Optional[str] = None, search: Optional[str] = None, sort: str = "newest"):
    return db.get_downloads(filter_status=filter, include_vault=False, search=search, sort_by=sort)

@app.post("/api/downloads/{download_id}/pause")
async def pause_download(download_id: str):
    downloader.pause_download(download_id)
    return {"success": True}

@app.post("/api/downloads/{download_id}/resume")
async def resume_download(download_id: str):
    downloader.resume_download(download_id)
    return {"success": True}

@app.post("/api/downloads/{download_id}/cancel")
async def cancel_download(download_id: str):
    downloader.cancel_download(download_id)
    return {"success": True}

@app.delete("/api/downloads/{download_id}")
async def delete_download(download_id: str):
    item = db.get_download(download_id)
    if item and item.get("file_path") and os.path.exists(item["file_path"]):
        try:
            os.remove(item["file_path"])
        except Exception:
            pass
    db.delete_download(download_id)
    return {"success": True}


# --- Private Vault API ---
@app.get("/api/vault/status")
async def get_vault_status():
    vault.check_auto_lock()
    return vault.get_vault_stats()

@app.post("/api/vault/set-pin")
async def set_vault_pin(req: PinRequest):
    if len(req.pin) < 4:
        raise HTTPException(status_code=400, detail="PIN must be at least 4 digits.")
    vault.set_pin(req.pin)
    return {"success": True}

@app.post("/api/vault/unlock")
async def unlock_vault(req: PinRequest):
    unlocked = vault.verify_and_unlock(req.pin)
    if not unlocked:
        raise HTTPException(status_code=401, detail="Invalid PIN.")
    return {"success": True}

@app.post("/api/vault/lock")
async def lock_vault():
    vault.lock()
    return {"success": True}

@app.post("/api/vault/hide")
async def hide_video(req: HideVaultRequest):
    try:
        item = vault.hide_video(req.download_id)
        return {"success": True, "vault_item": item}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/vault/items")
async def get_vault_items():
    vault.check_auto_lock()
    if not vault.is_unlocked:
        raise HTTPException(status_code=403, detail="Vault is locked.")
    items = db.get_vault_items()
    # Add human readable sizes
    for it in items:
        it["file_size_str"] = storage.get_storage_stats().get("downloads_size_str", "0 B")
    return items

@app.post("/api/vault/restore/{vault_id}")
async def restore_vault_video(vault_id: str):
    try:
        restored_path = vault.restore_video(vault_id)
        return {"success": True, "restored_path": restored_path}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/vault/play/{vault_id}")
async def play_vault_video(vault_id: str):
    try:
        temp_file = vault.decrypt_for_playback(vault_id)
        filename = os.path.basename(temp_file)
        return {"success": True, "stream_url": f"/media/vault_temp/{filename}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Storage API ---
@app.get("/api/storage/stats")
async def get_storage_stats():
    return storage.get_storage_stats()

@app.post("/api/storage/clean-temp")
async def clean_temp_storage():
    freed = storage.clean_temp_files()
    from core.storage_manager import format_bytes
    return {"success": True, "freed_bytes": freed, "freed_str": format_bytes(freed)}


latest_sniffed_url: Optional[str] = None

@app.get("/api/overlay/latest-url")
async def get_latest_url():
    global latest_sniffed_url
    url = latest_sniffed_url
    latest_sniffed_url = None  # Reset once fetched
    return {"url": url}

# --- Settings & Overlay API ---
@app.get("/api/settings")
async def get_settings():
    return db.get_all_settings()

@app.post("/api/overlay/toggle")
async def toggle_overlay(req: ToggleOverlayRequest):
    global overlay_assistant
    db.set_setting("floating_button_enabled", "true" if req.enabled else "false")
    if req.enabled:
        start_overlay()
    else:
        if overlay_assistant:
            overlay_assistant.stop()
            overlay_assistant = None
    return {"success": True, "enabled": req.enabled}


# --- Video Streaming Endpoint ---
@app.get("/media/stream/{download_id}")
async def stream_media(download_id: str):
    item = db.get_download(download_id)
    if not item or not item.get("file_path") or not os.path.exists(item["file_path"]):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(item["file_path"], media_type="video/mp4")

@app.get("/media/vault_temp/{filename}")
async def stream_vault_temp(filename: str):
    temp_path = os.path.join(os.path.expanduser("~"), ".universal_downloader", "temp_playback", filename)
    if not os.path.exists(temp_path):
        raise HTTPException(status_code=404, detail="Temp stream not found.")
    return FileResponse(temp_path, media_type="video/mp4")


def on_floating_bubble_click(detected_url: str):
    global latest_sniffed_url
    print(f"[Floating Button Clicked] Detected URL: {detected_url}")
    if detected_url:
        latest_sniffed_url = detected_url


def start_overlay():
    global overlay_assistant
    if overlay_assistant is None:
        overlay_assistant = DesktopFloatingOverlay(on_trigger_callback=on_floating_bubble_click)
        overlay_assistant.start()


def run_server():
    uvicorn.run(app, host="127.0.0.1", port=5824, log_level="warning")


def main():
    # Start server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(1.2)  # Give server a moment to bind

    # Start floating assistant if enabled
    if db.get_setting("floating_button_enabled", "true") == "true":
        try:
            start_overlay()
        except Exception as e:
            print(f"Overlay initialization notice: {e}")

    print("=" * 60)
    print("⚡ UNIVERSAL VIDEO DOWNLOADER & PRIVATE MEDIA VAULT")
    print("Web UI running at: http://127.0.0.1:5824")
    print("=" * 60)

    # Launch native mobile frame window if pywebview available
    try:
        import webview
        # 420x840 simulates a standard modern Android mobile screen ratio
        window = webview.create_window(
            "Universal Downloader",
            "http://127.0.0.1:5824",
            width=420,
            height=840,
            resizable=True
        )
        webview.start()
    except Exception as e:
        print(f"PyWebView not available or closed ({e}). Access UI at http://127.0.0.1:5824")
        # Keep server alive in console mode
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Shutting down...")


if __name__ == "__main__":
    main()
