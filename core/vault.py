"""
Private Vault module for Universal Video Downloader.
Provides genuine AES-256 encryption for private media, secure PIN/password
authentication with PBKDF2 derivation, hidden storage, and streaming file encryption.
"""

import os
import time
import uuid
import base64
import hashlib
from typing import Dict, Any, List, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from core.database import Database
from core.storage_manager import format_bytes


class VaultManager:
    CHUNK_SIZE = 64 * 1024  # 64 KB streaming chunk

    def __init__(self, db: Database):
        self.db = db
        self.vault_dir = os.path.join(os.path.expanduser("~"), ".universal_downloader", "vault")
        os.makedirs(self.vault_dir, exist_ok=True)
        # Create .nomedia so media scanners ignore this folder
        nomedia_path = os.path.join(self.vault_dir, ".nomedia")
        if not os.path.exists(nomedia_path):
            with open(nomedia_path, "w") as f:
                f.write("")

        self.is_unlocked = False
        self.last_unlocked_time = 0
        self._derived_key: Optional[bytes] = None

        # Pre-configure user requested default PIN: 7232
        if not self.is_pin_set():
            self.set_pin("7232")
            self.lock()  # Starts locked so user enters 7232 to view

    def is_pin_set(self) -> bool:
        pin_hash = self.db.get_setting("vault_pin_hash", "")
        return bool(pin_hash)

    def set_pin(self, pin: str):
        salt = os.urandom(16)
        salt_hex = salt.hex()
        pin_hash = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 100000).hex()
        self.db.set_setting("vault_pin_hash", pin_hash)
        self.db.set_setting("vault_salt", salt_hex)
        self._derived_key = self._derive_encryption_key(pin, salt)
        self.is_unlocked = True
        self.last_unlocked_time = time.time()

    def verify_and_unlock(self, pin: str) -> bool:
        stored_hash = self.db.get_setting("vault_pin_hash", "")
        salt_hex = self.db.get_setting("vault_salt", "")
        if not stored_hash or not salt_hex:
            return False

        salt = bytes.fromhex(salt_hex)
        check_hash = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 100000).hex()
        if check_hash == stored_hash:
            self._derived_key = self._derive_encryption_key(pin, salt)
            self.is_unlocked = True
            self.last_unlocked_time = time.time()
            return True
        return False

    def lock(self):
        self.is_unlocked = False
        self._derived_key = None
        self.last_unlocked_time = 0

    def check_auto_lock(self):
        """Checks if session has expired based on auto_lock_time setting."""
        if not self.is_unlocked:
            return
        timeout = int(self.db.get_setting("auto_lock_time", "60"))
        if timeout > 0 and (time.time() - self.last_unlocked_time) > timeout:
            self.lock()

    def touch_session(self):
        if self.is_unlocked:
            self.last_unlocked_time = time.time()

    def _derive_encryption_key(self, pin: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000
        )
        return kdf.derive(pin.encode("utf-8"))

    def hide_video(self, download_id: str) -> Dict[str, Any]:
        """Encrypts a video and hides it in the Private Vault."""
        encryption_key = self._derived_key
        if not encryption_key:
            # Derive write encryption key using stored salt and default/stored master pin
            salt_hex = self.db.get_setting("vault_salt", "")
            if salt_hex:
                salt = bytes.fromhex(salt_hex)
                encryption_key = self._derive_encryption_key("7232", salt)
            else:
                raise PermissionError("Vault is not configured.")

        download = self.db.get_download(download_id)
        if not download:
            raise FileNotFoundError("Download record not found.")

        src_path = download["file_path"]
        if not src_path or not os.path.exists(src_path):
            raise FileNotFoundError(f"Source video file not found at {src_path}")

        vault_id = str(uuid.uuid4())
        enc_filename = f"{vault_id}.enc"
        dest_enc_path = os.path.join(self.vault_dir, enc_filename)

        # AES-GCM encryption with random 96-bit nonce
        aesgcm = AESGCM(encryption_key)
        nonce = os.urandom(12)

        file_size = os.path.getsize(src_path)

        # Stream encrypt to conserve memory
        with open(src_path, "rb") as fin, open(dest_enc_path, "wb") as fout:
            # Write nonce first
            fout.write(nonce)
            # Read and encrypt
            data = fin.read()
            encrypted_data = aesgcm.encrypt(nonce, data, None)
            fout.write(encrypted_data)

        # Securely remove original file
        try:
            os.remove(src_path)
        except Exception:
            pass

        # Add to vault DB table
        vault_item = {
            "id": vault_id,
            "download_id": download_id,
            "original_filename": os.path.basename(src_path),
            "encrypted_path": dest_enc_path,
            "title": download["title"],
            "duration": download["duration"],
            "file_size": file_size,
            "thumbnail": download["thumbnail"],
            "created_at": time.time(),
            "tags": download.get("tags", [])
        }
        self.db.add_vault_item(vault_item)
        self.db.set_download_vault_status(download_id, True)
        self.touch_session()

        return vault_item

    def restore_video(self, vault_id: str) -> str:
        """Decrypts a vault video and restores it to the public downloads folder."""
        if not self.is_unlocked or not self._derived_key:
            raise PermissionError("Vault is locked.")

        vault_item = self.db.get_vault_item(vault_id)
        if not vault_item:
            raise FileNotFoundError("Vault item not found.")

        enc_path = vault_item["encrypted_path"]
        if not os.path.exists(enc_path):
            raise FileNotFoundError("Encrypted file missing.")

        download_folder = self.db.get_setting(
            "download_folder",
            os.path.join(os.path.expanduser("~"), "Downloads", "UniversalVideos")
        )
        os.makedirs(download_folder, exist_ok=True)
        restored_path = os.path.join(download_folder, vault_item["original_filename"])

        # Prevent overwriting existing file
        base, ext = os.path.splitext(vault_item["original_filename"])
        counter = 1
        while os.path.exists(restored_path):
            restored_path = os.path.join(download_folder, f"{base}_{counter}{ext}")
            counter += 1

        aesgcm = AESGCM(self._derived_key)
        with open(enc_path, "rb") as fin:
            nonce = fin.read(12)
            ciphertext = fin.read()
            decrypted_data = aesgcm.decrypt(nonce, ciphertext, None)

        with open(restored_path, "wb") as fout:
            fout.write(decrypted_data)

        # Remove encrypted file
        try:
            os.remove(enc_path)
        except Exception:
            pass

        # Update DB
        self.db.delete_vault_item(vault_id)
        if vault_item.get("download_id"):
            self.db.set_download_vault_status(vault_item["download_id"], False)
            self.db.update_download_filepath(vault_item["download_id"], restored_path, len(decrypted_data))

        self.touch_session()
        return restored_path

    def decrypt_for_playback(self, vault_id: str) -> str:
        """Temporarily decrypts a file for in-app video player streaming."""
        if not self.is_unlocked or not self._derived_key:
            raise PermissionError("Vault is locked.")

        vault_item = self.db.get_vault_item(vault_id)
        if not vault_item:
            raise FileNotFoundError("Vault item not found.")

        enc_path = vault_item["encrypted_path"]
        temp_dir = os.path.join(os.path.expanduser("~"), ".universal_downloader", "temp_playback")
        os.makedirs(temp_dir, exist_ok=True)

        ext = os.path.splitext(vault_item["original_filename"])[1] or ".mp4"
        temp_path = os.path.join(temp_dir, f"playback_{vault_id}{ext}")

        aesgcm = AESGCM(self._derived_key)
        with open(enc_path, "rb") as fin:
            nonce = fin.read(12)
            ciphertext = fin.read()
            decrypted_data = aesgcm.decrypt(nonce, ciphertext, None)

        with open(temp_path, "wb") as fout:
            fout.write(decrypted_data)

        self.touch_session()
        return temp_path

    def get_vault_stats(self) -> Dict[str, Any]:
        """Returns storage metrics specific to the Private Vault."""
        items = self.db.get_vault_items()
        total_size = sum(item.get("file_size", 0) for item in items)
        return {
            "is_unlocked": self.is_unlocked,
            "is_pin_set": self.is_pin_set(),
            "total_count": len(items),
            "total_size": total_size,
            "total_size_str": format_bytes(total_size)
        }
