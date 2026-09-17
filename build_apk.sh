#!/bin/bash
# Local APK Builder Script (Ubuntu / Debian / WSL)
set -e

echo "=== Installing Prerequisites for Android APK Compilation ==="
sudo apt update
sudo apt install -y git zip unzip autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev openjdk-17-jdk python3-pip

echo "=== Installing Buildozer & Cython ==="
pip3 install --upgrade pip
pip3 install --upgrade buildozer Cython==0.29.36

echo "=== Compiling Android APK ==="
buildozer -v android debug

echo "=== APK Compilation Complete! ==="
echo "Your APK is located in: bin/"
ls -la bin/*.apk
