[app]
title = Universal Downloader
package.name = universaldownloader
package.domain = org.universal
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,html,css,js,ttf,woff2,svg,json,db
version = 1.0.0

# Requirements including Python 3, yt-dlp, cryptography, and network libs
requirements = python3,requests,beautifulsoup4,yt-dlp,cryptography,pyjnius

orientation = portrait
fullscreen = 0

# Android permissions
android.permissions = INTERNET,ACCESS_NETWORK_STATE,SYSTEM_ALERT_WINDOW,FOREGROUND_SERVICE,POST_NOTIFICATIONS,WAKE_LOCK,READ_MEDIA_VIDEO,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,USE_BIOMETRIC

# Android API targeting modern Android 14 / 13 (API 33-34)
android.api = 34
android.minapi = 26
android.archs = arm64-v8a, armeabi-v7a

# Android background service declaration
services = DownloaderService:android/service.py

# Keep screen on during active downloads
android.wakelock = True

[buildozer]
log_level = 2
warn_on_root = 1
