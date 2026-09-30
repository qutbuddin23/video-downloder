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


def test_svg_and_images_strictly_rejected():
    from core.detector import is_valid_media_url
    detector = MediaDetector()

    # Verify is_valid_media_url
    assert is_valid_media_url("https://example.com/icon.svg") is False
    assert is_valid_media_url("https://example.com/logo.png") is False
    assert is_valid_media_url("https://example.com/image.webp?size=small") is False
    assert is_valid_media_url("data:image/svg+xml;utf8,<svg></svg>") is False
    assert is_valid_media_url("https://example.com/video.mp4") is True
    assert is_valid_media_url("https://example.com/live/stream.m3u8?token=xyz") is True

    # Test sniffing rejects picture/source svg and images
    sample_html = """
    <!DOCTYPE html>
    <html>
    <body>
        <picture>
            <source srcset="/assets/logo.svg" type="image/svg+xml">
            <img src="/assets/logo.png">
        </picture>
        <source src="/assets/hero.webp" type="image/webp">
        <video src="/media/real_video.mp4"></video>
    </body>
    </html>
    """
    mock_resp = MagicMock()
    mock_resp.text = sample_html
    mock_resp.status_code = 200
    mock_resp.url = "https://example.com"
    mock_resp.cookies = {}

    # Mock curl_cffi session to raise so requests.get fallback is used
    mock_cffi_sess = MagicMock()
    mock_cffi_sess.get.side_effect = Exception("mocked curl_cffi unavailable")
    mock_cffi_module = MagicMock()
    mock_cffi_module.Session.return_value = mock_cffi_sess

    with patch("requests.get", return_value=mock_resp), \
         patch.dict("sys.modules", {"curl_cffi": MagicMock(), "curl_cffi.requests": mock_cffi_module}):
        res = detector._sniff_webpage("https://example.com")
        assert res["success"] is True
        assert res["detected_count"] == 1
        assert "real_video.mp4" in res["formats"][0]["direct_url"]
        assert not any("svg" in f["direct_url"] for f in res["formats"])
        assert not any("webp" in f["direct_url"] for f in res["formats"])


def test_generic_site_formats_without_vcodec_recognized():
    detector = MediaDetector()
    mock_info = {
        "title": "Generic Tube Video",
        "formats": [
            {
                "format_id": "sb0",
                "ext": "mhtml",
                "vcodec": "none",
                "acodec": "none"
            },
            {
                "format_id": "240p",
                "ext": "mp4",
                "height": 240,
                "video_ext": "mp4",
                "url": "https://example.com/video_240p.mp4?token=123"
            },
            {
                "format_id": "480p",
                "ext": "mp4",
                "height": 480,
                "video_ext": "mp4",
                "url": "https://example.com/video_480p.mp4?token=456"
            }
        ]
    }
    processed = detector._process_ytdlp_info(mock_info, "https://example.com/watch")
    assert processed["success"] is True
    assert len(processed["formats"]) == 2
    # Storyboard sb0 must be excluded
    assert not any(f["format_id"] == "sb0" for f in processed["formats"])
    # 480p must be first
    assert processed["formats"][0]["resolution"] == "480p"
    assert "video_480p.mp4" in processed["direct_url"]


def test_direct_media_url_fast_path():
    detector = MediaDetector()
    direct_mp4 = "https://cdn.example.com/videos/sample_360p.mp4?validfrom=123&expire=456"
    res = detector.analyze_url(direct_mp4)
    assert res["success"] is True
    assert res.get("is_direct") is True
    assert len(res["formats"]) == 1
    assert res["formats"][0]["direct_url"] == direct_mp4
    assert res["formats"][0]["ext"] == "mp4"


def test_trailing_slash_media_urls_and_sources():
    from core.detector import is_valid_media_url, is_direct_download_url
    detector = MediaDetector()

    # URLs with trailing slashes must be recognized as valid media URLs
    assert is_valid_media_url("https://cdn.example.com/videos/93767542_2160m.mp4/") is True
    assert is_valid_media_url("https://cdn.example.com/videos/93767542_720m.mp4/") is True
    assert is_valid_media_url("https://cdn.example.com/streams/live.m3u8/") is True
    assert is_direct_download_url("https://cdn.example.com/videos/test.mp4/") is True

    # Test sniffing of <source> tags with labels and trailing slashes
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head><title>High Quality Video</title></head>
    <body>
        <video id="player">
            <source src="https://cdn.example.com/get_file/93767542_2160m.mp4/" type="video/mp4" label="2160p">
            <source src="https://cdn.example.com/get_file/93767542_720m.mp4/" type="video/mp4" label="720p" selected="true">
            <source src="https://cdn.example.com/get_file/93767542_480m.mp4/" type="video/mp4" label="480p">
        </video>
    </body>
    </html>
    """
    mock_resp = MagicMock()
    mock_resp.text = sample_html
    mock_resp.status_code = 200
    mock_resp.url = "https://example.com/video/123"
    mock_resp.cookies = {}

    mock_cffi_sess = MagicMock()
    mock_cffi_sess.get.side_effect = Exception("mocked curl_cffi unavailable")
    mock_cffi_module = MagicMock()
    mock_cffi_module.Session.return_value = mock_cffi_sess

    with patch("requests.get", return_value=mock_resp), \
         patch.dict("sys.modules", {"curl_cffi": MagicMock(), "curl_cffi.requests": mock_cffi_module}):
        res = detector._sniff_webpage("https://example.com/video/123")
        assert res["success"] is True
        # Expanded patterns may detect more unique URLs — require at least 3 (2160p, 720p, 480p)
        assert res["detected_count"] >= 3
        # Ensure key quality labels exist
        labels = [f["quality_label"] for f in res["formats"]]
        assert any("2160p 4K" in lbl for lbl in labels)
        assert any("720p HD" in lbl for lbl in labels)
        assert any("480p SD" in lbl for lbl in labels)
        # Formats should prioritize highest quality / selected
        assert res["formats"][0]["height"] in (2160, 720)


