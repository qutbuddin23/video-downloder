"""
Integration tests for the Python standard library HTTP server and REST endpoints.
"""

import os
import json
import time
import socket
import threading
import urllib.request
import urllib.error
import pytest
from app import run_server, db, vault, downloader

SERVER_PORT = 5829
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"


@pytest.fixture(scope="module", autouse=True)
def live_server():
    server_thread = threading.Thread(target=run_server, args=("127.0.0.1", SERVER_PORT), daemon=True)
    server_thread.start()
    
    # Wait for server to bind
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", SERVER_PORT), timeout=0.1):
                break
        except (OSError, ConnectionRefusedError):
            time.sleep(0.05)
    yield
    # Thread will terminate with process exit


def make_request(path, method="GET", data=None):
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"} if data else {}
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.read().decode("utf-8")


def test_serve_index_html():
    status, html = make_request("/")
    assert status == 200
    assert "Universal Downloader" in html
    assert "id=\"app-container\"" in html


def test_serve_static_asset():
    status, css = make_request("/static/css/style.css")
    assert status == 200
    assert "body" in css


def test_vault_status_and_unlock():
    # Lock first
    make_request("/api/vault/lock", method="POST", data={})

    # Check status
    status, raw = make_request("/api/vault/status")
    assert status == 200
    data = json.loads(raw)
    assert data["is_unlocked"] is False

    # Unlock with incorrect PIN fails
    try:
        make_request("/api/vault/unlock", method="POST", data={"pin": "0000"})
        assert False, "Should have failed with 401"
    except urllib.error.HTTPError as e:
        assert e.code == 401

    # Unlock with required default PIN 7232 succeeds
    status, raw = make_request("/api/vault/unlock", method="POST", data={"pin": "7232"})
    assert status == 200
    data = json.loads(raw)
    assert data["success"] is True

    # Status now shows unlocked
    status, raw = make_request("/api/vault/status")
    data = json.loads(raw)
    assert data["is_unlocked"] is True


def test_downloads_api():
    status, raw = make_request("/api/downloads")
    assert status == 200
    items = json.loads(raw)
    assert isinstance(items, list)


def test_storage_api():
    status, raw = make_request("/api/storage/stats")
    assert status == 200
    stats = json.loads(raw)
    assert "total_disk" in stats
    assert "free_disk_str" in stats


def test_overlay_toggle():
    status, raw = make_request("/api/overlay/toggle", method="POST", data={"enabled": False})
    assert status == 200
    res = json.loads(raw)
    assert res["success"] is True
    assert res["enabled"] is False


def test_auto_download_endpoint_validation():
    # Empty url should fail with 400
    try:
        make_request("/api/auto-download", method="POST", data={"url": ""})
        assert False, "Should have failed with 400"
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_thumbnail_proxy_validation():
    # Empty url should fail with 400
    try:
        make_request("/api/thumbnail-proxy?url=")
        assert False, "Should have failed with 400"
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_clipboard_detect_endpoint():
    status, raw = make_request("/api/clipboard/detect")
    assert status == 200
    resp = json.loads(raw)
    assert "has_video" in resp
    assert isinstance(resp["has_video"], bool)
    assert "url" in resp


def test_overlay_status_and_permission():
    status_code, raw = make_request("/api/overlay/status")
    assert status_code == 200
    status = json.loads(raw)
    assert "enabled" in status
    assert "can_draw" in status
    assert "is_android" in status

    perm_code, perm_raw = make_request("/api/overlay/request-permission", method="POST")
    assert perm_code == 200
    perm = json.loads(perm_raw)
    assert "success" in perm


def test_overlay_show_endpoint():
    status_code, raw = make_request("/api/overlay/show", method="POST")
    assert status_code == 200
    res = json.loads(raw)
    assert res["success"] is True
    assert "active" in res


def test_stream_proxy_validation():
    try:
        make_request("/api/stream-proxy?url=")
        assert False, "Should have failed with 400"
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_downloads_open_endpoint():
    # Non-existent download returns success: False
    code, raw = make_request("/api/downloads/non-existent-id/open", method="POST")
    assert code == 200
    res = json.loads(raw)
    assert res["success"] is False


def test_media_open_url_endpoint():
    code, raw = make_request("/api/media/open-url", method="POST", data={"url": "https://example.com/video.mp4"})
    assert code == 200
    res = json.loads(raw)
    assert "success" in res


def test_overlay_url_detection():
    from core.overlay import detect_video_url
    assert detect_video_url("https://www.youtube.com/watch?v=123") == "https://www.youtube.com/watch?v=123"
    assert detect_video_url("https://www.theyarehuge.com/v/test-video") == "https://www.theyarehuge.com/v/test-video"
    assert detect_video_url("Check out this link: https://cdn.example.com/video.mp4 cool right?") == "https://cdn.example.com/video.mp4"
    assert detect_video_url("https://example.com/logo.svg") is None
    assert detect_video_url("random text with no url") is None




