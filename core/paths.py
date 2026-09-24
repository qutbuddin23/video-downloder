"""
Cross-platform path resolver for Android and Desktop.
Ensures data, downloads, and vault directories are safely resolved to
writable locations without triggering permission errors on Android sandboxes.
"""

import os
import sys
import time

class SafeStreamWrapper:
    """Wraps sys.stdout / sys.stderr so any .write() or .flush() calls never crash."""
    def __init__(self, target):
        self._target = target

    def write(self, s):
        try:
            if hasattr(self._target, "write") and callable(self._target.write):
                return self._target.write(str(s))
        except Exception:
            pass
        return len(s) if isinstance(s, (str, bytes)) else 0

    def flush(self):
        try:
            if hasattr(self._target, "flush") and callable(self._target.flush):
                self._target.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._target, name, None)


if not hasattr(sys.stderr, "write") or isinstance(sys.stderr, str):
    sys.stderr = SafeStreamWrapper(sys.stderr)
if not hasattr(sys.stdout, "write") or isinstance(sys.stdout, str):
    sys.stdout = SafeStreamWrapper(sys.stdout)


class SafeYtdlLogger:
    """Safe logger for yt-dlp that never relies on sys.stderr or sys.stdout having a write attribute."""
    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        try:
            print(f"[yt-dlp] {msg}")
        except Exception:
            pass

    def write(self, msg):
        pass

    def flush(self):
        pass


def is_android() -> bool:
    """Bulletproof Android detection across all p4a, Kivy, and Android OS versions."""
    try:
        from kivy.utils import platform
        if platform == "android":
            return True
    except Exception:
        pass
    if hasattr(sys, "getandroidapilevel"):
        return True
    if any(k in os.environ for k in ["ANDROID_ARGUMENT", "ANDROID_PRIVATE", "ANDROID_ROOT", "ANDROID_DATA", "PYTHON_SERVICE_ARGUMENT"]):
        return True
    try:
        from jnius import autoclass
        if autoclass("org.kivy.android.PythonActivity"):
            return True
    except Exception:
        pass
    return False

def get_base_data_dir() -> str:
    """Return a safe writable root directory for database, vault, and app data."""
    # 1. Try PyJNIus Context.getFilesDir() (100% writable on Android internal storage)
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        if PythonActivity and PythonActivity.mActivity:
            files_dir = PythonActivity.mActivity.getFilesDir().getAbsolutePath()
            app_dir = os.path.join(files_dir, ".universal_downloader")
            os.makedirs(app_dir, exist_ok=True)
            return app_dir
    except Exception:
        pass

    # 2. Check Android environment variables set by python-for-android
    for env_var in ["ANDROID_PRIVATE", "ANDROID_ARGUMENT"]:
        val = os.environ.get(env_var)
        if val:
            try:
                os.makedirs(val, exist_ok=True)
                app_dir = os.path.join(val, ".universal_downloader")
                os.makedirs(app_dir, exist_ok=True)
                return app_dir
            except Exception:
                pass

    # 3. Android current directory fallback
    if is_android():
        app_dir = os.path.join(os.getcwd(), ".universal_downloader")
        try:
            os.makedirs(app_dir, exist_ok=True)
            return app_dir
        except Exception:
            return os.getcwd()

    # 4. Desktop / Standard OS fallback
    home = os.path.expanduser("~")
    app_dir = os.path.join(home, ".universal_downloader")
    try:
        os.makedirs(app_dir, exist_ok=True)
        return app_dir
    except Exception:
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

def is_directory_writable(path: str) -> bool:
    """Explicitly verify folder writability by writing and removing a small test file."""
    if not path:
        return False
    try:
        os.makedirs(path, exist_ok=True)
        test_file = os.path.join(path, f".chk_{os.getpid()}_{int(time.time()*1000)%10000}")
        with open(test_file, "wb") as f:
            f.write(b"ok")
        if os.path.exists(test_file):
            os.remove(test_file)
        return True
    except Exception:
        return False

def get_default_download_dir() -> str:
    """Return default public downloads directory visible in Gallery and File Manager."""
    if is_android():
        # 1. Primary Android location: Context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
        # On Android 10, 11, 12, 13, 14, 15, getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
        # is ALWAYS fully writable without requiring MANAGE_EXTERNAL_STORAGE permission,
        # AND files scanned with MediaScannerConnection immediately show up in the Gallery & Downloads!
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            if activity:
                Environment = autoclass("android.os.Environment")
                ext_dir = activity.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
                if ext_dir:
                    ext_path = ext_dir.getAbsolutePath()
                    if is_directory_writable(ext_path):
                        print(f"[Paths] Using safe external files dir: {ext_path}")
                        return ext_path
        except Exception as e:
            print(f"[Paths] getExternalFilesDir notice: {e}")

        # 2. Try PyJNIus Android Environment.getExternalStoragePublicDirectory
        try:
            from jnius import autoclass
            Environment = autoclass("android.os.Environment")
            dl_dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            if dl_dir:
                public_path = dl_dir.getAbsolutePath()
                target_path = os.path.join(public_path, "UniversalVideos")
                if is_directory_writable(target_path):
                    print(f"[Paths] Using public Android download path: {target_path}")
                    return target_path
        except Exception as e:
            print(f"[Paths] PyJNIus Environment download path check: {e}")

        # 3. Try standard external shared download directories
        candidates = [
            "/storage/emulated/0/Download/UniversalVideos",
            "/storage/emulated/0/Download",
            "/sdcard/Download/UniversalVideos",
            "/sdcard/Download",
            "/storage/emulated/0/Movies",
            "/sdcard/Movies"
        ]
        for candidate in candidates:
            if is_directory_writable(candidate):
                print(f"[Paths] Using candidate Android download path: {candidate}")
                return candidate

        # 4. Safe internal fallback if all external attempts fail
        safe_fallback = os.path.join(get_base_data_dir(), "downloads")
        os.makedirs(safe_fallback, exist_ok=True)
        return safe_fallback

    # Desktop standard downloads
    home = os.path.expanduser("~")
    desktop_dl = os.path.join(home, "Downloads", "UniversalVideos")
    if is_directory_writable(desktop_dl):
        return desktop_dl
    fallback = os.path.join(get_base_data_dir(), "downloads")
    os.makedirs(fallback, exist_ok=True)
    return fallback

