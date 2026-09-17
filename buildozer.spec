[app]
title = Universal Downloader
package.name = videomanager
package.domain = com.qutbuddin
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,html,css,js,ttf,woff2,svg,json,db
version = 1.0.0

# Requirements: pure python libs + kivy & pyjnius
requirements = python3,kivy,requests,beautifulsoup4,yt-dlp,pyjnius,pyaes

orientation = portrait
fullscreen = 0

# Clean permissions for modern Android (avoids Play Protect storage alarms)
android.permissions = INTERNET,ACCESS_NETWORK_STATE,SYSTEM_ALERT_WINDOW,FOREGROUND_SERVICE,POST_NOTIFICATIONS,WAKE_LOCK,READ_MEDIA_VIDEO

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
