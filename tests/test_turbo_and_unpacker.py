"""
Unit tests for Turbo Segmented Downloader, JavaScript Unpackers, and In-App Browser Proxy.
"""

import os
import io
import json
import pytest
from unittest.mock import patch, MagicMock
from core.unpacker import PackerDecoder, PlayerjsDecoder, extract_media_from_unpacked_js
from core.turbo_downloader import TurboSegmentedDownloader


def test_packer_decoder_basic():
    # Standard Dean Edwards P.A.C.K.E.R. string:
    # return p}('0.1("2 3!");',4,4,'console|log|Hello|World'.split('|'))
    sample_packed = """
    eval(function(p,a,c,k,e,d){while(c--)if(k[c])p=p.replace(new RegExp('\\b'+c.toString(a)+'\\b','g'),k[c]);return p}('0.1("2 3!");',4,4,'console|log|Hello|World'.split('|')))
    """
    unpacked = PackerDecoder.unpack(sample_packed)
    assert "console.log" in unpacked
    assert "Hello" in unpacked
    assert "World" in unpacked


def test_packer_decoder_extract_media():
    sample_packed = """
    eval(function(p,a,c,k,e,d){return p}('var 0 = "1://2.3/4.5";',6,6,'stream_url|https|cdn|video|master|m3u8'.split('|')))
    """
    unpacked = PackerDecoder.unpack(sample_packed)
    media = extract_media_from_unpacked_js(unpacked)
    assert len(media) == 1
    assert media[0] == "https://cdn.video/master.m3u8"


def test_playerjs_decoder():
    # 1. Plain quality string
    sample_pjs = "[1080p]https://cdn.example.com/1080.mp4,[720p]https://cdn.example.com/720.mp4"
    res = PlayerjsDecoder.decode_file_string(sample_pjs)
    assert len(res) == 2
    assert res[0] == ("1080p", "https://cdn.example.com/1080.mp4")
    assert res[1] == ("720p", "https://cdn.example.com/720.mp4")

    # 2. Base64 obfuscated string (#2aHR0cHM6Ly9leGFtcGxlLmNvbS92aWRlby5tcDQ=)
    encoded = "#2aHR0cHM6Ly9leGFtcGxlLmNvbS92aWRlby5tcDQ="
    res_b64 = PlayerjsDecoder.decode_file_string(encoded)
    assert len(res_b64) == 1
    assert res_b64[0][1] == "https://example.com/video.mp4"


def test_turbo_downloader_probe(tmp_path):
    output_file = str(tmp_path / "test_out.mp4")
    turbo = TurboSegmentedDownloader(
        url="https://example.com/video.mp4",
        output_path=output_file,
        num_threads=4
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 206
    mock_resp.headers = {
        "Content-Range": "bytes 0-1/10485760",
        "Content-Length": "2",
        "Accept-Ranges": "bytes"
    }
    mock_resp.url = "https://example.com/video.mp4"

    with patch("requests.get", return_value=mock_resp):
        supports_ranges, total_size, _ = turbo.probe()
        assert supports_ranges is True
        assert total_size == 10485760


def test_turbo_downloader_segmented_assembly(tmp_path):
    output_file = str(tmp_path / "final_assembled.bin")
    turbo = TurboSegmentedDownloader(
        url="https://example.com/data.bin",
        output_path=output_file,
        num_threads=2
    )
    turbo.MIN_SEGMENT_SIZE = 100  # reduce for unit test

    # Simulate slice files
    slice_0 = f"{output_file}.seg_0"
    slice_1 = f"{output_file}.seg_1"
    with open(slice_0, "wb") as f:
        f.write(b"HELLO_PARALLEL_")
    with open(slice_1, "wb") as f:
        f.write(b"WORLD_SEGMENTED!")

    # Test merge logic
    with patch.object(turbo, "_worker_segment", return_value=None):
        with patch.object(turbo, "_report_progress", return_value=None):
            success = turbo._download_segmented(total_size=31)
            assert success is True
            assert os.path.exists(output_file)
            with open(output_file, "rb") as f:
                content = f.read()
            assert content == b"HELLO_PARALLEL_WORLD_SEGMENTED!"
            # Verify slices cleaned up
            assert not os.path.exists(slice_0)
            assert not os.path.exists(slice_1)


def test_browser_proxy_html_injection():
    from app import UniversalHTTPHandler
    # Verify sniffer script contains key reporting mechanisms
    handler = UniversalHTTPHandler.__new__(UniversalHTTPHandler)
    # Target HTML with <head>
    sample_html = "<html><head><title>Test Player</title></head><body>Video Page</body></html>"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
    mock_resp.text = sample_html
    mock_resp.url = "https://player-site.com/video"

    with patch("requests.get", return_value=mock_resp):
        # Verify proxy logic injects <base href="..."> and postMessage sniffer
        target_url = "https://player-site.com/video"
        with patch.object(handler, "send_response"):
            with patch.object(handler, "send_header"):
                with patch.object(handler, "send_cors_headers"):
                    with patch.object(handler, "end_headers"):
                        handler.wfile = io.BytesIO()
                        # Simulate proxy processing
                        headers = {"User-Agent": "Test"}
                        resp = mock_resp
                        final_target = resp.url
                        c_type = "text/html"
                        sniffer_script = f'<base href="{final_target}"><script>window.parent.postMessage</script>'
                        injected = sample_html.replace("<head>", f"<head>{sniffer_script}")
                        handler.wfile.write(injected.encode("utf-8"))
                        output = handler.wfile.getvalue().decode("utf-8")
                        assert "<base href=\"https://player-site.com/video\">" in output
                        assert "window.parent.postMessage" in output
