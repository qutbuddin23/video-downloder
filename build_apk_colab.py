# Google Colab 1-Click Android APK Builder
# Open https://colab.research.google.com and run this script in a single code block!

"""
# Step 1: Install Buildozer and system dependencies
!apt update
!apt install -y git zip unzip autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev openjdk-17-jdk
!pip install --upgrade pip
!pip install --upgrade buildozer Cython==0.29.36

# Step 2: Upload or Clone your app directory here
# (If uploading zip: !unzip dowloader.zip -d dowloader && cd dowloader)

# Step 3: Run Buildozer to compile APK
!yes | buildozer -v android debug

# Step 4: Download compiled APK directly to your computer!
from google.colab import files
import glob

apk_files = glob.glob("bin/*.apk")
if apk_files:
    print(f"Downloading APK: {apk_files[0]}")
    files.download(apk_files[0])
else:
    print("APK build failed or output not found.")
"""
