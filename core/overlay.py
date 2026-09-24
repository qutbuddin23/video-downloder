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
from core.paths import is_android

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
    """Extracts any valid video or media streaming URL from raw string, rejecting static image/asset files."""
    if not text:
        return None
    raw = text.strip()
    urls = re.findall(r'https?://[^\s<>"\'`]+', raw)
    for u in urls:
        cand = u.strip(".,;:()[]{}<>\"'")
        clean = cand.split("?")[0].lower()
        if any(clean.endswith(ext) for ext in [".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".css", ".js"]):
            continue
        return cand
    return None


def get_android_sdk_level() -> int:
    """Safely retrieves Android SDK API level across all PyJNIus / Android versions."""
    try:
        import sys
        if hasattr(sys, 'getandroidapilevel'):
            return int(sys.getandroidapilevel())
    except Exception:
        pass
    try:
        from jnius import autoclass
        BuildVersion = autoclass("android.os.Build$VERSION")
        return int(BuildVersion.SDK_INT)
    except Exception:
        pass
    return 30


def get_android_clipboard_text() -> str:
    """Reads system clipboard on Android devices via PyJNIus using coerceToText."""
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
                try:
                    text = item.coerceToText(activity)
                except Exception:
                    text = item.getText()
                return str(text) if text else ""
    except Exception as e:
        print(f"[Clipboard] Android get text notice: {e}")
    return ""


def show_android_toast(message: str):
    """Displays native Android Toast notification across any active app."""
    try:
        from jnius import autoclass
        from android.runnable import run_on_ui_thread

        @run_on_ui_thread
        def _toast():
            try:
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                activity = PythonActivity.mActivity
                if activity:
                    ctx = activity.getApplicationContext() or activity
                    Toast = autoclass("android.widget.Toast")
                    String = autoclass("java.lang.String")
                    Toast.makeText(ctx, String(message), Toast.LENGTH_SHORT).show()
            except Exception as te:
                print(f"[Toast] error: {te}")
        _toast()
    except Exception:
        pass


try:
    from jnius import autoclass, PythonJavaClass, java_method
    HAS_PYJNIUS = True
except (ImportError, ModuleNotFoundError):
    HAS_PYJNIUS = False
    PythonJavaClass = object
    def java_method(sig):
        return lambda f: f


class AndroidBubbleTouchListener(PythonJavaClass):
    """Module-level touch listener for Android floating overlay view."""
    __javacontext__ = 'app'
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
        self.has_moved = False

    @java_method('(Landroid/view/View;Landroid/view/MotionEvent;)Z')
    def onTouch(self, view, event):
        try:
            from jnius import autoclass
            MotionEvent = autoclass('android.view.MotionEvent')
            action = event.getAction()
            if action == MotionEvent.ACTION_DOWN:
                self.initial_x = self.params_ref.x
                self.initial_y = self.params_ref.y
                self.initial_touch_x = event.getRawX()
                self.initial_touch_y = event.getRawY()
                self.has_moved = False
                return True
            elif action == MotionEvent.ACTION_MOVE:
                dx = int(event.getRawX() - self.initial_touch_x)
                dy = int(event.getRawY() - self.initial_touch_y)
                if abs(dx) > 10 or abs(dy) > 10:
                    self.has_moved = True
                self.params_ref.x = self.initial_x + dx
                self.params_ref.y = self.initial_y + dy
                self.wm_ref.updateViewLayout(self.view_ref, self.params_ref)
                return True
            elif action == MotionEvent.ACTION_UP:
                if not self.has_moved:
                    self.overlay_ref._on_bubble_clicked()
                return True
        except Exception as te:
            print(f"[OverlayTouch] Motion error: {te}")
        return False


class AndroidFloatingOverlay:
    """Native Android floating overlay bubble that draws over external apps."""
    def __init__(self, on_trigger_callback: Optional[Callable[[str], None]] = None):
        self.on_trigger_callback = on_trigger_callback
        self.is_active = False
        self.floating_view = None
        self.window_manager = None
        self.last_clipboard = ""
        self._touch_listener = None

    @staticmethod
    def can_draw_overlays() -> bool:
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            if not activity:
                return False
            Settings = autoclass("android.provider.Settings")
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
                    if not activity:
                        return
                    Intent = autoclass("android.content.Intent")
                    Uri = autoclass("android.net.Uri")
                    Settings = autoclass("android.provider.Settings")
                    pkg = str(activity.getPackageName())
                    
                    try:
                        intent = Intent(
                            Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                            Uri.parse(f"package:{pkg}")
                        )
                        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        activity.startActivity(intent)
                        return
                    except Exception as e1:
                        print(f"[Overlay] Package intent fallback: {e1}")

                    intent = Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION)
                    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
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
            from jnius import autoclass
            from android.runnable import run_on_ui_thread

            @run_on_ui_thread
            def _mount_floating_view():
                try:
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    activity = PythonActivity.mActivity
                    if not activity:
                        print("[Overlay] PythonActivity.mActivity not available yet.")
                        return

                    Context = autoclass("android.content.Context")
                    WindowManager = autoclass("android.view.WindowManager")
                    LayoutParams = autoclass("android.view.WindowManager$LayoutParams")
                    PixelFormat = autoclass("android.graphics.PixelFormat")
                    Gravity = autoclass("android.view.Gravity")
                    TextView = autoclass("android.widget.TextView")
                    Color = autoclass("android.graphics.Color")
                    GradientDrawable = autoclass("android.graphics.drawable.GradientDrawable")

                    # Use Application Context or Activity WindowManager
                    app_context = activity.getApplicationContext()
                    try:
                        wm = app_context.getSystemService(Context.WINDOW_SERVICE)
                    except Exception:
                        wm = activity.getSystemService(Context.WINDOW_SERVICE)
                    self.window_manager = wm

                    # In Android 8.0+ (API 26+), must use TYPE_APPLICATION_OVERLAY (2038)
                    layout_type = 2038 if get_android_sdk_level() >= 26 else 2002
                    # FLAG_NOT_FOCUSABLE (8) | FLAG_LAYOUT_IN_SCREEN (256)
                    flags = 8 | 256

                    params = LayoutParams(
                        int(170), int(170),
                        int(layout_type),
                        int(flags),
                        int(PixelFormat.TRANSLUCENT)
                    )
                    params.gravity = Gravity.TOP | Gravity.START
                    params.x = 24
                    params.y = 450

                    # Remove existing view if already mounted
                    if self.floating_view:
                        try:
                            wm.removeView(self.floating_view)
                        except Exception:
                            pass
                        self.floating_view = None

                    btn = TextView(activity)
                    try:
                        String = autoclass("java.lang.String")
                        from jnius import cast
                        btn.setText(cast("java.lang.CharSequence", String("⚡")))
                    except Exception as te:
                        print(f"[Overlay] setText CharSequence notice: {te}")
                        try:
                            btn.setText(String("⚡"))
                        except Exception:
                            pass
                    try:
                        btn.setTextSize(24.0)
                    except Exception:
                        pass
                    try:
                        btn.setGravity(Gravity.CENTER)
                        btn.setTextColor(Color.WHITE)
                    except Exception:
                        pass
                    try:
                        btn.setClickable(True)
                    except Exception:
                        pass

                    try:
                        shape = GradientDrawable()
                        shape.setShape(GradientDrawable.OVAL)
                        shape.setColor(Color.parseColor("#6366F1"))
                        shape.setStroke(4, Color.parseColor("#818CF8"))
                        btn.setBackground(shape)
                    except Exception as se:
                        print(f"[Overlay] Background shape notice: {se}")


                    try:
                        self._touch_listener = AndroidBubbleTouchListener(self, wm, params, btn)
                        btn.setOnTouchListener(self._touch_listener)
                    except Exception as tle:
                        print(f"[Overlay] TouchListener setup notice: {tle}")

                    wm.addView(btn, params)
                    self.floating_view = btn
                    self.is_active = True
                    print("[Overlay] Android Floating Button successfully mounted!")
                    show_android_toast("⚡ Floating Bubble Active! Drag it anywhere on screen.")
                except Exception as e:
                    print(f"[Overlay] Failed to mount Android floating button: {e}")
                    show_android_toast(f"Overlay notice: {e}")

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
        # Handle click asynchronously so the Android UI thread is never blocked
        threading.Thread(target=self._handle_bubble_click_async, daemon=True).start()

    def _handle_bubble_click_async(self):
        # 1. Bring activity to front so app acquires input focus for Android 10+ clipboard access
        try:
            from jnius import autoclass
            from android.runnable import run_on_ui_thread

            @run_on_ui_thread
            def _bring_forward():
                try:
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    activity = PythonActivity.mActivity
                    if activity:
                        Intent = autoclass("android.content.Intent")
                        intent = Intent(activity, activity.getClass())
                        intent.setFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT | Intent.FLAG_ACTIVITY_SINGLE_TOP)
                        activity.startActivity(intent)
                except Exception as fe:
                    print(f"[Overlay] Focus notice: {fe}")
            _bring_forward()
        except Exception:
            pass

        # Give Android 300ms to bring activity to front and grant clipboard access
        time.sleep(0.35)

        # 2. Read clipboard (check both freshly read text and last_clipboard)
        clip_text = get_android_clipboard_text()
        video_url = detect_video_url(clip_text) or detect_video_url(getattr(self, "last_clipboard", ""))
        if video_url:
            show_android_toast("⚡ Video Detected! Starting Auto-Download...")
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
    return is_android()


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


