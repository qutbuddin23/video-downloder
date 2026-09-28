"""
Native MEGA.nz Cloud File and Folder Resolver and Decryption Engine.
Provides pure-Python metadata retrieval, folder browsing, and AES-128-CTR streaming download
for public MEGA file and folder links without requiring external C++ SDKs or binary dependencies.
"""

import os
import re
import json
import base64
import struct
import urllib.parse
from typing import Dict, Any, Optional, Tuple, List, Callable
import requests
import pyaes
from core.storage_manager import format_bytes


MEGA_FILE_PATTERN = re.compile(
    r'mega\.(?:nz|co\.nz)/(?:file/|#!)([a-zA-Z0-9_-]+)(?:[#!])([a-zA-Z0-9_-]+)',
    re.IGNORECASE
)

MEGA_FOLDER_PATTERN = re.compile(
    r'mega\.(?:nz|co\.nz)/(?:folder/|#F!)([a-zA-Z0-9_-]+)(?:[#!])([a-zA-Z0-9_-]+)',
    re.IGNORECASE
)


def is_mega_url(url: str) -> bool:
    """Checks whether URL matches a MEGA.nz public file or folder pattern."""
    if not url or not isinstance(url, str):
        return False
    return bool(MEGA_FILE_PATTERN.search(url) or MEGA_FOLDER_PATTERN.search(url))


def is_mega_folder_url(url: str) -> bool:
    """Checks whether URL specifically matches a MEGA folder pattern."""
    if not url or not isinstance(url, str):
        return False
    return bool(MEGA_FOLDER_PATTERN.search(url))


def parse_mega_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Extracts (file_id, file_key) from a public MEGA file link."""
    m = MEGA_FILE_PATTERN.search(url or "")
    if m:
        return m.group(1), m.group(2)
    return None, None


def parse_mega_folder_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Extracts (folder_id, folder_key) from a public MEGA folder link."""
    m = MEGA_FOLDER_PATTERN.search(url or "")
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
    - 128-bit initial CTR counter integer (upper 64 bits = IV, lower 64 bits = 0)
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
        # MEGA AES-CTR specification: IV in top 64 bits, offset/block counter in bottom 64 bits
        initial_counter = ((iv[0] << 32) | iv[1]) << 64
        return key_bytes, initial_counter
    except Exception as e:
        print(f"[MEGA] Key parse error: {e}")
        return None, None


def _decrypt_attr(at_b64: str, key_bytes: bytes) -> Dict[str, Any]:
    """Decrypts MEGA file attributes (JSON metadata containing original filename)."""
    try:
        raw_at = _base64_url_decode(at_b64)
        cbc = pyaes.AESModeOfOperationCBC(key_bytes, iv=b'\x00' * 16)
        decrypted = b"".join(
            cbc.decrypt(raw_at[i:i+16])
            for i in range(0, len(raw_at), 16)
            if len(raw_at[i:i+16]) == 16
        )
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
    Resolves public MEGA single file link into file metadata and direct streaming URL.
    Returns standard metadata dictionary compatible with Universal Downloader.
    """
    file_id, file_key = parse_mega_url(url)
    if not file_id or not file_key:
        return {
            "success": False,
            "title": "Invalid MEGA URL",
            "source_url": url,
            "error_message": "Invalid or unparseable MEGA file link format."
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
            "filename": filename,
            "resolution": "Cloud File",
            "height": 0,
            "ext": ext,
            "codec": "AES-CTR Decrypted",
            "filesize": size,
            "filesize_str": format_bytes(size),
            "has_audio": ext in ["mp4", "mkv", "webm", "mp3", "m4a", "wav", "flac"],
            "has_video": ext in ["mp4", "mkv", "webm", "mov", "avi", "flv"],
            "direct_url": direct_url,
            "download_selector": "mega",
            "is_mega": True,
            "mega_key_bytes": key_bytes,
            "mega_initial_counter": initial_counter
        }

        return {
            "success": True,
            "is_folder": False,
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


def get_mega_folder_info(url: str) -> Dict[str, Any]:
    """
    Resolves public MEGA folder link into folder metadata and list of all files inside it.
    Decrypts filenames, extensions, and file sizes for every node in the folder.
    """
    folder_id, folder_key = parse_mega_folder_url(url)
    if not folder_id or not folder_key:
        return {
            "success": False,
            "title": "Invalid MEGA Folder URL",
            "source_url": url,
            "error_message": "Invalid or unparseable MEGA folder link format."
        }

    try:
        master_key = _base64_url_decode(folder_key)
        if len(master_key) != 16:
            return {
                "success": False,
                "title": "MEGA Folder Key Error",
                "source_url": url,
                "error_message": f"Expected 16-byte folder key, got {len(master_key)} bytes."
            }
    except Exception as e:
        return {
            "success": False,
            "title": "MEGA Folder Key Error",
            "source_url": url,
            "error_message": f"Could not decode folder key: {e}"
        }

    api_url = f"https://g.api.mega.co.nz/cs?id=123456789&n={folder_id}"
    payload = [{"a": "f", "c": 1, "r": 1, "ca": 1}]

    try:
        resp = requests.post(api_url, json=payload, timeout=25)
        if not resp.ok:
            return {
                "success": False,
                "title": "MEGA API Error",
                "source_url": url,
                "error_message": f"MEGA API returned HTTP {resp.status_code}"
            }

        data = resp.json()
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return {
                "success": False,
                "title": "MEGA Response Error",
                "source_url": url,
                "error_message": "Invalid response from MEGA folder API."
            }

        res = data[0]
        nodes = res.get("f", [])
        if not nodes:
            return {
                "success": False,
                "title": "Empty MEGA Folder",
                "source_url": url,
                "error_message": "No files found in this MEGA folder."
            }

        folder_name = "MEGA Shared Folder"
        formats = []
        ecb = pyaes.AESModeOfOperationECB(master_key)

        for node in nodes:
            h = node.get("h", "")
            t = node.get("t", 0)  # 0 = file, 1 = folder
            k = node.get("k", "")
            a = node.get("a", "")
            s = node.get("s", 0) or 0

            if not k or ":" not in k:
                continue

            try:
                k_str = k.split(":")[1]
                enc_k = _base64_url_decode(k_str)
                dec_k = b"".join(
                    ecb.decrypt(enc_k[i:i+16])
                    for i in range(0, len(enc_k), 16)
                    if len(enc_k[i:i+16]) == 16
                )

                if t == 1:
                    # Folder node
                    if len(dec_k) >= 16:
                        f_attr = _decrypt_attr(a, dec_k[:16])
                        if f_attr.get("n") and folder_name == "MEGA Shared Folder":
                            folder_name = f_attr["n"]
                elif t == 0:
                    # File node
                    if len(dec_k) >= 32:
                        a32 = struct.unpack(f">{len(dec_k)//4}I", dec_k[:32])
                        file_aes_key = struct.pack(
                            ">4I",
                            a32[0] ^ a32[4],
                            a32[1] ^ a32[5],
                            a32[2] ^ a32[6],
                            a32[3] ^ a32[7]
                        )
                        initial_counter = ((a32[4] << 32) | a32[5]) << 64
                        file_attr = _decrypt_attr(a, file_aes_key)
                        fname = file_attr.get("n", f"file_{h}")
                        ext = os.path.splitext(fname)[1].lstrip(".").lower() or "bin"

                        formats.append({
                            "format_id": f"mega_node_{h}",
                            "quality_label": fname,
                            "filename": fname,
                            "resolution": ext.upper(),
                            "height": 0,
                            "ext": ext,
                            "codec": "AES-CTR Decrypted",
                            "filesize": s,
                            "filesize_str": format_bytes(s),
                            "has_audio": ext in ["mp4", "mkv", "webm", "mp3", "m4a", "wav", "flac"],
                            "has_video": ext in ["mp4", "mkv", "webm", "mov", "avi", "flv"],
                            "direct_url": "",
                            "download_selector": f"mega_node:{folder_id}:{folder_key}:{h}",
                            "is_mega": True,
                            "node_handle": h,
                            "folder_id": folder_id,
                            "folder_key": folder_key
                        })
            except Exception as node_err:
                print(f"[MEGA] Node {h} parse warning: {node_err}")
                continue

        if not formats:
            return {
                "success": False,
                "title": folder_name,
                "source_url": url,
                "error_message": "Could not decrypt any files in this MEGA folder."
            }

        return {
            "success": True,
            "is_folder": True,
            "title": folder_name,
            "filename": folder_name,
            "thumbnail": "",
            "duration": 0,
            "duration_str": f"{len(formats)} Files",
            "source_url": url,
            "direct_url": "",
            "is_protected": False,
            "is_mega": True,
            "formats": formats,
            "detected_count": len(formats)
        }
    except Exception as e:
        return {
            "success": False,
            "title": "MEGA Folder Network Error",
            "source_url": url,
            "error_message": str(e)
        }


def get_mega_info(url: str) -> Dict[str, Any]:
    """Unified entry point for both MEGA single file and folder URLs."""
    if is_mega_folder_url(url):
        return get_mega_folder_info(url)
    return get_mega_file_info(url)


def get_mega_node_download_info(folder_id: str, folder_key: str, node_handle: str) -> Tuple[Optional[str], Optional[bytes], Optional[int], Optional[str], int]:
    """
    Fetches direct streaming URL and derives AES decryption key for a specific file node in a MEGA folder.
    Returns: (direct_url, file_aes_key, initial_counter, filename, file_size)
    """
    master_key = _base64_url_decode(folder_key)
    api_url = f"https://g.api.mega.co.nz/cs?id=123456789&n={folder_id}"

    # 1. Fetch node metadata and direct streaming URL in one request
    payload = [
        {"a": "f", "c": 1, "r": 1, "ca": 1},
        {"a": "g", "g": 1, "n": node_handle}
    ]
    resp = requests.post(api_url, json=payload, timeout=25)
    if not resp.ok:
        raise ValueError(f"MEGA API returned HTTP {resp.status_code}")

    res_list = resp.json()
    if not isinstance(res_list, list) or len(res_list) < 2:
        raise ValueError("Invalid response from MEGA API for folder node.")

    nodes = res_list[0].get("f", [])
    dl_info = res_list[1]

    direct_url = dl_info.get("g")
    if not direct_url:
        raise ValueError("Could not get direct download URL from MEGA.")

    size = dl_info.get("s", 0)

    # Find the target node
    target_node = next((n for n in nodes if n.get("h") == node_handle), None)
    if not target_node:
        raise ValueError(f"Node {node_handle} not found in folder.")

    k_str = target_node["k"].split(":")[1]
    enc_k = _base64_url_decode(k_str)

    ecb = pyaes.AESModeOfOperationECB(master_key)
    dec_k = b"".join(
        ecb.decrypt(enc_k[i:i+16])
        for i in range(0, len(enc_k), 16)
        if len(enc_k[i:i+16]) == 16
    )

    if len(dec_k) < 32:
        raise ValueError("Decrypted node key is too short.")

    a32 = struct.unpack(f">{len(dec_k)//4}I", dec_k[:32])
    file_aes_key = struct.pack(
        ">4I",
        a32[0] ^ a32[4],
        a32[1] ^ a32[5],
        a32[2] ^ a32[6],
        a32[3] ^ a32[7]
    )
    initial_counter = ((a32[4] << 32) | a32[5]) << 64
    attr = _decrypt_attr(target_node.get("a", ""), file_aes_key)
    filename = attr.get("n", f"mega_file_{node_handle}")

    return direct_url, file_aes_key, initial_counter, filename, size


def download_mega_file(task, direct_url: str, key_bytes: bytes, initial_counter: int,
                       output_path: str, progress_callback: Optional[Callable[[int, int], None]] = None) -> bool:
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
