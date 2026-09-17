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

    # 2. Try PyJNIus Context.getFilesDir() if available
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

def get_default_download_dir() -> str:
    """Return default public downloads directory visible in Gallery and File Manager."""
    if is_android():
        # 1. Try PyJNIus Android Environment.DIRECTORY_DOWNLOADS
        try:
            from jnius import autoclass
            Environment = autoclass("android.os.Environment")
            dl_dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            if dl_dir:
                public_path = dl_dir.getAbsolutePath()
                target_path = os.path.join(public_path, "UniversalVideos")
                os.makedirs(target_path, exist_ok=True)
                test_file = os.path.join(target_path, ".write_test")
                with open(test_file, "w") as f:
                    f.write("ok")
                os.remove(test_file)
                print(f"[Paths] Using public Android download path: {target_path}")
                return target_path
        except Exception as e:
            print(f"[Paths] PyJNIus Environment download path check: {e}")

        # 2. Try standard external shared download directories
        candidates = [
            "/storage/emulated/0/Download/UniversalVideos",
            "/storage/emulated/0/Download",
            "/sdcard/Download/UniversalVideos",
            "/sdcard/Download",
            "/storage/emulated/0/Movies",
            "/sdcard/Movies"
        ]
        for candidate in candidates:
            try:
                os.makedirs(candidate, exist_ok=True)
                test_file = os.path.join(candidate, ".write_test")
                with open(test_file, "w") as f:
                    f.write("ok")
                os.remove(test_file)
                print(f"[Paths] Using candidate Android download path: {candidate}")
                return candidate
            except Exception:
                continue

        # 3. Try Context.getExternalFilesDir (Always writable on all Android versions)
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            if activity:
                Environment = autoclass("android.os.Environment")
                ext_dir = activity.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
                if ext_dir:
                    ext_path = ext_dir.getAbsolutePath()
                    os.makedirs(ext_path, exist_ok=True)
                    print(f"[Paths] Using Context external files path: {ext_path}")
                    return ext_path
        except Exception as e:
            print(f"[Paths] getExternalFilesDir notice: {e}")

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
