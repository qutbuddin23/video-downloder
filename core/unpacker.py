"""
Dean Edwards JavaScript P.A.C.K.E.R. and Playerjs Stream Decoder.
Pure Python standard library implementation with zero external C/Rust dependencies.
"""

import re
import base64
import urllib.parse
from typing import List, Dict, Optional, Tuple


class PackerDecoder:
    """
    Decodes JavaScript code packed using Dean Edwards P.A.C.K.E.R.
    Pattern: eval(function(p,a,c,k,e,d){...}('payload', radix, count, 'keywords'.split('|'), ...))
    """
    ALPHABET_62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

    @classmethod
    def itob(cls, val: int, radix: int) -> str:
        """Converts an integer to a string in the given radix (base up to 62)."""
        if val == 0:
            return "0"
        chars = cls.ALPHABET_62[:radix] if radix <= 62 else cls.ALPHABET_62
        res = []
        while val > 0:
            res.append(chars[val % radix])
            val //= radix
        return "".join(reversed(res))

    @classmethod
    def btoi(cls, s: str, radix: int) -> int:
        """Converts a base-N string to an integer."""
        chars = cls.ALPHABET_62[:radix] if radix <= 62 else cls.ALPHABET_62
        val = 0
        for ch in s:
            idx = chars.find(ch)
            if idx == -1:
                return -1
            val = val * radix + idx
        return val

    @classmethod
    def unpack(cls, packed_code: str) -> str:
        """Unpacks Dean Edwards packed JavaScript code string."""
        pattern = r"\}\s*\(\s*(['\"].*?['\"])\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(['\"].*?['\"])\s*\.split\(\s*['\"]\|['\"]\s*\)"
        match = re.search(pattern, packed_code, re.DOTALL)
        if not match:
            # Alternate pattern with variables at the beginning
            alt_pattern = r"return\s+p\}\s*\(\s*(['\"].*?['\"])\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(['\"].*?['\"])\.split\(['\"]\|['\"]\)"
            match = re.search(alt_pattern, packed_code, re.DOTALL)

        if not match:
            return ""

        payload_raw = match.group(1)[1:-1]  # remove surrounding quotes
        radix = int(match.group(2))
        count = int(match.group(3))
        keywords_str = match.group(4)[1:-1]
        symtab = keywords_str.split("|")

        # Unescape common escaped chars in payload
        payload = payload_raw.encode("utf-8").decode("unicode_escape", errors="replace")

        def _replace_word(m):
            word = m.group(0)
            idx = cls.btoi(word, radix)
            if 0 <= idx < len(symtab) and symtab[idx]:
                return symtab[idx]
            return word

        unpacked = re.sub(r"\b[0-9a-zA-Z]+\b", _replace_word, payload)
        return unpacked

    @classmethod
    def find_and_unpack_all(cls, html_or_js: str) -> List[str]:
        """Finds all eval(function(p,a,c,k,e,...)) instances in text and returns their unpacked results."""
        results = []
        # Find occurrences of eval(function(p,a,c,k,e
        matches = re.finditer(r"eval\s*\(\s*function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k\s*,\s*e\s*,\s*[dr]\s*\)", html_or_js, re.IGNORECASE)
        for m in matches:
            start_pos = m.start()
            chunk = html_or_js[start_pos:start_pos + 12000]
            unpacked = cls.unpack(chunk)
            if unpacked:
                results.append(unpacked)
        return results


class PlayerjsDecoder:
    """Decodes Playerjs video configurations and obfuscated stream links."""

    @staticmethod
    def decode_file_string(file_str: str) -> List[Tuple[str, str]]:
        """
        Parses Playerjs file string:
        Formats:
        - "[1080p]https://...,[720p]https://..."
        - "#2aHR0cHM6Ly..." (Base64 encoded)
        - "https://..."
        Returns list of (quality_label, url).
        """
        results = []
        if not file_str:
            return results

        clean = file_str.strip().strip('"\'')
        # Check for #2 Base64 encoding
        if clean.startswith("#2"):
            try:
                b64_part = clean[2:]
                # Add padding if necessary
                b64_part += "=" * (-len(b64_part) % 4)
                decoded = base64.b64decode(b64_part).decode("utf-8", errors="replace")
                if decoded.startswith("http") or "[" in decoded:
                    clean = decoded
            except Exception:
                pass

        # Split comma-separated qualities: [720p]https://...
        for part in clean.split(","):
            part = part.strip()
            if not part:
                continue
            m = re.search(r"(?:\[([^\]]+)\])?\s*(https?://[^\s,\"\'<>]+)", part)
            if m:
                label = m.group(1) or "HD"
                url = m.group(2)
                results.append((label, url))

        return results


def extract_media_from_unpacked_js(code: str) -> List[str]:
    """Finds all .m3u8, .mpd, .mp4, and media stream URLs in unpacked JS code."""
    found = []
    # 1. Direct URLs with extension
    for u in re.findall(r'https?://[^\s"\'<>]+\.(?:m3u8|mpd|mp4|webm|mkv)(?:\?[^\s"\'<>]*)?', code, re.I):
        found.append(u)

    # 2. File / source parameters
    for m in re.finditer(r'["\']?(?:file|source|src|stream|url|video)["\']?\s*[:=]\s*["\'](https?://[^\s"\'<>]+)["\']', code, re.I):
        u = m.group(1)
        if any(ext in u.lower() for ext in [".m3u8", ".mpd", ".mp4", "stream", "video", "manifest", "chunklist"]):
            found.append(u)

    return list(dict.fromkeys(found))
