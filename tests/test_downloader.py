"""
Unit tests for Downloader Engine and File Sanitization.
"""

import os
import shutil
import tempfile
from unittest.mock import patch, MagicMock
import pytest
from core.database import Database
from core.downloader import sanitize_filename, DownloadManager


@pytest.fixture
def temp_db():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    db = Database(db_path=db_path)
    yield db, temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_sanitize_filename():
    raw = 'How to: Build "App" / Guide <2026>? *Best* | Tutorial'
    clean = sanitize_filename(raw)
    assert ":" not in clean
    assert '"' not in clean
    assert "/" not in clean
    assert "<" not in clean
    assert ">" not in clean
    assert "?" not in clean
    assert "*" not in clean
    assert "|" not in clean
    assert clean == "How_to_Build_App__Guide_2026_Best__Tutorial"


def test_download_task_record(temp_db):
    db, _ = temp_db
    dm = DownloadManager(db)

    dl_id = dm.create_download(
        url="https://example.com/test.mp4",
        title="Unit Test Video",
        quality_label="1080p",
        format_selector="best",
        direct_url=None,
        auto_start=False
    )

    record = db.get_download(dl_id)
    assert record is not None
    assert record["title"] == "Unit Test Video"
    assert record["quality"] == "1080p"
    assert record["status"] in ["queued", "downloading", "failed"]

    # Test pause
    dm.pause_download(dl_id)
    paused_rec = db.get_download(dl_id)
    assert paused_rec["status"] == "paused"

    # Test resume
    dm.resume_download(dl_id)
    assert dl_id in dm.tasks

    # Test cancel
    dm.cancel_download(dl_id)
    cancelled_rec = db.get_download(dl_id)
    assert cancelled_rec["status"] == "cancelled"

    # Ensure background thread is terminated before fixture teardown
    if dl_id in dm.tasks and dm.tasks[dl_id].thread:
        dm.tasks[dl_id].thread.join(timeout=1.0)


def test_android_notification_helper_graceful():
    from core.downloader import AndroidNotificationHelper, get_android_sdk_level
    assert isinstance(get_android_sdk_level(), int)
    assert get_android_sdk_level() >= 1
    # Verify non-Android graceful degradation (no unhandled exceptions)
    AndroidNotificationHelper.update_progress(1234, "Test Video", 50.0, "2.5 MB/s")
    AndroidNotificationHelper.show_complete(1234, "Test Video")
    AndroidNotificationHelper.cancel(1234)


def test_direct_http_fallback_to_ytdlp(temp_db):
    from unittest.mock import patch, MagicMock
    from core.downloader import DownloadTask

    db, temp_dir = temp_db
    task = DownloadTask(
        task_id="fallback_test_123",
        url="https://www.example.com/video-page",
        title="Fallback Test",
        format_selector="b",
        direct_url="https://cdn.example.com/stream.mp4",
        output_dir=temp_dir,
        db=db
    )

    # Simulate direct HTTP returning non-video / text-html
    with patch.object(task, "_download_direct_http", side_effect=ValueError("Server returned non-video content type (text/html)")) as mock_direct:
        with patch.object(task, "_download_via_ytdlp") as mock_ytdlp:
            task._run()
            mock_direct.assert_called_once()
            mock_ytdlp.assert_called_once()


def test_safe_stream_and_ytdl_logger():
    from core.paths import SafeStreamWrapper, SafeYtdlLogger

    # Test string target wrapped in SafeStreamWrapper
    dummy_str = "not a stream"
    safe = SafeStreamWrapper(dummy_str)
    assert safe.write("test log message\n") == 17
    safe.flush()  # Must not raise

    # Test SafeYtdlLogger methods
    logger = SafeYtdlLogger()
    logger.debug("debug message")
    logger.info("info message")
    logger.warning("warning message")
    logger.error("error message")
    logger.write("write message")
    logger.flush()


def test_writable_directory_and_auto_migration(tmp_path):
    from core.paths import is_directory_writable
    from core.downloader import DownloadTask
    from core.database import Database

    writable_dir = str(tmp_path / "writable")
    assert is_directory_writable(writable_dir) is True

    # Test unwritable directory migration
    db = Database(str(tmp_path / "test.db"))
    task = DownloadTask(
        task_id="mig_test_123",
        url="https://www.example.com/video",
        title="Migration Test",
        format_selector="b",
        direct_url=None,
        output_dir="Z:\\NonExistent\\Unwritable\\Path",
        db=db
    )

    with patch("core.downloader.is_directory_writable", side_effect=lambda p: p != "Z:\\NonExistent\\Unwritable\\Path"):
        with patch.object(task, "_download_via_ytdlp"):
            task._run()
            assert task.output_dir != "Z:\\NonExistent\\Unwritable\\Path"


