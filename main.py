"""
Main application launcher for Android (Kivy + Native WebView) and Desktop.
Starts background Python HTTP server, requests Android runtime permissions,
and displays full-screen native Android WebView pointing to http://127.0.0.1:5824.
"""

import os
import sys
import socket
import threading
import time
import traceback

try:
    from kivy.app import App
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.label import Label
    from kivy.utils import platform
    from kivy.clock import Clock
    from kivy.core.window import Window

    class UniversalDownloaderApp(App):
        def build(self):
            self.wv = None
            self.webview_attached = False
            self.server_ready = False
            self.server_error = None

            root = BoxLayout(orientation='vertical')
            self.status_label = Label(
                text="Universal Downloader\nStarting media engine...",
                font_size='18sp',
                halign='center',
                color=(0.9, 0.9, 1.0, 1.0)
            )
            root.add_widget(self.status_label)
            return root

        def on_start(self):
            # 1. On Android, bind back button and prompt for permissions
            if platform == "android":
                Window.bind(on_keyboard=self.on_android_back)
                # Show runtime permission dialogs early so user can grant them
                Clock.schedule_once(self.request_app_permissions, 0.5)

            # 2. Start HTTP server in a managed background thread
            srv_thread = threading.Thread(target=self._start_server_thread, daemon=True)
            srv_thread.start()

            # 3. Start waiter thread to monitor server and launch WebView
            if platform == "android":
                waiter_thread = threading.Thread(target=self._wait_and_launch_webview, daemon=True)
                waiter_thread.start()

        def on_pause(self):
            # Keep Python and HTTP server running in background
            return True

        def on_resume(self):
            pass

        def _update_status(self, text: str):
            def _set(dt):
                try:
                    if hasattr(self, 'status_label') and self.status_label:
                        self.status_label.text = text
                except Exception:
                    pass
            Clock.schedule_once(_set, 0)

        def request_app_permissions(self, *args):
            """Show native Android runtime permission prompts (storage & notifications)."""
            try:
                from android.permissions import request_permissions
                from android.runnable import run_on_ui_thread

                @run_on_ui_thread
                def _do_ask():
                    try:
                        perms = [
                            "android.permission.POST_NOTIFICATIONS",
                            "android.permission.READ_MEDIA_VIDEO",
                            "android.permission.READ_EXTERNAL_STORAGE",
                            "android.permission.WRITE_EXTERNAL_STORAGE"
                        ]
                        print(f"[Android Launcher] Requesting runtime permissions: {perms}")
                        request_permissions(perms)
                    except Exception as pe:
                        print(f"[Android Launcher] Permission prompt notice: {pe}")
                _do_ask()
            except Exception as e:
                print(f"[Android Launcher] Permissions module notice: {e}")

        def _start_server_thread(self):
            """Runs the internal HTTP server on 127.0.0.1:5824 with full exception capture."""
            try:
                from app import run_server
                run_server(host="127.0.0.1", port=5824)
            except Exception as e:
                self.server_error = str(e)
                tb = traceback.format_exc()
                print(f"[Android Launcher] HTTP server error:\n{tb}")
                self._update_status(f"Universal Downloader\nServer Error:\n{e}")

        def _wait_and_launch_webview(self):
            """Polls until server is accepting connections, then schedules WebView attach."""
            start_time = time.time()
            max_wait = 30.0
            connected = False

            while (time.time() - start_time) < max_wait:
                if self.server_error:
                    self._update_status(f"Universal Downloader\nServer Error:\n{self.server_error}")
                    return

                try:
                    with socket.create_connection(("127.0.0.1", 5824), timeout=0.5):
                        connected = True
                        break
                except (OSError, ConnectionRefusedError):
                    elapsed = int(time.time() - start_time)
                    if elapsed > 1:
                        self._update_status(f"Universal Downloader\nStarting engine... ({elapsed}s)")
                    time.sleep(0.15)

            if connected:
                self.server_ready = True
                self._update_status("Universal Downloader\nOpening interface...")
                Clock.schedule_once(self.attach_android_webview, 0)
            else:
                self._update_status("Universal Downloader\nConnection timeout.\nPlease restart the app.")

        def attach_android_webview(self, *args):
            """Creates and attaches native hardware-accelerated Android WebView on UI thread."""
            if self.webview_attached:
                return

            try:
                from jnius import autoclass
                from android.runnable import run_on_ui_thread

                @run_on_ui_thread
                def _create_and_add():
                    try:
                        PythonActivity = autoclass("org.kivy.android.PythonActivity")
                        activity = PythonActivity.mActivity
                        if not activity:
                            print("[Android Launcher] Activity not ready, retrying in 200ms...")
                            Clock.schedule_once(self.attach_android_webview, 0.2)
                            return

                        WebView = autoclass("android.webkit.WebView")
                        WebViewClient = autoclass("android.webkit.WebViewClient")
                        WebChromeClient = autoclass("android.webkit.WebChromeClient")
                        ViewGroup = autoclass("android.view.ViewGroup$LayoutParams")

                        wv = WebView(activity)
                        self.wv = wv
                        settings = wv.getSettings()
                        settings.setJavaScriptEnabled(True)
                        settings.setDomStorageEnabled(True)
                        settings.setAllowFileAccess(True)
                        settings.setAllowContentAccess(True)
                        settings.setMediaPlaybackRequiresUserGesture(False)
                        settings.setDatabaseEnabled(True)
                        settings.setUseWideViewPort(True)
                        settings.setLoadWithOverviewMode(True)

                        wv.setWebViewClient(WebViewClient())
                        wv.setWebChromeClient(WebChromeClient())

                        # Attach native WebView over the activity content
                        params = ViewGroup(-1, -1)
                        activity.addContentView(wv, params)
                        wv.bringToFront()
                        wv.requestFocus()

                        wv.loadUrl("http://127.0.0.1:5824")
                        self.webview_attached = True
                        print("[Android Launcher] Native WebView attached and loaded http://127.0.0.1:5824")
                    except Exception as err:
                        tb = traceback.format_exc()
                        print(f"[Android Launcher] WebView setup error: {err}\n{tb}")
                        self._update_status(f"Universal Downloader\nUI Error:\n{err}")

                _create_and_add()
            except Exception as e:
                print(f"[Android Launcher] attach_android_webview exception: {e}")
                self._update_status(f"Universal Downloader\nInterface Error:\n{e}")

        def on_android_back(self, window, key, *args):
            """Handle Android hardware back key (keycode 27) for in-app navigation."""
            if key == 27 and self.wv is not None:
                try:
                    from android.runnable import run_on_ui_thread
                    @run_on_ui_thread
                    def go_back():
                        try:
                            self.wv.evaluateJavascript(
                                "if (window.onAndroidBackPressed) { window.onAndroidBackPressed(); } else if (window.history.length > 1) { window.history.back(); }",
                                None
                            )
                        except Exception as e:
                            print(f"[Android Launcher] back key error: {e}")
                    go_back()
                    return True
                except Exception:
                    pass
            return False

    def main():
        if platform == "android":
            UniversalDownloaderApp().run()
        else:
            from app import main as desktop_main
            desktop_main()

except (ImportError, ModuleNotFoundError):
    # Desktop fallback when Kivy is not installed
    from app import main

if __name__ == "__main__":
    main()
