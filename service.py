"""
Android Background Service for Universal Video Downloader.
Runs on Android devices via Python-for-Android / Buildozer.
Promotes the service to a Foreground Service with ongoing notification and PARTIAL_WAKE_LOCK,
ensuring downloads continue uninterrupted when the screen is off, phone is locked, or other apps are active.
"""

import time
import os

try:
    from jnius import autoclass, cast
    ANDROID_AVAILABLE = True
except ImportError:
    ANDROID_AVAILABLE = False


def promote_to_foreground():
    """Promotes service to an Android Foreground Service with an ongoing notification."""
    if not ANDROID_AVAILABLE:
        return
    try:
        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        if not service:
            return

        Context = autoclass("android.content.Context")
        Notification = autoclass("android.app.Notification")
        NotificationManager = autoclass("android.app.NotificationManager")
        String = autoclass("java.lang.String")
        CHANNEL_ID = "universal_downloader_bg_service"

        sdk_int = 30
        try:
            BuildVersion = autoclass("android.os.Build$VERSION")
            sdk_int = int(BuildVersion.SDK_INT)
        except Exception:
            pass

        if sdk_int >= 26:
            NotificationChannel = autoclass("android.app.NotificationChannel")
            channel = NotificationChannel(
                String(CHANNEL_ID),
                cast("java.lang.CharSequence", String("Downloader Background Engine")),
                NotificationManager.IMPORTANCE_LOW
            )
            channel.setDescription(String("Ensures downloads continue while screen is off or in background"))
            nm = service.getSystemService(Context.NOTIFICATION_SERVICE)
            nm.createNotificationChannel(channel)
            builder = Notification.Builder(service, String(CHANNEL_ID))
        else:
            builder = Notification.Builder(service)

        title = String("Universal Downloader Active")
        text = String("Background downloads and media engine running")
        builder.setContentTitle(cast("java.lang.CharSequence", title))
        builder.setContentText(cast("java.lang.CharSequence", text))

        icon_id = 0
        try:
            icon_id = service.getApplicationInfo().icon
        except Exception:
            pass
        if not icon_id:
            try:
                android_R = autoclass("android.R$drawable")
                icon_id = getattr(android_R, "stat_sys_download", 17301634)
            except Exception:
                icon_id = 17301634

        builder.setSmallIcon(int(icon_id))
        builder.setOngoing(True)
        notification = builder.build()

        service.startForeground(9999, notification)
        print("[Service] Successfully started as Android Foreground Service!")
    except Exception as e:
        print(f"[Service] startForeground notice: {e}")


def acquire_wakelock():
    """Acquires CPU WakeLock so Android does not sleep the processor when screen turns off."""
    if not ANDROID_AVAILABLE:
        return None
    try:
        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        if not service:
            return None
        Context = autoclass("android.content.Context")
        PowerManager = autoclass("android.os.PowerManager")
        pm = service.getSystemService(Context.POWER_SERVICE)
        if pm:
            # PARTIAL_WAKE_LOCK = 1
            wl = pm.newWakeLock(1, "UniversalDownloader:BackgroundServiceLock")
            wl.acquire()
            print("[Service] Acquired PARTIAL_WAKE_LOCK for background service.")
            return wl
    except Exception as e:
        print(f"[Service] WakeLock notice: {e}")
    return None


def main():
    print("Android Downloader Background Service Started.")
    promote_to_foreground()
    wl = acquire_wakelock()
    try:
        while True:
            time.sleep(5)
    finally:
        if wl:
            try:
                wl.release()
            except Exception:
                pass


if __name__ == "__main__":
    main()
