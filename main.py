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
            self.webview_attached = False
            self.status_label = None

            # 1. Start background standard library HTTP server with error protection
            try:
                from app import run_server
                server_thread = threading.Thread(target=run_server, daemon=True)
                server_thread.start()
            except Exception as srv_err:
                print(f"[Android Launcher] Server start error: {srv_err}")

            # 2. On Android, schedule background waiter and handle back button
            if platform == "android":
                Window.bind(on_keyboard=self.on_android_back)
                threading.Thread(target=self._launch_android_webview_flow, daemon=True).start()

            from kivy.uix.boxlayout import BoxLayout
            from kivy.uix.label import Label
            root = BoxLayout(orientation='vertical')
            self.status_label = Label(
                text="⚡ Universal Downloader\nLoading media engine...",
                font_size='18sp',
                halign='center',
                color=(0.9, 0.9, 1.0, 1.0)
            )
            root.add_widget(self.status_label)
            return root

        def on_pause(self):
            # CRITICAL: Prevent Kivy from exiting when WebView takes focus or activity is paused
            return True

        def on_resume(self):
            pass

        def wait_for_server(self, host="127.0.0.1", port=5824, timeout=12.0):
            """Verify that the HTTP server is accepting connections (runs on background thread)."""
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    with socket.create_connection((host, port), timeout=0.5):
                        return True
                except (OSError, ConnectionRefusedError):
                    time.sleep(0.15)
            return False

        def _update_status(self, text: str):
            try:
                if self.status_label:
                    self.status_label.text = text
            except Exception:
                pass

        def _launch_android_webview_flow(self):
            """Background worker thread: requests permissions, waits for server, then posts WebView to UI thread."""
            try:
                # 1. Request permissions on Android UI thread
                try:
                    from android.permissions import request_permissions
                    from android.runnable import run_on_ui_thread

                    @run_on_ui_thread
                    def ask_permissions():
                        try:
                            request_permissions([
                                "android.permission.POST_NOTIFICATIONS",
                                "android.permission.READ_MEDIA_VIDEO"
                            ])
                        except Exception as p_err:
                            print(f"[Android Launcher] Permission prompt note: {p_err}")

                    ask_permissions()
                except Exception as perm_err:
                    print(f"[Android Launcher] Permission setup note: {perm_err}")

                # 2. Wait for background HTTP server to bind
                server_ok = self.wait_for_server(timeout=12.0)
                if not server_ok:
                    print("[Android Launcher] Server wait timed out, attempting WebView load anyway")
                else:
                    print("[Android Launcher] HTTP server verified on 127.0.0.1:5824")

                time.sleep(0.2)

                # 3. Post WebView creation and attachment to Android UI Thread
                self._attach_android_webview()
            except Exception as e:
                print(f"[Android Launcher] Launch flow error: {e}")

        def _attach_android_webview(self):
            try:
                from jnius import autoclass
                from android.runnable import run_on_ui_thread

                @run_on_ui_thread
                def setup_webview_on_main():
                    if self.webview_attached:
                        return

                    try:
                        PythonActivity = autoclass("org.kivy.android.PythonActivity")
                        activity = PythonActivity.mActivity
                        if not activity:
                            print("[Android Launcher] PythonActivity.mActivity not ready yet, retrying...")
                            Clock.schedule_once(lambda dt: self._attach_android_webview(), 0.3)
                            return

                        self.webview_attached = True

                        WebView = autoclass("android.webkit.WebView")
                        WebViewClient = autoclass("android.webkit.WebViewClient")
                        WebChromeClient = autoclass("android.webkit.WebChromeClient")
                        LayoutParams = autoclass("android.view.ViewGroup$LayoutParams")

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

                        # CRITICAL: Use addContentView instead of setContentView!
                        # setContentView detaches SDLSurface from Kivy, causing eglSwapBuffers SIGSEGV.
                        # addContentView layers the WebView on top without disturbing SDL2.
                        params = LayoutParams(-1, -1)  # -1 = MATCH_PARENT
                        activity.addContentView(wv, params)
                        wv.loadUrl("http://127.0.0.1:5824")
                        print("[Android Launcher] Native WebView successfully loaded http://127.0.0.1:5824")
                    except Exception as err:
                        print(f"[Android Launcher] setup_webview_on_main exception: {err}")
                        Clock.schedule_once(lambda dt: self._update_status(f"Starting interface...\n({err})"), 0)

                setup_webview_on_main()
            except Exception as e:
                print(f"[Android Launcher] _attach_android_webview error: {e}")

        def on_android_back(self, window, key, *args):
            """Handle Android back key (keycode 27) in WebView navigation."""
            if key == 27 and self.wv is not None:
                try:
                    from android.runnable import run_on_ui_thread
                    @run_on_ui_thread
                    def go_back_or_exit():
                        try:
                            self.wv.evaluateJavascript(
                                "if (window.onAndroidBackPressed) { window.onAndroidBackPressed(); } else if (window.history.length > 1) { window.history.back(); }",
                                None
                            )
                        except Exception as e:
                            print(f"[Android Launcher] back handler error: {e}")
                    go_back_or_exit()
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
