"""
Android Background Service for Universal Video Downloader.
Runs on Android devices via Python-for-Android / Buildozer.
Promotes the service to a Foreground Service with ongoing notification, PARTIAL_WAKE_LOCK,
and high-performance WifiLock, and runs the core media download engine so downloads
continue uninterrupted at maximum speed when the screen is off, phone is locked, or other apps are active.
"""

import time
import os
import threading
from core.dns_resolver import install_smart_dns
install_smart_dns()

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

        if sdk_int >= 34:
            try:
                ServiceInfo = autoclass("android.content.pm.ServiceInfo")
                # FOREGROUND_SERVICE_TYPE_DATA_SYNC = 1
                type_flag = getattr(ServiceInfo, "FOREGROUND_SERVICE_TYPE_DATA_SYNC", 1)
                service.startForeground(9999, notification, int(type_flag))
                print("[Service] Successfully started as Android 14+ Foreground Service with DATA_SYNC!")
            except Exception as e34:
                print(f"[Service] Android 14 type start notice ({e34}), falling back to standard startForeground")
                service.startForeground(9999, notification)
        else:
            service.startForeground(9999, notification)
            print("[Service] Successfully started as Android Foreground Service!")
    except Exception as e:
        print(f"[Service] startForeground notice: {e}")


def acquire_locks():
    """Acquires CPU WakeLock and WifiLock so Android does not sleep the CPU or drop Wi-Fi when screen turns off."""
    locks = []
    if not ANDROID_AVAILABLE:
        return locks
    try:
        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        if not service:
            return locks
        Context = autoclass("android.content.Context")
        PowerManager = autoclass("android.os.PowerManager")
        pm = service.getSystemService(Context.POWER_SERVICE)
        if pm:
            # PARTIAL_WAKE_LOCK = 1
            wl = pm.newWakeLock(1, "UniversalDownloader:BackgroundServiceLock")
            wl.acquire()
            locks.append(wl)
            print("[Service] Acquired PARTIAL_WAKE_LOCK for background service.")

        WifiManager = autoclass("android.net.wifi.WifiManager")
        wm = service.getSystemService(Context.WIFI_SERVICE)
        if wm:
            # WIFI_MODE_FULL_HIGH_PERF = 3
            wifi_lock = wm.createWifiLock(3, "UniversalDownloader:ServiceWifiLock")
            wifi_lock.acquire()
            locks.append(wifi_lock)
            print("[Service] Acquired WifiLock for background service.")
    except Exception as e:
        print(f"[Service] Locks acquire notice: {e}")
    return locks


def start_engine_server():
    """Runs the internal HTTP server on 127.0.0.1:5824 inside the Foreground Service."""
    try:
        from app import run_server
        srv_thread = threading.Thread(target=lambda: run_server(host="127.0.0.1", port=5824), daemon=True)
        srv_thread.start()
        print("[Service] Background HTTP media engine running on 127.0.0.1:5824")
    except Exception as e:
        print(f"[Service] Engine server launch notice: {e}")


def main():
    print("Android Downloader Background Service Starting...")
    promote_to_foreground()
    locks = acquire_locks()
    start_engine_server()
    try:
        while True:
            time.sleep(10)
    finally:
        for lock in locks:
            try:
                lock.release()
            except Exception:
                pass


if __name__ == "__main__":
    main()
