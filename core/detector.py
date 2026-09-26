"""
Universal Media Detection Engine for Universal Video Downloader.
Extracts video metadata and streams using yt-dlp and deep webpage sniffing
(HTML5, HLS .m3u8 playlists, MPEG-DASH .mpd manifests, and direct video links).
"""

import os
import re
import urllib.parse
import warnings
from typing import Dict, Any, List, Optional
import requests
from core.storage_manager import format_bytes
from core.paths import SafeYtdlLogger

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*Support for Python version.*deprecated.*")


from core.mega import is_mega_url, get_mega_file_info
from core.terabox import is_terabox_url, get_terabox_file_info

DIRECT_DOWNLOAD_EXTS = (
    # Video & Audio
    ".mp4", ".webm", ".mkv", ".mov", ".m3u8", ".mpd", ".m4v", ".ts", ".flv", ".avi", ".3gp",
    ".mp3", ".m4a", ".aac", ".opus", ".flac", ".wav", ".ogg",
    # Archives & Compressed Files
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".tgz",
    # Applications, Installers & Documents
    ".apk", ".pdf", ".epub", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".exe", ".bin", ".dmg"
)


def is_direct_download_url(url: str) -> bool:
    """Checks whether URL directly references a raw media file, archive, installer, or document."""
    clean = url.split("?")[0].lower()
    return any(clean.endswith(ext) for ext in DIRECT_DOWNLOAD_EXTS)


def is_direct_media_url(url: str) -> bool:
    """Backwards-compatible wrapper for direct media and file URLs."""
    return is_direct_download_url(url)




def format_duration(seconds: Optional[int]) -> str:
    """Format seconds into MM:SS or HH:MM:SS string."""
    if not seconds or seconds <= 0:
        return "Unknown"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def is_valid_media_url(u: str) -> bool:
    """Strictly validates whether a URL points to a legitimate media stream/file."""
    if not u or not isinstance(u, str):
        return False
    u_strip = u.strip()
    if not (u_strip.startswith("http://") or u_strip.startswith("https://")):
        return False
    clean_u = u_strip.split("?")[0].lower()
    disallowed = (
        ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico",
        ".css", ".js", ".json", ".xml", ".html", ".htm", ".txt",
        ".woff", ".woff2", ".ttf", ".eot"
    )
    if any(clean_u.endswith(ext) for ext in disallowed):
        return False
    # Reject common non-video asset keywords in query or path
    low_u = u_strip.lower()
    if any(tok in low_u for tok in [".svg?", ".png?", ".jpg?", "format=svg", "format=png", "format=jpg", "format=webp", "data:image/", "mime=image/"]):
        return False
    return True


def get_android_cookies(url: str) -> Dict[str, str]:
    """Extracts live session cookies from Android WebView CookieManager if on Android."""
    cookies = {}
    if not url:
        return cookies
    try:
        from jnius import autoclass
        CookieManager = autoclass("android.webkit.CookieManager")
        cm = CookieManager.getInstance()
        cookie_str = cm.getCookie(url)
        if cookie_str:
            for item in cookie_str.split(";"):
                if "=" in item:
                    k, v = item.strip().split("=", 1)
                    cookies[k.strip()] = v.strip()
    except Exception:
        pass
    return cookies


class MediaDetector:
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    _cookie_jar: Dict[str, dict] = {}

    @classmethod
    def get_cookies_for_url(cls, url: str) -> Dict[str, str]:
        """Collects combined session cookies from memory cache and Android CookieManager."""
        all_cookies = {}
        if not url:
            return all_cookies
        try:
            domain = urllib.parse.urlsplit(url).netloc.lower()
            for d_key, c_dict in cls._cookie_jar.items():
                d_clean = d_key.lower().lstrip(".")
                if d_clean in domain or domain in d_clean:
                    all_cookies.update(c_dict)
        except Exception:
            pass

        android_c = get_android_cookies(url)
        if android_c:
            all_cookies.update(android_c)

        return all_cookies

    def __init__(self):
        self.ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "skip_download": True,
            "nocheckcertificate": True,
            "geo_bypass": True,
            "logtostderr": False,
            "logger": SafeYtdlLogger(),
            "socket_timeout": 15,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "android_vr", "web"]
                }
            }
        }

    def analyze_url(self, url: str) -> Dict[str, Any]:
        """
        Analyzes a URL using a multi-engine approach:
        1. Native MEGA.nz cloud resolver.
        2. TeraBox / 1024tera multi-tier link extractor.
        3. Fast path for direct file & media streams (.mp4, .zip, .apk, .pdf, etc.).
        4. yt-dlp extractor for major video streaming platforms.
        5. Direct HTTP stream probe for arbitrary direct download endpoints.
        6. Fallback deep HTML5 & network manifest sniffer for arbitrary websites.
        """
        url = url.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url

        # 1. Native MEGA.nz Cloud Link Resolution
        if is_mega_url(url):
            return get_mega_file_info(url)

        # 2. TeraBox Cloud Link Resolution
        if is_terabox_url(url):
            return get_terabox_file_info(url)

        # 3. Fast path: Direct file or media URL (.mp4, .zip, .apk, .pdf, etc.)
        if is_direct_download_url(url):
            clean = url.split("?")[0].lower()
            ext = "mp4"
            for candidate in DIRECT_DOWNLOAD_EXTS:
                if clean.endswith(candidate):
                    ext = candidate.lstrip('.')
                    break
            path_part = urllib.parse.urlsplit(url).path
            fname = os.path.basename(path_part)
            raw_title = os.path.splitext(fname)[0] or "Direct Download"
            title = re.sub(r'[_.-]+', ' ', raw_title).strip() or "Direct Download"
            fmt = {
                "format_id": "direct_stream",
                "quality_label": f"Direct ({ext.upper()})",
                "resolution": "Direct Stream",
                "height": 720 if ext in ["mp4", "mkv", "webm", "mov"] else 0,
                "ext": "mp4" if ext in ["m3u8", "mpd"] else ext,
                "codec": "h264/aac" if ext in ["mp4", "mkv", "webm"] else "binary",
                "filesize": 0,
                "filesize_str": "Direct Stream",
                "has_audio": ext in ["mp4", "mkv", "webm", "mp3", "m4a", "wav"],
                "has_video": ext in ["mp4", "mkv", "webm", "mov"],
                "direct_url": url,
                "download_selector": "direct",
                "referer": url
            }
            return {
                "success": True,
                "is_direct": True,
                "title": title,
                "thumbnail": "",
                "duration": 0,
                "duration_str": "Direct File",
                "source_url": url,
                "direct_url": url,
                "is_protected": False,
                "formats": [fmt],
                "detected_count": 1
            }

        # 4. yt-dlp extraction for known platforms
        try:
            import yt_dlp
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    result = self._process_ytdlp_info(info, url)
                    if result.get("success") and result.get("formats") and any(f.get("has_video") for f in result["formats"]):
                        return result
        except Exception as e:
            error_str = str(e).lower()
            if "drm" in error_str or "encrypted" in error_str or "protected" in error_str:
                return {
                    "success": False,
                    "title": "Protected Media",
                    "source_url": url,
                    "is_protected": True,
                    "protection_reason": "This media is protected by DRM/access encryption and cannot be downloaded legitimately.",
                    "formats": []
                }

        # 5. Direct HTTP probe for arbitrary direct download endpoints
        try:
            probe = requests.get(url, headers=self.DEFAULT_HEADERS, stream=True, timeout=12, allow_redirects=True)
            c_type = probe.headers.get("content-type", "").lower()
            c_disp = probe.headers.get("content-disposition", "")
            # If server responds with binary / media / download content rather than an HTML webpage
            if probe.status_code in (200, 206) and not ("text/html" in c_type or "text/plain" in c_type):
                fname = ""
                if "filename=" in c_disp:
                    m = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', c_disp)
                    if m:
                        fname = urllib.parse.unquote(m.group(1).strip())
                if not fname:
                    path_part = urllib.parse.urlsplit(probe.url).path
                    fname = os.path.basename(path_part)
                if not fname:
                    fname = "direct_download"
                ext = os.path.splitext(fname)[1].lstrip('.').lower() or "bin"
                content_len = int(probe.headers.get("content-length", 0))
                fmt = {
                    "format_id": "direct_stream",
                    "quality_label": f"Direct ({ext.upper()})",
                    "resolution": "Direct Stream",
                    "height": 0,
                    "ext": ext,
                    "codec": c_type or "binary",
                    "filesize": content_len,
                    "filesize_str": format_bytes(content_len) if content_len else "Direct Stream",
                    "has_audio": True,
                    "has_video": True,
                    "direct_url": probe.url,
                    "download_selector": "direct",
                    "referer": url
                }
                return {
                    "success": True,
                    "is_direct": True,
                    "title": fname,
                    "thumbnail": "",
                    "duration": 0,
                    "duration_str": "Direct File",
                    "source_url": url,
                    "direct_url": probe.url,
                    "is_protected": False,
                    "formats": [fmt],
                    "detected_count": 1
                }
        except Exception as probe_err:
            print(f"[Detector] Direct HTTP probe notice: {probe_err}")

        # 6. Fallback: Deep DOM & Network sniffer
        return self._sniff_webpage(url)

    def _process_ytdlp_info(self, info: Dict[str, Any], original_url: str) -> Dict[str, Any]:
        """Formats yt-dlp metadata into a clean, unified structure."""
        title = info.get("title") or "Detected Video"
        thumbnail = info.get("thumbnail") or ""
        duration = info.get("duration") or 0
        formats_raw = info.get("formats") or []

        # Check for DRM indicator
        is_protected = False
        protection_reason = ""
        for f in formats_raw:
            if "drm" in str(f.get("format_note", "")).lower() or f.get("has_drm"):
                is_protected = True
                protection_reason = "Stream contains DRM protection."
                break

        # Process available quality options
        quality_map = {}
        audio_options = []

        for f in formats_raw:
            fmt_id = str(f.get("format_id") or "").lower()
            ext = (f.get("ext") or "mp4").lower()
            url = f.get("url") or ""

            # Strictly reject storyboards, images, or non-media formats
            if fmt_id.startswith("sb") or ext in ["mhtml", "jpg", "jpeg", "png", "webp", "gif", "svg", "ico"]:
                continue
            if url and not is_valid_media_url(url) and not f.get("manifest_url"):
                continue

            vcodec = f.get("vcodec") or "none"
            acodec = f.get("acodec") or "none"
            video_ext = f.get("video_ext") or "none"
            audio_ext = f.get("audio_ext") or "none"
            height = f.get("height")
            filesize = f.get("filesize") or f.get("filesize_approx") or 0

            # Comprehensive check for video presence
            is_video = (
                (vcodec != "none" and vcodec is not None)
                or (video_ext != "none" and video_ext is not None)
                or (height is not None and int(height) > 0)
                or (ext in ["mp4", "webm", "mkv", "mov", "flv", "avi", "3gp", "ts", "m3u8", "mpd"] and acodec != "only")
            )
            # If strictly audio-only
            if vcodec == "none" and acodec != "none" and not height and ext in ["mp3", "m4a", "aac", "opus", "wav", "flac"]:
                is_video = False

            # Determine whether stream has audio
            is_audio = (
                (acodec != "none" and acodec is not None)
                or (audio_ext != "none" and audio_ext is not None)
                or ext in ["mp3", "m4a", "aac", "opus", "wav", "ogg"]
                or (is_video and ext in ["mp4", "webm", "mkv", "mov", "3gp"])  # Pre-muxed files
            )

            if is_video:
                resolution_label = f"{height}p" if height else (f.get("resolution") or "Standard")
                # Group by resolution to present the best stream per quality
                if resolution_label not in quality_map or filesize > quality_map[resolution_label]["filesize"]:
                    quality_map[resolution_label] = {
                        "format_id": fmt_id,
                        "quality_label": resolution_label,
                        "resolution": resolution_label,
                        "height": int(height) if height else 0,
                        "ext": ext if ext in ["mp4", "webm", "mkv", "mov"] else "mp4",
                        "codec": f"{vcodec}/{acodec}",
                        "filesize": filesize,
                        "filesize_str": format_bytes(filesize) if filesize > 0 else "Adaptive / Unknown",
                        "has_audio": is_audio,
                        "has_video": True,
                        "direct_url": url,
                        "download_selector": f"best[height<={height}][vcodec!=none][acodec!=none][format_id!^=sb]/b/18/best[vcodec!=none][acodec!=none][format_id!^=sb]/best[format_id!^=sb]" if height else "b/18/best[vcodec!=none][acodec!=none][format_id!^=sb]/best[format_id!^=sb]"
                    }
            elif is_audio and not is_video:
                # Audio only stream
                abr = f.get("abr") or 128
                audio_options.append({
                    "format_id": fmt_id,
                    "quality_label": f"Audio ({abr} kbps)",
                    "resolution": "Audio Only",
                    "height": 0,
                    "ext": ext if ext in ["mp3", "m4a", "aac", "opus"] else "m4a",
                    "codec": acodec,
                    "filesize": filesize,
                    "filesize_str": format_bytes(filesize) if filesize > 0 else "Unknown",
                    "has_audio": True,
                    "has_video": False,
                    "direct_url": url,
                    "download_selector": "bestaudio[format_id!^=sb]/best"
                })

        # Sort video options by height descending (e.g. 1080p, 720p, 480p)
        sorted_video = sorted(quality_map.values(), key=lambda x: x["height"], reverse=True)

        # Append top audio options
        best_audio = sorted(audio_options, key=lambda x: x["filesize"], reverse=True)[:2]
        all_formats = sorted_video + best_audio

        # Select the best direct URL that has both video and audio for in-app preview
        best_direct = next((f["direct_url"] for f in all_formats if f.get("has_audio") and f.get("has_video") and f.get("direct_url")), "")
        if not best_direct and sorted_video:
            best_direct = sorted_video[0].get("direct_url", "")

        return {
            "success": bool(all_formats),
            "title": title,
            "thumbnail": thumbnail,
            "duration": duration,
            "duration_str": format_duration(duration),
            "source_url": original_url,
            "direct_url": best_direct,
            "is_protected": is_protected,
            "protection_reason": protection_reason,
            "formats": all_formats,
            "detected_count": len(all_formats)
        }

    def _sniff_webpage(self, url: str) -> Dict[str, Any]:
        """
        Deep webpage scanner: Fetches HTML and inspects:
        - HTML5 <video> tags and <source> elements (excluding images/SVGs)
        - OpenGraph & Twitter video metadata
        - HLS .m3u8 playlist URLs
        - MPEG-DASH .mpd manifest URLs
        - Direct .mp4 / .webm video links in page scripts & JS configs
        """
        try:
            cookies = MediaDetector.get_cookies_for_url(url)
            resp = requests.get(url, headers=self.DEFAULT_HEADERS, cookies=cookies or None, timeout=12)
            html = resp.text
            domain = urllib.parse.urlsplit(url).netloc
            if getattr(resp, "cookies", None):
                try:
                    MediaDetector._cookie_jar[domain] = resp.cookies.get_dict()
                except Exception:
                    pass
        except Exception as e:
            return {
                "success": False,
                "title": "Unreachable URL",
                "source_url": url,
                "is_protected": False,
                "error_message": f"Could not connect to URL: {str(e)}",
                "formats": []
            }

        clean_html = html.replace(r'\/', '/')

        # Determine Page Title
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else "Detected Web Video"

        # Determine Thumbnail
        thumbnail = ""
        og_img = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if not og_img:
            og_img = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\']', html, re.IGNORECASE)
        if og_img and og_img.group(1):
            cand_thumb = urllib.parse.urljoin(url, og_img.group(1))
            if not cand_thumb.lower().endswith(".svg"):
                thumbnail = cand_thumb

        detected_urls = set()

        # 1. HTML5 <video> tags
        for v in re.finditer(r'<video[^>]+src=["\']([^"\']+)["\']', clean_html, re.IGNORECASE):
            cand = urllib.parse.urljoin(url, v.group(1))
            if is_valid_media_url(cand):
                detected_urls.add(cand)

        # 2. <source> tags strictly for video/audio (ignore picture/srcset/svg)
        for s in re.finditer(r'<source\s+[^>]*src=["\']([^"\']+)["\'][^>]*>', clean_html, re.IGNORECASE):
            full_tag = s.group(0).lower()
            if "image/" in full_tag or "srcset" in full_tag:
                continue
            cand = urllib.parse.urljoin(url, s.group(1))
            if is_valid_media_url(cand):
                detected_urls.add(cand)

        # 3. Meta tags (OpenGraph / Twitter card video)
        for meta_name in ["og:video", "og:video:url", "og:video:secure_url", "twitter:player:stream"]:
            m = re.search(rf'<meta[^>]+(?:property|name)=["\']{re.escape(meta_name)}["\'][^>]+content=["\']([^"\']+)["\']', clean_html, re.IGNORECASE)
            if not m:
                m = re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(meta_name)}["\']', clean_html, re.IGNORECASE)
            if m and m.group(1):
                cand = urllib.parse.urljoin(url, m.group(1))
                if is_valid_media_url(cand):
                    detected_urls.add(cand)

        # 4. JS configurations and player script links (VideoJS, JWPlayer, Spankbang, FluidPlayer)
        js_patterns = [
            r'["\']?(?:file|src|url|video_url|stream_url|source|streamUrl|videoUrl|hls|m3u8|mp4)["\']?\s*[:=]\s*["\']([^"\'\s]+\.(?:m3u8|mpd|mp4|webm|mkv)[^"\'\s]*)["\']',
            r'["\']?(?:1080p|720p|480p|360p|240p|high|med|low)["\']?\s*[:=]\s*["\']([^"\'\s]+\.(?:m3u8|mpd|mp4|webm|mkv)[^"\'\s]*)["\']',
            r'https?://[^\s"\'<>]+\.m3u8(?:\?[^\s"\'<>]*)?',
            r'https?://[^\s"\'<>]+\.mpd(?:\?[^\s"\'<>]*)?',
            r'https?://[^\s"\'<>]+\.(?:mp4|webm|mkv|mov)(?:\?[^\s"\'<>]*)?'
        ]
        for pat in js_patterns:
            for match in re.findall(pat, clean_html, re.IGNORECASE):
                if isinstance(match, tuple):
                    match = match[0]
                cand = urllib.parse.urljoin(url, match)
                if is_valid_media_url(cand):
                    detected_urls.add(cand)

        if not detected_urls:
            return {
                "success": False,
                "title": title,
                "source_url": url,
                "is_protected": False,
                "error_message": "No downloadable video stream was detected on this page.",
                "formats": []
            }

        # Stream prioritization: prioritize full video streams and HLS over trailers/previews
        def _stream_priority(u: str) -> int:
            u_low = u.lower()
            score = 100
            if any(p in u_low for p in ["trailer", "preview", "sample", "intro", "thumb", "teaser", "snippet"]):
                score -= 60
            if ".m3u8" in u_low:
                score += 35
            if "1080" in u_low:
                score += 25
            elif "720" in u_low:
                score += 20
            elif "480" in u_low:
                score += 15
            elif ".mp4" in u_low:
                score += 10
            return score

        sorted_urls = sorted(detected_urls, key=_stream_priority, reverse=True)

        # Build formats from sorted detected URLs
        formats = []
        for i, media_url in enumerate(sorted_urls):
            clean_url = media_url.split("?")[0].lower()
            ext = "m3u8" if clean_url.endswith(".m3u8") else ("mpd" if clean_url.endswith(".mpd") else "mp4")
            label = f"Stream {i+1} ({ext.upper()})"
            formats.append({
                "format_id": f"sniffed_{i}",
                "quality_label": label,
                "resolution": "Native Stream",
                "height": 720,
                "ext": "mp4" if ext in ["m3u8", "mpd"] else ext,
                "codec": "h264/aac",
                "filesize": 0,
                "filesize_str": "Stream",
                "has_audio": True,
                "has_video": True,
                "direct_url": media_url,
                "download_selector": "best[format_id!^=sb]",
                "referer": url
            })

        best_direct = formats[0]["direct_url"] if formats else ""

        return {
            "success": True,
            "title": title,
            "thumbnail": thumbnail,
            "duration": 0,
            "duration_str": "Stream",
            "source_url": url,
            "direct_url": best_direct,
            "is_protected": False,
            "formats": formats,
            "detected_count": len(formats)
        }
