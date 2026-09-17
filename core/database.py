"""
Database module for Universal Video Downloader & Private Media Manager.
Uses SQLite for robust, thread-safe metadata, history, and vault tracking.
"""

import sqlite3
import os
import json
import time
from typing import Dict, List, Optional, Any
from core.paths import get_db_path, get_default_download_dir


class Database:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_db_path()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Downloads table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                thumbnail TEXT,
                duration INTEGER DEFAULT 0,
                file_path TEXT,
                file_size INTEGER DEFAULT 0,
                quality TEXT,
                format TEXT,
                status TEXT DEFAULT 'queued',
                progress REAL DEFAULT 0.0,
                speed REAL DEFAULT 0.0,
                downloaded_bytes INTEGER DEFAULT 0,
                total_bytes INTEGER DEFAULT 0,
                created_at REAL,
                completed_at REAL,
                error_message TEXT,
                is_vault INTEGER DEFAULT 0,
                tags TEXT DEFAULT '[]',
                is_favorite INTEGER DEFAULT 0
            );
            """)

            # Private Vault items table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS vault_items (
                id TEXT PRIMARY KEY,
                download_id TEXT,
                original_filename TEXT NOT NULL,
                encrypted_path TEXT NOT NULL,
                title TEXT NOT NULL,
                duration INTEGER DEFAULT 0,
                file_size INTEGER DEFAULT 0,
                thumbnail TEXT,
                created_at REAL,
                tags TEXT DEFAULT '[]'
            );
            """)

            # URL Analysis History
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT,
                thumbnail TEXT,
                date_visited REAL,
                detected_count INTEGER DEFAULT 1
            );
            """)

            # Application Settings
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """)

            # Default settings if not set
            default_settings = {
                "default_quality": "best",
                "default_format": "mp4",
                "download_folder": get_default_download_dir(),
                "floating_button_enabled": "true",
                "clipboard_monitor": "true",
                "dark_mode": "true",
                "auto_lock_time": "60", # seconds
                "vault_pin_hash": "",   # hashed master PIN
                "vault_salt": "",       # hex salt
                "concurrent_downloads": "3",
                "wifi_only": "false",
                "auto_retry": "true"
            }

            for k, v in default_settings.items():
                cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?);", (k, v))

            conn.commit()

    # --- Downloads CRUD ---

    def add_download(self, item: Dict[str, Any]) -> str:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO downloads (
                id, url, title, thumbnail, duration, file_path, file_size,
                quality, format, status, progress, speed, downloaded_bytes,
                total_bytes, created_at, completed_at, error_message, is_vault, tags, is_favorite
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                item["id"],
                item.get("url", ""),
                item.get("title", "Untitled Video"),
                item.get("thumbnail", ""),
                item.get("duration", 0),
                item.get("file_path", ""),
                item.get("file_size", 0),
                item.get("quality", "Auto"),
                item.get("format", "mp4"),
                item.get("status", "queued"),
                item.get("progress", 0.0),
                item.get("speed", 0.0),
                item.get("downloaded_bytes", 0),
                item.get("total_bytes", 0),
                item.get("created_at", time.time()),
                item.get("completed_at", None),
                item.get("error_message", None),
                1 if item.get("is_vault") else 0,
                json.dumps(item.get("tags", [])),
                1 if item.get("is_favorite") else 0
            ))
            conn.commit()
            return item["id"]

    def update_download_progress(self, download_id: str, status: str, progress: float,
                                 downloaded_bytes: int, total_bytes: int, speed: float,
                                 error_message: Optional[str] = None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            completed_at = time.time() if status == "completed" else None
            cursor.execute("""
            UPDATE downloads SET
                status = ?,
                progress = ?,
                downloaded_bytes = ?,
                total_bytes = ?,
                speed = ?,
                completed_at = COALESCE(?, completed_at),
                error_message = ?
            WHERE id = ?;
            """, (status, progress, downloaded_bytes, total_bytes, speed, completed_at, error_message, download_id))
            conn.commit()

    def update_download_filepath(self, download_id: str, file_path: str, file_size: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE downloads SET file_path = ?, file_size = ? WHERE id = ?;
            """, (file_path, file_size, download_id))
            conn.commit()

    def get_download(self, download_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM downloads WHERE id = ?;", (download_id,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
                return d
            return None

    def get_downloads(self, filter_status: Optional[str] = None,
                      include_vault: bool = False,
                      search: Optional[str] = None,
                      sort_by: str = "newest") -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM downloads WHERE 1=1"
            params: List[Any] = []

            if not include_vault:
                query += " AND is_vault = 0"

            if filter_status:
                if filter_status == "active":
                    query += " AND status IN ('downloading', 'queued', 'preparing', 'paused')"
                elif filter_status == "completed":
                    query += " AND status = 'completed'"
                elif filter_status == "failed":
                    query += " AND status = 'failed'"
                else:
                    query += " AND status = ?"
                    params.append(filter_status)

            if search:
                query += " AND (title LIKE ? OR url LIKE ?)"
                params.extend([f"%{search}%", f"%{search}%"])

            if sort_by == "newest":
                query += " ORDER BY created_at DESC"
            elif sort_by == "oldest":
                query += " ORDER BY created_at ASC"
            elif sort_by == "largest":
                query += " ORDER BY file_size DESC"
            elif sort_by == "smallest":
                query += " ORDER BY file_size ASC"
            elif sort_by == "name":
                query += " ORDER BY title ASC"

            cursor.execute(query, params)
            results = []
            for row in cursor.fetchall():
                d = dict(row)
                d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
                results.append(d)
            return results

    def delete_download(self, download_id: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM downloads WHERE id = ?;", (download_id,))
            conn.commit()

    def set_download_vault_status(self, download_id: str, is_vault: bool):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE downloads SET is_vault = ? WHERE id = ?;", (1 if is_vault else 0, download_id))
            conn.commit()

    def toggle_favorite(self, download_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE downloads SET is_favorite = (1 - is_favorite) WHERE id = ?;", (download_id,))
            cursor.execute("SELECT is_favorite FROM downloads WHERE id = ?;", (download_id,))
            row = cursor.fetchone()
            conn.commit()
            return bool(row["is_favorite"]) if row else False

    # --- Vault Items CRUD ---

    def add_vault_item(self, item: Dict[str, Any]):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO vault_items (
                id, download_id, original_filename, encrypted_path, title,
                duration, file_size, thumbnail, created_at, tags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                item["id"],
                item.get("download_id"),
                item["original_filename"],
                item["encrypted_path"],
                item.get("title", "Private Video"),
                item.get("duration", 0),
                item.get("file_size", 0),
                item.get("thumbnail", ""),
                item.get("created_at", time.time()),
                json.dumps(item.get("tags", []))
            ))
            conn.commit()

    def get_vault_items(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vault_items ORDER BY created_at DESC;")
            results = []
            for row in cursor.fetchall():
                d = dict(row)
                d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
                results.append(d)
            return results

    def get_vault_item(self, vault_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vault_items WHERE id = ?;", (vault_id,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
                return d
            return None

    def delete_vault_item(self, vault_id: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM vault_items WHERE id = ?;", (vault_id,))
            conn.commit()

    # --- History Tracking ---

    def record_history(self, url: str, title: str, thumbnail: str = ""):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO history (url, title, thumbnail, date_visited, detected_count)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(url) DO UPDATE SET
                date_visited = ?,
                title = COALESCE(?, title),
                thumbnail = COALESCE(?, thumbnail),
                detected_count = detected_count + 1;
            """, (url, title, thumbnail, time.time(), time.time(), title, thumbnail))
            conn.commit()

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM history ORDER BY date_visited DESC LIMIT ?;", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def clear_history(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM history;")
            conn.commit()

    # --- Settings ---

    def get_setting(self, key: str, default: str = "") -> str:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?;", (key,))
            row = cursor.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?);", (key, str(value)))
            conn.commit()

    def get_all_settings(self) -> Dict[str, str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM settings;")
            return {row["key"]: row["value"] for row in cursor.fetchall()}
