"""
Unit tests for Media Detection and Stream Sniffing Engine.
"""

from unittest.mock import patch, MagicMock
from core.detector import MediaDetector, format_duration


def test_format_duration():
    assert format_duration(0) == "Unknown"
    assert format_duration(45) == "00:45"
    assert format_duration(125) == "02:05"
    assert format_duration(3665) == "01:01:05"


def test_html5_media_sniffing():
    detector = MediaDetector()
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head><title>Custom Video Page</title></head>
    <body>
        <video src="/media/sample_stream.mp4"></video>
        <script>
            var playlist = "https://cdn.example.com/live/master.m3u8";
        </script>
    </body>
    </html>
    """

    mock_resp = MagicMock()
    mock_resp.text = sample_html
    mock_resp.status_code = 200

    with patch("requests.get", return_value=mock_resp):
        res = detector._sniff_webpage("https://example.com/watch")
        assert res["success"] is True
        assert res["title"] == "Custom Video Page"
        assert res["detected_count"] >= 2

        # Check detected streams
        urls = [f["direct_url"] for f in res["formats"]]
        assert any("sample_stream.mp4" in u for u in urls)
        assert any("master.m3u8" in u for u in urls)


def test_drm_detection_handling():
    detector = MediaDetector()
    mock_info = {
        "title": "Encrypted Stream",
        "formats": [
            {"format_id": "1", "format_note": "DRM Widevine Encrypted", "vcodec": "avc1"}
        ]
    }
    processed = detector._process_ytdlp_info(mock_info, "https://example.com/drm")
    assert processed["is_protected"] is True
    assert "DRM" in processed["protection_reason"]
