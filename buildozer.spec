[app]
title = Universal Downloader
package.name = universaldownloader
package.domain = org.universal
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,html,css,js,ttf,woff2,svg,json,db
version = 1.0.0

# Requirements: pure python libs + kivy & pyjnius
requirements = python3,kivy,requests,beautifulsoup4,yt-dlp,pyjnius,pyaes

orientation = portrait
fullscreen = 0

# Android permissions
android.permissions = INTERNET,ACCESS_NETWORK_STATE,SYSTEM_ALERT_WINDOW,FOREGROUND_SERVICE,POST_NOTIFICATIONS,WAKE_LOCK,READ_MEDIA_VIDEO,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,USE_BIOMETRIC

# Targets arm64-v8a only for 2x faster build speed and modern device compatibility
android.archs = arm64-v8a
android.api = 33
android.minapi = 26
android.ndk = 25b

# Background service with lowercase name
services = downloader:service.py

android.wakelock = True

[buildozer]
log_level = 2
warn_on_root = 1
