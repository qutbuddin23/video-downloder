"""
Floating Download Assistant for Universal Video Downloader.
Provides an Always-On-Top floating bubble that operates outside the main application,
allowing users to drag it over any browser or app, monitor the clipboard for video links,
and trigger instant downloads.
"""

import sys
import time
import threading
from typing import Optional, Callable
import re

try:
    import tkinter as tk
    TKINTER_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    tk = None
    TKINTER_AVAILABLE = False

VIDEO_URL_PATTERN = re.compile(
    r'(https?://[^\s]+(?:youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch|twitter\.com|x\.com|vimeo\.com|dailymotion\.com|reddit\.com|[^\s]+\.(?:mp4|m3u8|webm|mpd|mov)))',
    re.IGNORECASE
)


class DesktopFloatingOverlay:
    def __init__(self, on_trigger_callback: Optional[Callable[[str], None]] = None):
        self.on_trigger_callback = on_trigger_callback
        self.root: Optional[tk.Tk] = None
        self.is_active = False
        self.last_clipboard = ""
        self.detected_url = ""
        self.drag_x = 0
        self.drag_y = 0

    def start(self):
        if not TKINTER_AVAILABLE:
            print("Desktop floating overlay not supported on mobile/Android (using native service).")
            return
        if self.is_active:
            return
        self.is_active = True
        thread = threading.Thread(target=self._run_ui, daemon=True)
        thread.start()

        # Start clipboard monitor thread
        clip_thread = threading.Thread(target=self._clipboard_loop, daemon=True)
        clip_thread.start()

    def stop(self):
        self.is_active = False
        if self.root:
            try:
                self.root.quit()
                self.root.destroy()
            except Exception:
                pass
            self.root = None

    def _run_ui(self):
        self.root = tk.Tk()
        self.root.title("Floating Downloader")
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.config(bg="#1E1E2E")

        # Circular dimension
        size = 64
        # Position at right side of screen
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        start_x = screen_w - size - 20
        start_y = screen_h // 2 - size // 2

        self.root.geometry(f"{size}x{size}+{start_x}+{start_y}")

        # Canvas for rounded bubble effect
        canvas = tk.Canvas(self.root, width=size, height=size, bg="#1E1E2E", highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        # Draw circle button
        canvas.create_oval(4, 4, size-4, size-4, fill="#6366F1", outline="#818CF8", width=2)
        # Download arrow icon
        canvas.create_line(size//2, 18, size//2, 38, fill="#FFFFFF", width=3)
        canvas.create_line(size//2 - 8, 30, size//2, 38, fill="#FFFFFF", width=3)
        canvas.create_line(size//2 + 8, 30, size//2, 38, fill="#FFFFFF", width=3)
        canvas.create_line(size//2 - 12, 44, size//2 + 12, 44, fill="#FFFFFF", width=3)

        # Badge counter
        self.badge_id = canvas.create_oval(size-22, 2, size-2, 22, fill="#EF4444", outline="#FFFFFF", width=1, state="hidden")
        self.badge_text_id = canvas.create_text(size-12, 12, text="1", fill="#FFFFFF", font=("Arial", 9, "bold"), state="hidden")

        self.canvas = canvas

        # Mouse Drag handlers
        self.root.bind("<Button-1>", self._on_drag_start)
        self.root.bind("<B1-Motion>", self._on_drag_motion)
        self.root.bind("<ButtonRelease-1>", self._on_click_or_drop)

        self.root.mainloop()

    def _on_drag_start(self, event):
        self.drag_x = event.x
        self.drag_y = event.y
        self.has_dragged = False

    def _on_drag_motion(self, event):
        self.has_dragged = True
        deltax = event.x - self.drag_x
        deltay = event.y - self.drag_y
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")

    def _on_click_or_drop(self, event):
        if not getattr(self, "has_dragged", False):
            # Normal tap/click on floating button
            self._show_quick_download_popup()
            if self.on_trigger_callback:
                self.on_trigger_callback(self.detected_url)
            # Hide badge
            self._set_badge(False)

    def _show_quick_download_popup(self):
        if not self.root:
            return
        # Create small overlay popup near the button
        popup = tk.Toplevel(self.root)
        popup.title("Quick Video Download")
        popup.wm_attributes("-topmost", True)
        popup.overrideredirect(True)
        popup.config(bg="#1E293B", padx=14, pady=14)

        x = max(10, self.root.winfo_x() - 260)
        y = max(10, self.root.winfo_y() - 40)
        popup.geometry(f"280x160+{x}+{y}")

        # Title
        lbl = tk.Label(popup, text="⚡ Video Downloader Assistant", fg="#818CF8", bg="#1E293B", font=("Segoe UI", 10, "bold"))
        lbl.pack(anchor="w", pady=(0, 6))

        # Show detected URL or prompt
        url_to_show = self.detected_url or ""
        if not url_to_show:
            try:
                clip = self.root.clipboard_get()
                if clip and ("http://" in clip or "https://" in clip):
                    url_to_show = clip
                    self.detected_url = clip
            except Exception:
                pass

        status_text = "Video Detected from Clipboard!" if url_to_show else "No video in clipboard yet."
        lbl_status = tk.Label(popup, text=status_text, fg="#F8FAFC", bg="#1E293B", font=("Segoe UI", 9))
        lbl_status.pack(anchor="w", pady=(0, 4))

        # URL Entry / preview
        entry = tk.Entry(popup, bg="#334155", fg="#FFFFFF", insertbackground="#FFFFFF", font=("Segoe UI", 9))
        entry.pack(fill="x", pady=(0, 10))
        if url_to_show:
            entry.insert(0, url_to_show)
        else:
            entry.insert(0, "Paste video link here...")

        btn_frame = tk.Frame(popup, bg="#1E293B")
        btn_frame.pack(fill="x")

        def on_download_now():
            target_url = entry.get().strip()
            if target_url and target_url != "Paste video link here...":
                self.detected_url = target_url
                if self.on_trigger_callback:
                    self.on_trigger_callback(target_url)
            popup.destroy()

        btn_dl = tk.Button(btn_frame, text="⬇ Analyze & Download", bg="#6366F1", fg="#FFFFFF", font=("Segoe UI", 9, "bold"),
                           relief="flat", cursor="hand2", command=on_download_now, padx=10, pady=5)
        btn_dl.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_close = tk.Button(btn_frame, text="✕", bg="#475569", fg="#FFFFFF", font=("Segoe UI", 9),
                             relief="flat", cursor="hand2", command=popup.destroy, padx=8, pady=5)
        btn_close.pack(side="right")

    def _set_badge(self, visible: bool):
        if hasattr(self, "canvas") and self.root:
            try:
                state = "normal" if visible else "hidden"
                self.canvas.itemconfigure(self.badge_id, state=state)
                self.canvas.itemconfigure(self.badge_text_id, state=state)
            except Exception:
                pass

    def _clipboard_loop(self):
        while self.is_active:
            try:
                if self.root:
                    clip_text = self.root.clipboard_get()
                    if clip_text and clip_text != self.last_clipboard:
                        self.last_clipboard = clip_text
                        match = VIDEO_URL_PATTERN.search(clip_text)
                        if match:
                            self.detected_url = match.group(1)
                            self._set_badge(True)
            except Exception:
                pass
            time.sleep(1.5)


def detect_video_url(text: str) -> Optional[str]:
    """Extracts a valid video or media streaming URL from raw string."""
    if not text:
        return None
    match = VIDEO_URL_PATTERN.search(text.strip())
    if match:
        return match.group(1).strip()
    return None


def get_android_clipboard_text() -> str:
    """Reads system clipboard on Android devices via PyJNIus."""
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        if activity:
            Context = autoclass("android.content.Context")
            clipboard = activity.getSystemService(Context.CLIPBOARD_SERVICE)
            clip = clipboard.getPrimaryClip()
            if clip and clip.getItemCount() > 0:
                item = clip.getItemAt(0)
                text = item.getText()
                return str(text) if text else ""
    except Exception as e:
        print(f"[Clipboard] Android get text notice: {e}")
    return ""


def show_android_toast(message: str):
    """Displays native Android Toast notification."""
    try:
        from jnius import autoclass
        from android.runnable import run_on_ui_thread

        @run_on_ui_thread
        def _toast():
            try:
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                activity = PythonActivity.mActivity
                Toast = autoclass("android.widget.Toast")
                String = autoclass("java.lang.String")
                if activity:
                    Toast.makeText(activity, String(message), Toast.LENGTH_SHORT).show()
            except Exception as te:
                print(f"[Toast] error: {te}")
        _toast()
    except Exception:
        pass


class AndroidFloatingOverlay:
    """Native Android floating overlay bubble that draws over external apps."""
    def __init__(self, on_trigger_callback: Optional[Callable[[str], None]] = None):
        self.on_trigger_callback = on_trigger_callback
        self.is_active = False
        self.floating_view = None
        self.window_manager = None
        self.last_clipboard = ""

    @staticmethod
    def can_draw_overlays() -> bool:
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            Settings = autoclass("android.provider.Settings")
            if activity:
                return bool(Settings.canDrawOverlays(activity))
        except Exception as e:
            print(f"[Overlay] can_draw_overlays check: {e}")
        return False

    @staticmethod
    def open_overlay_settings() -> bool:
        try:
            from jnius import autoclass
            from android.runnable import run_on_ui_thread

            @run_on_ui_thread
            def _open():
                try:
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    activity = PythonActivity.mActivity
                    if activity:
                        Intent = autoclass("android.content.Intent")
                        Uri = autoclass("android.net.Uri")
                        Settings = autoclass("android.provider.Settings")
                        intent = Intent(
                            Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                            Uri.parse("package:" + activity.getPackageName())
                        )
                        activity.startActivity(intent)
                except Exception as e:
                    print(f"[Overlay] open settings error: {e}")
            _open()
            return True
        except Exception as e:
            print(f"[Overlay] open_overlay_settings notice: {e}")
            return False

    def start(self):
        if self.is_active:
            return
        if not self.can_draw_overlays():
            print("[Overlay] Cannot start Android overlay: overlay permission not granted.")
            return

        try:
            from jnius import autoclass, PythonJavaClass, java_method
            from android.runnable import run_on_ui_thread

            @run_on_ui_thread
            def _mount_floating_view():
                try:
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    activity = PythonActivity.mActivity
                    if not activity:
                        return

                    app_context = activity.getApplicationContext()
                    Context = autoclass("android.content.Context")
                    WindowManager = autoclass("android.view.WindowManager")
                    LayoutParams = autoclass("android.view.WindowManager$LayoutParams")
                    PixelFormat = autoclass("android.graphics.PixelFormat")
                    Gravity = autoclass("android.view.Gravity")
                    Button = autoclass("android.widget.Button")
                    Color = autoclass("android.graphics.Color")
                    GradientDrawable = autoclass("android.graphics.drawable.GradientDrawable")

                    wm = app_context.getSystemService(Context.WINDOW_SERVICE)
                    self.window_manager = wm

                    flags = LayoutParams.FLAG_NOT_FOCUSABLE | LayoutParams.FLAG_LAYOUT_IN_SCREEN
                    params = LayoutParams(
                        160, 160,
                        LayoutParams.TYPE_APPLICATION_OVERLAY,
                        flags,
                        PixelFormat.TRANSLUCENT
                    )
                    params.gravity = Gravity.TOP | Gravity.START
                    params.x = 24
                    params.y = 450

                    btn = Button(app_context)
                    btn.setText("⚡")
                    btn.setTextSize(26)
                    btn.setTextColor(Color.WHITE)

                    shape = GradientDrawable()
                    shape.setShape(GradientDrawable.OVAL)
                    shape.setColor(Color.parseColor("#6366F1"))
                    shape.setStroke(4, Color.parseColor("#818CF8"))
                    btn.setBackground(shape)

                    class BubbleTouchListener(PythonJavaClass):
                        __javainterfaces__ = ['android/view/View$OnTouchListener']
                        def __init__(self, overlay_ref, wm_ref, params_ref, view_ref):
                            super().__init__()
                            self.overlay_ref = overlay_ref
                            self.wm_ref = wm_ref
                            self.params_ref = params_ref
                            self.view_ref = view_ref
                            self.initial_x = 0
                            self.initial_y = 0
                            self.initial_touch_x = 0.0
                            self.initial_touch_y = 0.0
                            self.is_click = False

                        @java_method('(Landroid/view/View;Landroid/view/MotionEvent;)Z')
                        def onTouch(self, view, event):
                            try:
                                MotionEvent = autoclass('android.view.MotionEvent')
                                action = event.getAction()
                                if action == MotionEvent.ACTION_DOWN:
                                    self.initial_x = self.params_ref.x
                                    self.initial_y = self.params_ref.y
                                    self.initial_touch_x = event.getRawX()
                                    self.initial_touch_y = event.getRawY()
                                    self.is_click = True
                                    return True
                                elif action == MotionEvent.ACTION_MOVE:
                                    dx = int(event.getRawX() - self.initial_touch_x)
                                    dy = int(event.getRawY() - self.initial_touch_y)
                                    if abs(dx) > 12 or abs(dy) > 12:
                                        self.is_click = False
                                    self.params_ref.x = self.initial_x + dx
                                    self.params_ref.y = self.initial_y + dy
                                    self.wm_ref.updateViewLayout(self.view_ref, self.params_ref)
                                    return True
                                elif action == MotionEvent.ACTION_UP:
                                    if self.is_click:
                                        self.overlay_ref._on_bubble_clicked()
                                    return True
                            except Exception as te:
                                print(f"[OverlayTouch] Motion error: {te}")
                            return False

                    self._touch_listener = BubbleTouchListener(self, wm, params, btn)
                    btn.setOnTouchListener(self._touch_listener)

                    wm.addView(btn, params)
                    self.floating_view = btn
                    self.is_active = True
                    print("[Overlay] Android Floating Button successfully mounted via ApplicationContext!")
                    show_android_toast("⚡ Floating Bubble Active! Drag it anywhere on screen.")
                except Exception as e:
                    print(f"[Overlay] Failed to mount Android floating button: {e}")

            _mount_floating_view()
            threading.Thread(target=self._clipboard_monitor_loop, daemon=True).start()
        except Exception as e:
            print(f"[Overlay] Android overlay start error: {e}")

    def show_or_request_permission(self):
        if not self.can_draw_overlays():
            self.open_overlay_settings()
            return {"active": False, "needs_permission": True, "message": "Opening Android Settings... Please enable 'Display over other apps'."}
        self.start()
        return {"active": True, "needs_permission": False, "message": "⚡ Floating Bubble is now active on your screen! Drag it anywhere."}

    def _on_bubble_clicked(self):
        clip_text = get_android_clipboard_text()
        video_url = detect_video_url(clip_text)
        if video_url:
            show_android_toast("⚡ Auto-Downloading detected video...")
            if self.on_trigger_callback:
                self.on_trigger_callback(video_url)
        else:
            show_android_toast("Universal Downloader: Copy a video link first, then tap ⚡")

    def _clipboard_monitor_loop(self):
        while self.is_active:
            try:
                clip_text = get_android_clipboard_text()
                if clip_text and clip_text != self.last_clipboard:
                    self.last_clipboard = clip_text
                    video_url = detect_video_url(clip_text)
                    if video_url:
                        show_android_toast("🎬 Video Link Copied! Tap ⚡ to download.")
            except Exception:
                pass
            time.sleep(2.0)

    def stop(self):
        self.is_active = False
        if self.floating_view and self.window_manager:
            try:
                from android.runnable import run_on_ui_thread
                @run_on_ui_thread
                def _remove():
                    try:
                        self.window_manager.removeView(self.floating_view)
                    except Exception:
                        pass
                    self.floating_view = None
                _remove()
            except Exception:
                pass


def is_running_on_android() -> bool:
    import os
    return "ANDROID_ARGUMENT" in os.environ or "ANDROID_PRIVATE" in os.environ or os.path.exists("/system/build.prop")


class FloatingOverlayManager:
    """Unified cross-platform floating assistant manager."""
    def __init__(self, on_trigger_callback: Optional[Callable[[str], None]] = None):
        self.on_trigger_callback = on_trigger_callback
        if is_running_on_android():
            self.overlay = AndroidFloatingOverlay(on_trigger_callback=on_trigger_callback)
        else:
            self.overlay = DesktopFloatingOverlay(on_trigger_callback=on_trigger_callback)

    def start(self):
        return self.overlay.start()

    def stop(self):
        return self.overlay.stop()

    def is_active(self) -> bool:
        return getattr(self.overlay, "is_active", False)

    def can_draw_overlays(self) -> bool:
        if hasattr(self.overlay, "can_draw_overlays"):
            return self.overlay.can_draw_overlays()
        return True

    def open_overlay_settings(self) -> bool:
        if hasattr(self.overlay, "open_overlay_settings"):
            return self.overlay.open_overlay_settings()
        return True

    def show_or_request_permission(self):
        if hasattr(self.overlay, "show_or_request_permission"):
            return self.overlay.show_or_request_permission()
        self.start()
        return {"active": self.is_active(), "needs_permission": False, "message": "Floating assistant active."}


