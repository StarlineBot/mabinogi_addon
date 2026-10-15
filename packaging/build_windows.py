"""사전 검증과 태그 릴리즈가 공유하는 Windows exe 빌드 명령."""

import argparse
from pathlib import Path
import re
import shlex
import subprocess
import sys


OPTIONS = shlex.split('''
--noconfirm --clean --onefile --windowed --name mabinogi-addon --uac-admin
--splash packaging/splash.png --icon packaging/logo.ico
--version-file packaging/version_info.txt --paths src
--add-data "src/mabinogi_addon/assets;assets"
--add-data "src/mabinogi_addon/detect/templates;mabinogi_addon/detect/templates"
--collect-all dxcam --collect-all comtypes --collect-data certifi
--exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets
--exclude-module PySide6.QtWebEngineQuick --exclude-module PySide6.QtQuick
--exclude-module PySide6.QtQuick3D --exclude-module PySide6.QtQml
--exclude-module PySide6.Qt3DCore --exclude-module PySide6.Qt3DRender
--exclude-module PySide6.QtCharts --exclude-module PySide6.QtDataVisualization
--exclude-module PySide6.QtPdf --exclude-module PySide6.QtPdfWidgets
--exclude-module PySide6.QtWebChannel --exclude-module PySide6.QtWebSockets
--exclude-module PySide6.QtDesigner --exclude-module PySide6.QtQuickWidgets
--exclude-module PySide6.QtQuickControls2
--hidden-import win32gui --hidden-import win32ui --hidden-import win32process
--hidden-import win32con packaging/entry.py
''')


def build_command():
    return [sys.executable, "-m", "PyInstaller", *OPTIONS]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        parser.error("version must be X.Y.Z")
    if sys.platform != "win32":
        parser.error("exe verification requires Windows")
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, "packaging/make_version_info.py", args.version], cwd=root, check=True)
    subprocess.run(build_command(), cwd=root, check=True)
    exe = root / "dist" / "mabinogi-addon.exe"
    if not exe.is_file() or exe.stat().st_size == 0:
        raise RuntimeError("PyInstaller did not produce a non-empty exe")
    print(f"Verified exe: {exe.name} ({exe.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
