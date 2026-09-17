"""
Storage Manager for Universal Video Downloader & Private Media Manager.
Computes real-time storage metrics (Vault weight, Downloads weight, Free disk space)
and provides file cleanup and duplicate detection utilities.
"""

import os
import shutil
import hashlib
from typing import Dict, Any, List
from core.database import Database
from core.paths import get_vault_dir, get_default_download_dir, get_base_data_dir

def format_bytes(bytes_num: int) -> str:
    """Format bytes into readable string (KB, MB, GB)."""
    if bytes_num <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    val = float(bytes_num)
    while val >= 1024 and i < len(units) - 1:
        val /= 1024.0
        i += 1
    return f"{val:.2f} {units[i]}"


class StorageManager:
    def __init__(self, db: Database):
        self.db = db
        self.download_folder = self.db.get_setting(
            "download_folder",
            get_default_download_dir()
        )
        self.vault_folder = get_vault_dir()
        os.makedirs(self.download_folder, exist_ok=True)
        os.makedirs(self.vault_folder, exist_ok=True)

    def _get_dir_size_and_count(self, path: str) -> tuple[int, int]:
        total_size = 0
        total_count = 0
        if not os.path.exists(path):
            return 0, 0
        for root, _, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    if not os.path.islink(fp):
                        total_size += os.path.getsize(fp)
                        total_count += 1
                except (OSError, PermissionError):
                    pass
        return total_size, total_count

    def get_storage_stats(self) -> Dict[str, Any]:
        """Returns comprehensive storage metrics for UI display."""
        # Disk usage for the drive holding downloads
        disk_target = self.download_folder if os.path.exists(self.download_folder) else get_base_data_dir()
        total_disk, used_disk, free_disk = shutil.disk_usage(disk_target)

        # Public downloads size
        downloads_size, downloads_count = self._get_dir_size_and_count(self.download_folder)

        # Private vault size
        vault_size, vault_count = self._get_dir_size_and_count(self.vault_folder)

        # Temporary / .part files size
        temp_size = 0
        temp_count = 0
        if os.path.exists(self.download_folder):
            for f in os.listdir(self.download_folder):
                if f.endswith(".part") or f.endswith(".tmp"):
                    fp = os.path.join(self.download_folder, f)
                    try:
                        temp_size += os.path.getsize(fp)
                        temp_count += 1
                    except (OSError, PermissionError):
                        pass

        return {
            "total_disk": total_disk,
            "used_disk": used_disk,
            "free_disk": free_disk,
            "downloads_size": downloads_size,
            "downloads_count": downloads_count,
            "vault_size": vault_size,
            "vault_count": vault_count,
            "temp_size": temp_size,
            "temp_count": temp_count,
            # Formatted human readable strings
            "total_disk_str": format_bytes(total_disk),
            "used_disk_str": format_bytes(used_disk),
            "free_disk_str": format_bytes(free_disk),
            "downloads_size_str": format_bytes(downloads_size),
            "vault_size_str": format_bytes(vault_size),
            "temp_size_str": format_bytes(temp_size),
            # Percentage breakdown of disk
            "downloads_percent": round((downloads_size / max(1, total_disk)) * 100, 1),
            "vault_percent": round((vault_size / max(1, total_disk)) * 100, 1),
            "free_percent": round((free_disk / max(1, total_disk)) * 100, 1),
        }

    def clean_temp_files(self) -> int:
        """Removes incomplete .part and .tmp files. Returns freed bytes."""
        freed = 0
        if os.path.exists(self.download_folder):
            for f in os.listdir(self.download_folder):
                if f.endswith(".part") or f.endswith(".tmp"):
                    fp = os.path.join(self.download_folder, f)
                    try:
                        sz = os.path.getsize(fp)
                        os.remove(fp)
                        freed += sz
                    except (OSError, PermissionError):
                        pass
        return freed

    def get_large_files(self, min_size_mb: int = 100) -> List[Dict[str, Any]]:
        """Finds files in download folder exceeding min_size_mb."""
        min_bytes = min_size_mb * 1024 * 1024
        large_files = []
        if os.path.exists(self.download_folder):
            for f in os.listdir(self.download_folder):
                fp = os.path.join(self.download_folder, f)
                if os.path.isfile(fp):
                    try:
                        sz = os.path.getsize(fp)
                        if sz >= min_bytes:
                            large_files.append({
                                "filename": f,
                                "path": fp,
                                "size": sz,
                                "size_str": format_bytes(sz)
                            })
                    except (OSError, PermissionError):
                        pass
        return sorted(large_files, key=lambda x: x["size"], reverse=True)
