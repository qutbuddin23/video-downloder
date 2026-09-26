"""
TeraBox Cloud Link Resolver and Stream Extraction Engine.
Supports terabox.com, terabox.app, 1024tera.com, mirrobox.com, nephobox.com,
freeterabox.com, 4funbox.com, and tibibox.com without requiring official client apps.
"""

import os
import re
import json
import urllib.parse
from typing import Dict, Any, Optional
import requests
from core.storage_manager import format_bytes


TERABOX_DOMAINS = (
    "terabox.com", "terabox.app", "1024tera.com", "1024terabox.com", "mirrobox.com",
    "nephobox.com", "freeterabox.com", "4funbox.com", "teraboxlink.com",
    "tibibox.com", "teraboxshare.com", "terasharelink.com", "terafileshare.com",
    "momerybox.com"
)


def is_terabox_url(url: str) -> bool:
    """Checks whether URL belongs to any TeraBox / Dubox domain."""
    if not url or not isinstance(url, str):
        return False
    lower = url.lower()
    return any(domain in lower for domain in TERABOX_DOMAINS)


def extract_terabox_surl(url: str) -> Optional[str]:
    """Extracts the shared shorturl key from a TeraBox share link."""
    m = re.search(r'(?:/s/|surl=)1?([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    return None


def _find_between(s: str, start: str, end: str) -> str:
    """Safely extracts a substring between two delimiters."""
    try:
        start_idx = s.find(start)
        if start_idx == -1:
            return ""
        start_idx += len(start)
        end_idx = s.find(end, start_idx)
        if end_idx == -1:
            return ""
        return s[start_idx:end_idx]
    except Exception:
        return ""


def get_terabox_file_info(url: str, cookie: str = "") -> Dict[str, Any]:
    """
    Resolves TeraBox share URL into direct download link (dlink), filename, and size.
    Uses multi-tiered strategy:
    1. Direct TeraBox web API session resolution.
    2. Public fast resolver gateway fallback.
    """
    surl = extract_terabox_surl(url)
    if not surl:
        return {
            "success": False,
            "title": "Invalid TeraBox Link",
            "source_url": url,
            "error_message": "Could not extract TeraBox share identifier (surl)."
        }

    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.terabox.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    if cookie:
        headers["Cookie"] = cookie if "ndus=" in cookie else f"ndus={cookie}; lang=en;"

    # Strategy 1: Direct Web Token Resolution
    try:
        init_res = session.get(url, headers=headers, timeout=15, allow_redirects=True)
        if init_res.ok:
            # Direct HTML state inspection
            if "server_filename" in page_text and "dlink" in page_text:
                try:
                    state_match = re.search(r'window\.server_data\s*=\s*(\{.*?\});', page_text) or re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', page_text)
                    if state_match:
                        raw_json = json.loads(state_match.group(1))
                        flist = raw_json.get("list") or raw_json.get("file_list") or []
                        if flist and isinstance(flist, list):
                            item = flist[0]
                            dlink = item.get("dlink")
                            filename = item.get("server_filename", "terabox_download")
                            size = int(item.get("size", 0))
                            ext = os.path.splitext(filename)[1].lstrip('.').lower() or "bin"
                            if dlink:
                                fmt = {
                                    "format_id": "terabox_direct",
                                    "quality_label": f"TeraBox ({ext.upper()})",
                                    "resolution": "Cloud File",
                                    "height": 0,
                                    "ext": ext,
                                    "codec": "Direct Cloud Stream",
                                    "filesize": size,
                                    "filesize_str": format_bytes(size),
                                    "has_audio": True,
                                    "has_video": True,
                                    "direct_url": dlink,
                                    "download_selector": "direct",
                                    "referer": "https://www.terabox.com/",
                                    "is_terabox": True
                                }
                                return {
                                    "success": True,
                                    "title": filename,
                                    "filename": filename,
                                    "thumbnail": item.get("thumbs", {}).get("url3", ""),
                                    "duration": 0,
                                    "duration_str": "Cloud File",
                                    "source_url": url,
                                    "direct_url": dlink,
                                    "is_protected": False,
                                    "is_terabox": True,
                                    "formats": [fmt],
                                    "detected_count": 1
                                }
                except Exception:
                    pass

            js_token = _find_between(page_text, 'fn%28%22', '%22%29')
            logid = _find_between(page_text, 'dp-logid=', '&')
            bdstoken = _find_between(page_text, 'bdstoken":"', '"')

            if js_token and logid:
                list_params = {
                    "app_id": "250528",
                    "web": "1",
                    "channel": "dubox",
                    "clienttype": "0",
                    "jsToken": js_token,
                    "dp-logid": logid,
                    "page": "1",
                    "num": "20",
                    "by": "name",
                    "order": "asc",
                    "site_referer": init_res.url,
                    "shorturl": surl,
                    "root": "1,"
                }
                if bdstoken:
                    list_params["bdstoken"] = bdstoken

                api_res = session.get("https://www.terabox.app/share/list", headers=headers, params=list_params, timeout=15)
                if api_res.ok:
                    data = api_res.json()
                    file_list = data.get("list", [])
                    if file_list and isinstance(file_list, list):
                        item = file_list[0]
                        filename = item.get("server_filename", "terabox_download")
                        dlink = item.get("dlink", "")
                        size = int(item.get("size", 0))
                        thumb = item.get("thumbs", {}).get("url3", "")
                        ext = os.path.splitext(filename)[1].lstrip('.').lower() or "bin"

                        if dlink:
                            fmt = {
                                "format_id": "terabox_direct",
                                "quality_label": f"TeraBox ({ext.upper()})",
                                "resolution": "Cloud File",
                                "height": 0,
                                "ext": ext,
                                "codec": "Direct Cloud Stream",
                                "filesize": size,
                                "filesize_str": format_bytes(size),
                                "has_audio": ext in ["mp4", "mkv", "webm", "mp3", "m4a", "wav"],
                                "has_video": ext in ["mp4", "mkv", "webm", "mov", "avi"],
                                "direct_url": dlink,
                                "download_selector": "direct",
                                "referer": "https://www.terabox.com/",
                                "is_terabox": True
                            }
                            return {
                                "success": True,
                                "title": filename,
                                "filename": filename,
                                "thumbnail": thumb,
                                "duration": 0,
                                "duration_str": "Cloud File",
                                "source_url": url,
                                "direct_url": dlink,
                                "is_protected": False,
                                "is_terabox": True,
                                "formats": [fmt],
                                "detected_count": 1
                            }
    except Exception as e:
        print(f"[TeraBox] Web token extraction notice: {e}")

    # Strategy 2: Fast Public Resolver Gateways
    public_gateways = [
        f"https://terabox-api.online/api?url={urllib.parse.quote(url)}",
        f"https://teraboxdownloader.online/api/?url={urllib.parse.quote(url)}"
    ]
    for gw in public_gateways:
        try:
            gw_res = session.get(gw, timeout=10)
            if gw_res.ok:
                gw_data = gw_res.json()
                dlink = gw_data.get("download") or gw_data.get("dlink") or gw_data.get("direct_link")
                filename = gw_data.get("filename") or gw_data.get("name") or "terabox_download"
                size = gw_data.get("size_bytes") or gw_data.get("size") or 0
                if isinstance(size, str):
                    try:
                        size = int(size)
                    except Exception:
                        size = 0
                ext = os.path.splitext(filename)[1].lstrip('.').lower() or "bin"
                if dlink:
                    fmt = {
                        "format_id": "terabox_gw",
                        "quality_label": f"TeraBox ({ext.upper()})",
                        "resolution": "Cloud File",
                        "height": 0,
                        "ext": ext,
                        "codec": "Gateway Stream",
                        "filesize": size,
                        "filesize_str": format_bytes(size) if size else "Cloud Stream",
                        "has_audio": True,
                        "has_video": True,
                        "direct_url": dlink,
                        "download_selector": "direct",
                        "referer": "https://www.terabox.com/",
                        "is_terabox": True
                    }
                    return {
                        "success": True,
                        "title": filename,
                        "filename": filename,
                        "thumbnail": gw_data.get("thumbnail", ""),
                        "duration": 0,
                        "duration_str": "Cloud File",
                        "source_url": url,
                        "direct_url": dlink,
                        "is_protected": False,
                        "is_terabox": True,
                        "formats": [fmt],
                        "detected_count": 1
                    }
        except Exception:
            continue

    return {
        "success": False,
        "title": "TeraBox Extraction Failed",
        "source_url": url,
        "error_message": "Could not retrieve direct link from TeraBox. If this is a private file, you can enter your TeraBox ndus cookie in Settings."
    }
