"""
Main application launcher for Android (Kivy + Native WebView) and Desktop.
Starts background Python HTTP server and attaches native Android WebView
to PythonActivity with hardware acceleration and back-button handling.
"""

import os
import sys
import socket
import threading
import time

try:
    from kivy.app import App
    from kivy.uix.widget import Widget
    from kivy.utils import platform
    from kivy.clock import Clock
    from kivy.core.window import Window

    class UniversalDownloaderApp(App):
        def build(self):
            self.wv = None
            # 1. Start background standard library HTTP server
            from app import run_server
            server_thread = threading.Thread(target=run_server, daemon=True)
            server_thread.start()

            # 2. On Android, schedule native WebView setup after window is initialized
            if platform == "android":
                Clock.schedule_once(self.init_android, 0.5)
                # Handle Android hardware back button
                Window.bind(on_keyboard=self.on_android_back)

            return Widget()

        def wait_for_server(self, host="127.0.0.1", port=5824, timeout=5.0):
            """Verify that the HTTP server is accepting connections."""
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    with socket.create_connection((host, port), timeout=0.5):
                        return True
                except (OSError, ConnectionRefusedError):
                    time.sleep(0.1)
            return False

        def init_android(self, dt):
            try:
                # Request runtime permissions on Android 13+
                try:
                    from android.permissions import request_permissions, Permission
                    request_permissions([
                        Permission.INTERNET,
                        Permission.READ_MEDIA_VIDEO,
                        Permission.POST_NOTIFICATIONS
                    ])
                except Exception as perm_err:
                    print(f"Android permission request note: {perm_err}")

                from jnius import autoclass
                from android.runnable import run_on_ui_thread

                @run_on_ui_thread
                def setup_android_webview():
                    # Wait up to 3 seconds for server to bind
                    self.wait_for_server()

                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    activity = PythonActivity.mActivity
                    WebView = autoclass("android.webkit.WebView")
                    WebViewClient = autoclass("android.webkit.WebViewClient")
                    WebChromeClient = autoclass("android.webkit.WebChromeClient")

                    wv = WebView(activity)
                    self.wv = wv
                    settings = wv.getSettings()
                    settings.setJavaScriptEnabled(True)
                    settings.setDomStorageEnabled(True)
                    settings.setAllowFileAccess(True)
                    settings.setAllowContentAccess(True)
                    settings.setMediaPlaybackRequiresUserGesture(False)
                    settings.setDatabaseEnabled(True)

                    wv.setWebViewClient(WebViewClient())
                    wv.setWebChromeClient(WebChromeClient())
                    activity.setContentView(wv)
                    wv.loadUrl("http://127.0.0.1:5824")

                setup_android_webview()
            except Exception as e:
                print(f"Android WebView Setup Error: {e}")

        def on_android_back(self, window, key, *args):
            """Handle Android back key (keycode 27) in WebView navigation."""
            if key == 27 and self.wv is not None:
                try:
                    from android.runnable import run_on_ui_thread
                    @run_on_ui_thread
                    def go_back_or_exit():
                        if self.wv.canGoBack():
                            self.wv.goBack()
                    go_back_or_exit()
                    return True
                except Exception:
                    pass
            return False

    def main():
        UniversalDownloaderApp().run()

except (ImportError, ModuleNotFoundError):
    # Desktop fallback when Kivy is not installed
    from app import main

if __name__ == "__main__":
    main()
