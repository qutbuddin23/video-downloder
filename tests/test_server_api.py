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

