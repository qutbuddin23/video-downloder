"""
Cross-platform path resolver for Android and Desktop.
Ensures data, downloads, and vault directories are safely resolved to
writable locations without triggering permission errors on Android sandboxes.
"""

import os
import sys

def is_android() -> bool:
    """Detect if running on Android OS."""
    return "ANDROID_ARGUMENT" in os.environ or "ANDROID_PRIVATE" in os.environ or os.path.exists("/system/build.prop")

def get_base_data_dir() -> str:
    """Return a safe writable root directory for database, vault, and app data."""
    # 1. Check Android environment variables set by python-for-android
    android_private = os.environ.get("ANDROID_PRIVATE")
    if android_private and os.path.isdir(android_private):
        app_dir = os.path.join(android_private, ".universal_downloader")
        os.makedirs(app_dir, exist_ok=True)
        return app_dir

    android_argument = os.environ.get("ANDROID_ARGUMENT")
    if android_argument and os.path.isdir(android_argument):
        app_dir = os.path.join(android_argument, ".universal_downloader")
        os.makedirs(app_dir, exist_ok=True)
        return app_dir

    # 2. Try PyJNIus Context.getFilesDir() if available
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        if activity:
            files_dir = activity.getFilesDir().getAbsolutePath()
            app_dir = os.path.join(files_dir, ".universal_downloader")
            os.makedirs(app_dir, exist_ok=True)
            return app_dir
    except Exception:
        pass

    # 3. Desktop / Standard OS fallback
    home = os.path.expanduser("~")
    app_dir = os.path.join(home, ".universal_downloader")
    try:
        os.makedirs(app_dir, exist_ok=True)
        return app_dir
    except Exception:
        # Fallback to local workspace if home is read-only (e.g. Android root fallback)
        curr = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
        fallback_dir = os.path.join(curr, ".universal_downloader")
        os.makedirs(fallback_dir, exist_ok=True)
        return fallback_dir

def get_db_path() -> str:
    """Return database file path."""
    return os.path.join(get_base_data_dir(), "app_data.db")

def get_vault_dir() -> str:
    """Return encrypted vault directory."""
    vault_dir = os.path.join(get_base_data_dir(), "vault")
    os.makedirs(vault_dir, exist_ok=True)
    return vault_dir

def get_temp_playback_dir() -> str:
    """Return temporary playback stream directory."""
    temp_dir = os.path.join(get_base_data_dir(), "temp_playback")
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir

def get_default_download_dir() -> str:
    """Return default public downloads directory."""
    if is_android():
        # Try standard external shared download directories
        candidates = [
            "/sdcard/Download/UniversalVideos",
            "/storage/emulated/0/Download/UniversalVideos",
            os.path.join(get_base_data_dir(), "downloads")
        ]
        for candidate in candidates:
            try:
                os.makedirs(candidate, exist_ok=True)
                test_file = os.path.join(candidate, ".write_test")
                with open(test_file, "w") as f:
                    f.write("ok")
                os.remove(test_file)
                return candidate
            except Exception:
                continue
    # Desktop standard downloads
    home = os.path.expanduser("~")
    desktop_dl = os.path.join(home, "Downloads", "UniversalVideos")
    try:
        os.makedirs(desktop_dl, exist_ok=True)
        return desktop_dl
    except Exception:
        fallback = os.path.join(get_base_data_dir(), "downloads")
        os.makedirs(fallback, exist_ok=True)
        return fallback
