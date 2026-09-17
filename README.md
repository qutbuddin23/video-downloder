# Universal Video Downloader & Private Media Manager (Android / Python)

A high-performance, universal video downloading and private media management application built with **Python**, featuring an **Android Material 3 UI**, **Always-On-Top Floating Download Assistant**, and **AES-256 Encrypted Private Vault**.

---

## 🌟 Key Features

1. **Universal Media & Stream Sniffer (`core/detector.py`)**:
   - **Supported Platforms**: YouTube, Instagram, TikTok, Facebook, Twitter / X, Vimeo, Reddit, Dailymotion, and 1,000+ websites powered by `yt-dlp`.
   - **Deep Webpage & Hidden Stream Sniffer**: Scans HTML5 `<video>`, `<source>`, OpenGraph tags, JSON-LD, and deep regex extracts **HLS (`.m3u8`)** playlists, **MPEG-DASH (`.mpd`)** manifests, and direct video links even when hidden or not directly embedded.
   - **DRM & Access Detection**: Detects Widevine/FairPlay/ClearKey DRM streams and clearly informs the user instead of crashing.
   - **Quality & Format Selection**: Choose from 1080p, 720p, 480p, 360p, or Audio-Only (MP3/M4A), with estimated file sizes and codecs.

2. **Always-On-Top Floating Download Assistant (`core/overlay.py`)**:
   - **Desktop Testing Mode**: A borderless, draggable circular bubble that floats above other apps (Chrome, Edge, YouTube, VLC).
   - **Clipboard Auto-Detection**: Detects copied video URLs and displays a red badge count (`1`). Tapping the bubble opens instant download options.
   - **Android Overlay Mode (`android/service.py`)**: Uses Android's `SYSTEM_ALERT_WINDOW` API via PyJNIus to float over any external app.

3. **Multi-Threaded Download Manager (`core/downloader.py`)**:
   - HTTP byte-range chunked downloads with pause, resume, and cancel support.
   - Real-time download speed (MB/s), percentage (%), downloaded/total bytes, and ETA.
   - Saves temporary `.part` files to prevent corrupted partial files.

4. **AES-256 Encrypted Private Vault (`core/vault.py`)**:
   - Genuine application-level encryption using **AES-256-GCM** with PBKDF2 (100,000 iterations) key derivation from user PIN.
   - Completely removes private videos from device gallery scanners via `.nomedia` hidden directory.
   - **Storage Weight Breakdown**: Real-time breakdown of Vault storage usage, Public Downloads usage, and Free Device Storage.
   - Auto-lock timeout after inactivity.

5. **Built-In Video Player & In-App Browser (`ui/`)**:
   - Integrated HTML5 video player with gesture controls, playback speed, and fullscreen support.
   - In-app browser with a live stream sniffer button.

---

## 🚀 Quick Start (Running on Desktop / PC)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Application
```bash
python app.py
```
* On Desktop, this will launch a native mobile window (simulating an Android screen) along with the external **Floating Download Bubble**.
* You can also open your web browser at: `http://127.0.0.1:5824`

---

## 📱 Building the Android APK (via Buildozer)

### Requirements:
* Linux or WSL2 (Ubuntu 20.04/22.04 on Windows)
* Python 3.10+
* JDK 17
* Android NDK & SDK (automatically handled by Buildozer)

### Build Command:
```bash
# Install Buildozer
pip install --upgrade buildozer

# Build Debug APK
buildozer android debug
```
The compiled APK will be created inside the `bin/` directory (e.g., `UniversalDownloader-1.0.0-arm64-v8a_armeabi-v7a-debug.apk`).

### Required Android Permissions:
* `android.permission.INTERNET`: For streaming and downloading videos.
* `android.permission.SYSTEM_ALERT_WINDOW`: For the floating download button over external apps.
* `android.permission.FOREGROUND_SERVICE`: For ongoing background downloads with notifications.
* `android.permission.READ_MEDIA_VIDEO` / `WRITE_EXTERNAL_STORAGE`: For saving and reading videos in device storage.

---

## 🧪 Running Tests

Run the full automated test suite:
```bash
python -m pytest -v
```
All tests verify:
- Stream duration formatting and HTML5 media sniffing
- DRM protection detection
- Download state machine and filename sanitization
- AES-256 cryptographic roundtrip and PIN authentication
