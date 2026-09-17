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
