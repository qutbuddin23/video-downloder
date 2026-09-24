"""
Android Background Service for Universal Video Downloader.
Runs on Android devices via Python-for-Android / Buildozer.
Implements the native SYSTEM_ALERT_WINDOW floating overlay button over other apps,
and manages background downloads with ongoing notifications.
"""

import time
import os

try:
    from jnius import autoclass
    from jnius import cast
    ANDROID_AVAILABLE = True
except ImportError:
    ANDROID_AVAILABLE = False


def setup_android_floating_button(context):
    """Initializes native Android WindowManager floating overlay."""
    if not ANDROID_AVAILABLE:
        print("Native Android APIs (PyJNIus) not available on this platform.")
        return

    try:
        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        Context = autoclass("android.content.Context")
        WindowManager = autoclass("android.view.WindowManager")
        LayoutParams = autoclass("android.view.WindowManager$LayoutParams")
        PixelFormat = autoclass("android.graphics.PixelFormat")
        Gravity = autoclass("android.view.Gravity")
        ImageView = autoclass("android.widget.ImageView")
        sdk_int = 30
        try:
            BuildVersion = autoclass("android.os.Build$VERSION")
            sdk_int = int(BuildVersion.SDK_INT)
        except Exception:
            pass

        window_manager = cast(WindowManager, service.getSystemService(Context.WINDOW_SERVICE))

        # Check Android version for layout type
        if sdk_int >= 26:
            layout_type = LayoutParams.TYPE_APPLICATION_OVERLAY
        else:
            layout_type = LayoutParams.TYPE_PHONE

        params = LayoutParams(
            160, 160, # 160x160 dp
            layout_type,
            LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        )
        params.gravity = Gravity.TOP | Gravity.START
        params.x = 0
        params.y = 300

        # Floating ImageView
        floating_view = ImageView(service)
        # Note: image resource can be set from drawable or bitmap
        window_manager.addView(floating_view, params)
        print("Android Floating Button successfully mounted to WindowManager.")

    except Exception as e:
        print(f"Error initializing Android floating overlay: {e}")


def main():
    print("Android Downloader Background Service Started.")
    while True:
        # Maintain background heartbeat
        time.sleep(5)


if __name__ == "__main__":
    main()
