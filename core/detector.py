"""
Universal Media Detection Engine for Universal Video Downloader.
Extracts video metadata and streams using yt-dlp and deep webpage sniffing
(HTML5, HLS .m3u8 playlists, MPEG-DASH .mpd manifests, and direct video links).
"""

import re
import urllib.parse
import warnings
from typing import Dict, Any, List, Optional
import requests
from core.storage_manager import format_bytes

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*Support for Python version.*deprecated.*")


def format_duration(seconds: Optional[int]) -> str:
    """Format seconds into MM:SS or HH:MM:SS string."""
    if not seconds or seconds <= 0:
        return "Unknown"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class MediaDetector:
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    def __init__(self):
        self.ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "skip_download": True,
            "nocheckcertificate": True,
            "geo_bypass": True,
            "socket_timeout": 15,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "mweb", "web"]
                }
            }
        }

    def analyze_url(self, url: str) -> Dict[str, Any]:
        """
        Analyzes a URL using a dual-engine approach:
        1. yt-dlp extractor for known platforms and complex streaming setups.
        2. Fallback deep HTML5 & network manifest sniffer for arbitrary websites.
        """
        url = url.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url

        # First attempt: yt-dlp extraction
        try:
            import yt_dlp
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    return self._process_ytdlp_info(info, url)
        except Exception as e:
            # yt-dlp failed or unsupported extractor, fall back to deep webpage scraping
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

        # Fallback: Deep DOM & Network sniffer
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
            fmt_id = f.get("format_id")
            ext = f.get("ext") or "mp4"
            vcodec = f.get("vcodec") or "none"
            acodec = f.get("acodec") or "none"
            height = f.get("height")
            filesize = f.get("filesize") or f.get("filesize_approx") or 0
            url = f.get("url")

            is_video = vcodec != "none"
            is_audio = acodec != "none"

            if is_video:
                resolution_label = f"{height}p" if height else (f.get("resolution") or "Standard")
                # Group by resolution to present the best stream per quality
                if resolution_label not in quality_map or filesize > quality_map[resolution_label]["filesize"]:
                    quality_map[resolution_label] = {
                        "format_id": fmt_id,
                        "quality_label": resolution_label,
                        "resolution": resolution_label,
                        "height": height or 0,
                        "ext": ext,
                        "codec": f"{vcodec}/{acodec}",
                        "filesize": filesize,
                        "filesize_str": format_bytes(filesize) if filesize > 0 else "Adaptive / Unknown",
                        "has_audio": is_audio,
                        "has_video": True,
                        "direct_url": url,
                        "download_selector": f"best[height<={height}][ext=mp4][acodec!=none]/best[height<={height}][acodec!=none]/b/18/best" if height else "b/18/best[vcodec!=none][acodec!=none]/best"
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
                    "download_selector": "bestaudio/best"
                })

        # Sort video options by height descending (e.g. 1080p, 720p, 480p)
        sorted_video = sorted(quality_map.values(), key=lambda x: x["height"], reverse=True)

        # Append top audio options
        best_audio = sorted(audio_options, key=lambda x: x["filesize"], reverse=True)[:2]
        all_formats = sorted_video + best_audio

        # If no formats extracted, synthesize standard defaults
        if not all_formats:
            all_formats.append({
                "format_id": "best",
                "quality_label": "Best Available",
                "resolution": "Auto",
                "height": 0,
                "ext": "mp4",
                "codec": "auto",
                "filesize": 0,
                "filesize_str": "Standard",
                "has_audio": True,
                "has_video": True,
                "direct_url": original_url,
                "download_selector": "best"
            })

        # Select the best direct URL that has both video and audio for in-app preview
        best_direct = next((f["direct_url"] for f in all_formats if f.get("has_audio") and f.get("has_video") and f.get("direct_url")), "")
        if not best_direct and all_formats:
            best_direct = all_formats[0].get("direct_url", "")

        return {
            "success": True,
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
        - HTML5 <video> tags and <source> elements
        - OpenGraph & Twitter video metadata
        - HLS .m3u8 playlist URLs
        - MPEG-DASH .mpd manifest URLs
        - Direct .mp4 / .webm video links in page scripts
        """
        try:
            resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=12)
            html = resp.text
        except Exception as e:
            return {
                "success": False,
                "title": "Unreachable URL",
                "source_url": url,
                "is_protected": False,
                "error_message": f"Could not connect to URL: {str(e)}",
                "formats": []
            }

        # Determine Page Title
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else "Detected Web Video"

        # Determine Thumbnail
        thumbnail = ""
        og_img = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if not og_img:
            og_img = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\']', html, re.IGNORECASE)
        if og_img and og_img.group(1):
            thumbnail = urllib.parse.urljoin(url, og_img.group(1))

        detected_urls = set()

        # 1. HTML5 <video> & <source> tags
        for v in re.finditer(r'<video[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE):
            detected_urls.add(urllib.parse.urljoin(url, v.group(1)))
        for s in re.finditer(r'<source[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE):
            detected_urls.add(urllib.parse.urljoin(url, s.group(1)))

        # 2. Meta tags (OpenGraph / Twitter card video)
        for meta_name in ["og:video", "og:video:url", "og:video:secure_url", "twitter:player:stream"]:
            m = re.search(rf'<meta[^>]+(?:property|name)=["\']{re.escape(meta_name)}["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
            if not m:
                m = re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(meta_name)}["\']', html, re.IGNORECASE)
            if m and m.group(1):
                detected_urls.add(urllib.parse.urljoin(url, m.group(1)))

        # 3. Regex search in page scripts for .m3u8, .mpd, .mp4
        m3u8_pattern = r'https?://[^\s"\'<>]+\.m3u8(?:\?[^\s"\'<>]*)?'
        mpd_pattern = r'https?://[^\s"\'<>]+\.mpd(?:\?[^\s"\'<>]*)?'
        mp4_pattern = r'https?://[^\s"\'<>]+\.(?:mp4|webm|mkv)(?:\?[^\s"\'<>]*)?'

        for match in re.findall(m3u8_pattern, html):
            detected_urls.add(match)
        for match in re.findall(mpd_pattern, html):
            detected_urls.add(match)
        for match in re.findall(mp4_pattern, html):
            detected_urls.add(match)

        if not detected_urls:
            return {
                "success": False,
                "title": title,
                "source_url": url,
                "is_protected": False,
                "error_message": "No downloadable video stream was detected on this page.",
                "formats": []
            }

        # Build formats from detected URLs
        formats = []
        for i, media_url in enumerate(detected_urls):
            ext = "m3u8" if ".m3u8" in media_url else ("mpd" if ".mpd" in media_url else "mp4")
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
                "download_selector": "best"
            })

        return {
            "success": True,
            "title": title,
            "thumbnail": thumbnail,
            "duration": 0,
            "duration_str": "Stream",
            "source_url": url,
            "is_protected": False,
            "formats": formats,
            "detected_count": len(formats)
        }
