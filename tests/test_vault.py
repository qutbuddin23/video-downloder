"""
Unit tests for Private Vault encryption, PIN verification, and storage metrics.
"""

import os
import shutil
import tempfile
import pytest
from core.database import Database
from core.vault import VaultManager


@pytest.fixture
def temp_env():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    db = Database(db_path=db_path)
    vault = VaultManager(db)
    vault.vault_dir = os.path.join(temp_dir, "vault")
    os.makedirs(vault.vault_dir, exist_ok=True)
    yield db, vault, temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_pin_set_and_verify(temp_env):
    db, vault, _ = temp_env
    # PIN is pre-set to 7232 by default and initialized in locked state
    assert vault.is_pin_set()
    assert not vault.is_unlocked

    # Verify wrong PIN fails
    assert not vault.verify_and_unlock("9999")
    assert not vault.is_unlocked

    # Verify pre-set 7232 unlocks successfully
    assert vault.verify_and_unlock("7232")
    assert vault.is_unlocked

    # Lock again
    vault.lock()
    assert not vault.is_unlocked

    # Update to custom PIN
    vault.set_pin("1234")
    assert vault.is_unlocked
    vault.lock()
    assert vault.verify_and_unlock("1234")
    assert vault.is_unlocked


def test_encrypt_and_decrypt_roundtrip(temp_env):
    db, vault, temp_dir = temp_env
    vault.set_pin("4321")

    # Create dummy video file
    video_content = b"TEST_VIDEO_PAYLOAD_DATA_XYZ_1234567890" * 100
    dummy_video_path = os.path.join(temp_dir, "sample_video.mp4")
    with open(dummy_video_path, "wb") as f:
        f.write(video_content)

    # Add download record in DB
    dl_id = "dl_test_1"
    db.add_download({
        "id": dl_id,
        "url": "https://example.com/video.mp4",
        "title": "Sample Video",
        "file_path": dummy_video_path,
        "file_size": len(video_content),
        "status": "completed"
    })

    # Hide video in vault
    vault_item = vault.hide_video(dl_id)
    assert vault_item is not None
    assert not os.path.exists(dummy_video_path)  # Original removed
    assert os.path.exists(vault_item["encrypted_path"])  # Encrypted exists

    # Check stats
    stats = vault.get_vault_stats()
    assert stats["total_count"] == 1
    assert stats["total_size"] == len(video_content)

    # Restore video
    restored_path = vault.restore_video(vault_item["id"])
    assert os.path.exists(restored_path)
    with open(restored_path, "rb") as f:
        restored_content = f.read()

    # Verify cryptographic byte integrity
    assert restored_content == video_content
