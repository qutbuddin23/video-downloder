"""
Comprehensive tests for Cloud Downloads (MEGA, TeraBox) and Direct File Sniffing.
"""

import json
import base64
from unittest.mock import patch, MagicMock
import pyaes
from core.mega import is_mega_url, parse_mega_url, _prepare_key, _decrypt_attr, _base64_url_decode, get_mega_file_info
from core.terabox import is_terabox_url, extract_terabox_surl, get_terabox_file_info
from core.detector import MediaDetector, is_valid_media_url, DIRECT_DOWNLOAD_EXTS


def test_mega_url_parsing():
    # Test classic hash style
    url1 = "https://mega.nz/#!abc123XY!abcdefghijklmnopqrstuvwxyz0123456789-_ABC"
    file_id1, key1 = parse_mega_url(url1)
    assert file_id1 == "abc123XY"
    assert key1 == "abcdefghijklmnopqrstuvwxyz0123456789-_ABC"

    # Test modern /file/ style
    url2 = "https://mega.nz/file/xyz789QW#mnopqrstuvw0123456789-_ABCDEFGHIJKLMNOPQ"
    file_id2, key2 = parse_mega_url(url2)
    assert file_id2 == "xyz789QW"
    assert key2 == "mnopqrstuvw0123456789-_ABCDEFGHIJKLMNOPQ"


def test_mega_crypto_key_and_attributes_decryption():
    # Verify key parser
    sample_b64 = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE"
    key_bytes, counter = _prepare_key(sample_b64)
    assert key_bytes is not None
    assert len(key_bytes) == 16
    assert counter is not None

    # Test _decrypt_attr with AES-CBC
    key = b"\x01" * 16
    raw_attr = b'MEGA{"n":"test_archive.zip","size":1048576}'
    pad_len = 16 - (len(raw_attr) % 16)
    padded = raw_attr + (b"\0" * pad_len)
    
    cbc = pyaes.AESModeOfOperationCBC(key, iv=b"\x00" * 16)
    encrypted = b"".join(cbc.encrypt(padded[i:i+16]) for i in range(0, len(padded), 16))
    # url-safe base64
    enc_b64 = base64.urlsafe_b64encode(encrypted).decode("ascii").rstrip("=")
    
    decrypted = _decrypt_attr(enc_b64, key)
    assert decrypted.get("n") == "test_archive.zip"
    assert decrypted.get("size") == 1048576


def test_terabox_url_detection():
    assert is_terabox_url("https://terabox.com/s/1a2b3c4d5e") is True
    assert is_terabox_url("https://www.1024tera.com/sharing/link?surl=a2b3c4d5e") is True
    assert is_terabox_url("https://mirrobox.com/s/9z8y7x") is True
    assert is_terabox_url("https://youtube.com/watch?v=12345") is False
    assert is_terabox_url("https://mega.nz/file/123#abc") is False

    surl1 = extract_terabox_surl("https://terabox.app/s/1ABCDEF12345")
    assert surl1 == "ABCDEF12345"

    surl2 = extract_terabox_surl("https://www.1024tera.com/sharing/link?surl=XYZ98765")
    assert surl2 == "XYZ98765"


def test_direct_file_detection_and_probing():
    detector = MediaDetector()

    # Direct archive/installer file
    res = detector.analyze_url("https://example.com/downloads/package.apk")
    assert res["success"] is True
    assert "package" in res["title"]
    assert res["formats"][0]["ext"] == "apk"

    res_zip = detector.analyze_url("https://example.com/data/backup.zip")
    assert res_zip["success"] is True
    assert res_zip["formats"][0]["ext"] == "zip"

    # Direct HTTP Probe with Content-Disposition
    mock_probe = MagicMock()
    mock_probe.status_code = 200
    mock_probe.url = "https://example.com/get-file?id=99281"
    mock_probe.headers = {
        "content-type": "application/octet-stream",
        "content-disposition": 'attachment; filename="setup_v2.iso"',
        "content-length": "734003200"
    }

    with patch("requests.get", return_value=mock_probe):
        probe_res = detector.analyze_url("https://example.com/get-file?id=99281")
        assert probe_res["success"] is True
        assert probe_res["title"] == "setup_v2.iso"
        assert probe_res["formats"][0]["ext"] == "iso"


def test_is_valid_media_url_includes_archives_and_cloud():
    # Direct archives and packages should be valid
    assert is_valid_media_url("https://example.com/app.apk") is True
    assert is_valid_media_url("https://example.com/archive.zip") is True
    assert is_valid_media_url("https://example.com/document.pdf") is True
    assert is_valid_media_url("https://mega.nz/file/xyz#123") is True
    assert is_valid_media_url("https://terabox.com/s/12345") is True

    # Image/SVG formats should still be strictly rejected
    assert is_valid_media_url("https://example.com/favicon.ico") is False
    assert is_valid_media_url("https://example.com/banner.png") is False
    assert is_valid_media_url("https://example.com/vector.svg") is False
