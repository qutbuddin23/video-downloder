"""
Native MEGA.nz Cloud File Resolver and Decryption Engine.
Provides pure-Python metadata retrieval and AES-128-CTR streaming download
for public MEGA file links without requiring external C++ SDKs or binary dependencies.
"""

import os
import re
import json
import base64
import struct
import urllib.parse
from typing import Dict, Any, Optional, Tuple, Callable
import requests
import pyaes
from core.storage_manager import format_bytes


MEGA_URL_PATTERN = re.compile(
    r'mega\.(?:nz|co\.nz)/(?:file/|#!)?([a-zA-Z0-9_-]+)(?:[#!])([a-zA-Z0-9_-]+)',
    re.IGNORECASE
)


def is_mega_url(url: str) -> bool:
    """Checks whether URL matches a MEGA.nz public file pattern."""
    if not url or not isinstance(url, str):
        return False
    return bool(MEGA_URL_PATTERN.search(url))


def parse_mega_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Extracts (file_id, file_key) from a public MEGA link."""
    m = MEGA_URL_PATTERN.search(url or "")
    if m:
        return m.group(1), m.group(2)
    return None, None


def _base64_url_decode(data: str) -> bytes:
    """Decodes URL-safe base64 string with automatic padding."""
    data = data.strip().replace('-', '+').replace('_', '/')
    padding = (4 - len(data) % 4) % 4
    data += '=' * padding
    return base64.b64decode(data)


def _prepare_key(b64_key: str) -> Tuple[Optional[bytes], Optional[int]]:
    """
    Parses a 43-character base64 MEGA file key into:
    - 128-bit AES key (16 bytes)
    - 64-bit IV counter start integer
    """
    try:
        raw = _base64_url_decode(b64_key)
        if len(raw) < 32:
            return None, None
        a32 = struct.unpack(f">{len(raw) // 4}I", raw[:32])
        # 32 bytes = 8 x 32-bit unsigned ints: a, b, c, d, e, f, g, h
        k = (a32[0] ^ a32[4], a32[1] ^ a32[5], a32[2] ^ a32[6], a32[3] ^ a32[7])
        iv = (a32[4], a32[5])
        key_bytes = struct.pack(">4I", *k)
        initial_counter = (iv[0] << 32) | iv[1]
        return key_bytes, initial_counter
    except Exception as e:
        print(f"[MEGA] Key parse error: {e}")
        return None, None


def _decrypt_attr(at_b64: str, key_bytes: bytes) -> Dict[str, Any]:
    """Decrypts MEGA file attributes (JSON metadata containing original filename)."""
    try:
        raw_at = _base64_url_decode(at_b64)
        # AES-CBC decryption with 16 zero-bytes IV across 16-byte blocks
        cbc = pyaes.AESModeOfOperationCBC(key_bytes, iv=b'\x00' * 16)
        decrypted = b"".join(
            cbc.decrypt(raw_at[i:i+16])
            for i in range(0, len(raw_at), 16)
            if len(raw_at[i:i+16]) == 16
        )
        # Remove null byte padding
        clean = decrypted.rstrip(b'\x00')
        if clean.startswith(b'MEGA'):
            clean = clean[4:]
        text = clean.decode('utf-8', errors='replace')
        return json.loads(text)
    except Exception as e:
        print(f"[MEGA] Attribute decrypt error: {e}")
        return {}


def get_mega_file_info(url: str) -> Dict[str, Any]:
    """
    Resolves public MEGA link into file metadata and direct streaming URL.
    Returns standard metadata dictionary compatible with Universal Downloader.
    """
    file_id, file_key = parse_mega_url(url)
    if not file_id or not file_key:
        return {
            "success": False,
            "title": "Invalid MEGA URL",
            "source_url": url,
            "error_message": "Invalid or unparseable MEGA link format."
        }

    key_bytes, initial_counter = _prepare_key(file_key)
    if not key_bytes or initial_counter is None:
        return {
            "success": False,
            "title": "MEGA Decryption Error",
            "source_url": url,
            "error_message": "Failed to parse MEGA encryption key."
        }

    api_url = "https://g.api.mega.co.nz/cs?id=123456789"
    payload = [{"a": "g", "g": 1, "p": file_id}]

    try:
        resp = requests.post(api_url, json=payload, timeout=20)
        if not resp.ok:
            return {
                "success": False,
                "title": "MEGA API Error",
                "source_url": url,
                "error_message": f"MEGA API returned HTTP {resp.status_code}"
            }

        data = resp.json()
        if not isinstance(data, list) or not data:
            return {
                "success": False,
                "title": "MEGA Response Error",
                "source_url": url,
                "error_message": "Empty response from MEGA API."
            }

        res = data[0]
        if isinstance(res, int):
            error_codes = {
                -2: "Invalid file arguments.",
                -9: "File does not exist or has been deleted.",
                -11: "Access denied or account suspended.",
                -16: "File temporarily unavailable or bandwidth limit exceeded."
            }
            err_msg = error_codes.get(res, f"MEGA error code: {res}")
            return {
                "success": False,
                "title": "MEGA File Unavailable",
                "source_url": url,
                "error_message": err_msg
            }

        size = res.get("s", 0)
        direct_url = res.get("g", "")
        enc_attr = res.get("at", "")

        attributes = _decrypt_attr(enc_attr, key_bytes)
        filename = attributes.get("n", f"mega_file_{file_id}")
        ext = os.path.splitext(filename)[1].lstrip('.').lower() or "bin"

        fmt = {
            "format_id": "mega_stream",
            "quality_label": f"MEGA ({ext.upper()})",
            "resolution": "Cloud File",
            "height": 0,
            "ext": ext,
            "codec": "AES-CTR Decrypted",
            "filesize": size,
            "filesize_str": format_bytes(size),
            "has_audio": ext in ["mp4", "mkv", "webm", "mp3", "m4a", "wav"],
            "has_video": ext in ["mp4", "mkv", "webm", "mov", "avi"],
            "direct_url": direct_url,
            "download_selector": "mega",
            "is_mega": True,
            "mega_key_bytes": key_bytes,
            "mega_initial_counter": initial_counter
        }

        return {
            "success": True,
            "title": filename,
            "filename": filename,
            "thumbnail": "",
            "duration": 0,
            "duration_str": "Cloud File",
            "source_url": url,
            "direct_url": direct_url,
            "is_protected": False,
            "is_mega": True,
            "formats": [fmt],
            "detected_count": 1
        }
    except Exception as e:
        return {
            "success": False,
            "title": "MEGA Network Error",
            "source_url": url,
            "error_message": str(e)
        }


def download_mega_file(task, direct_url: str, key_bytes: bytes, initial_counter: int,
                       output_path: str, progress_callback: Optional[Callable[[int, int], None]] = None):
    """
    Downloads encrypted stream from MEGA, decrypting chunks with AES-CTR in real time.
    """
    part_path = output_path + ".part"
    session = requests.Session()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "*/*"
    }

    resp = session.get(direct_url, headers=headers, stream=True, timeout=30)
    if resp.status_code not in (200, 206):
        raise ValueError(f"MEGA storage server returned status {resp.status_code}")

    total_size = int(resp.headers.get("content-length", 0))

    # MEGA AES-CTR counter uses upper 64-bit IV and increments 64-bit lower counter every 16 bytes
    counter = pyaes.Counter(initial_value=initial_counter)
    aes_ctr = pyaes.AESModeOfOperationCTR(key_bytes, counter=counter)

    downloaded = 0
    with open(part_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if task.is_cancelled or task.is_paused:
                break
            if chunk:
                decrypted_chunk = aes_ctr.decrypt(chunk)
                f.write(decrypted_chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total_size)

    if task.is_cancelled:
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except Exception:
                pass
        return False

    if task.is_paused:
        return False

    if os.path.exists(part_path):
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
        os.rename(part_path, output_path)
        return True

    return False
