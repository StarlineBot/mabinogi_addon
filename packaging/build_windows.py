"""사전 검증과 태그 릴리즈가 공유하는 Windows exe 빌드 명령."""

import argparse
import ast
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile


OPTIONS = shlex.split("""
--noconfirm --clean --onefile --windowed --name mabinogi-addon --uac-admin
--splash src/mabinogi_addon/assets/startup_background.png --icon packaging/logo.ico
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
--hidden-import win32con --hidden-import pyi_splash packaging/entry.py
""")


def build_command():
    """Canonical CLI settings, converted to an extended spec by build()."""
    return [sys.executable, "-m", "PyInstaller", *OPTIONS]


def extend_spec(spec: Path, root: Path) -> None:
    """Extend the generated spec locally, preserving all standard build options."""
    source = spec.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Splash"
    ]
    if len(calls) != 1:
        raise RuntimeError("PyInstaller generated splash spec contract changed")
    preamble = (
        f"import sys\nsys.path[:0] = [{str(root)!r}, {str(root / 'src')!r}]\n"
        "from scripts.startup_splash import splash_type\n"
        "from mabinogi_addon.startup_content import MESSAGES\n"
        "Splash = splash_type(Splash, messages=MESSAGES)\n"
    )
    call = calls[0]
    call.keywords = [
        keyword for keyword in call.keywords if keyword.arg != "minify_script"
    ]
    call.keywords.append(ast.keyword(arg="minify_script", value=ast.Constant(False)))
    spec.write_text(preamble + ast.unparse(tree) + "\n", encoding="utf-8")


def build(root: Path, *, blackbox_options=()) -> None:
    # Use PyInstaller's own CLI-to-spec conversion for data/hooks/UAC/version flags.
    # The only extension is our spec-local Splash subclass; no global monkeypatch.
    with tempfile.TemporaryDirectory(prefix="mabinogi-spec-") as temporary:
        options = [
            option
            for option in [*build_command()[3:-1], *blackbox_options, build_command()[-1]]
            if option not in {"--noconfirm", "--clean"}
        ]
        # Analysis resolves data sources relative to the spec directory. The spec
        # is temporary, so make every source path absolute before generating it.
        for index, option in enumerate(options[:-1]):
            if option in {"--splash", "--icon", "--version-file", "--paths"}:
                options[index + 1] = str(root / options[index + 1])
            elif option == "--add-data":
                source, destination = options[index + 1].split(";", 1)
                options[index + 1] = str(root / source) + os.pathsep + destination
        options[-1] = str(root / options[-1])
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller.utils.cliutils.makespec",
                "--specpath",
                temporary,
                *options,
            ],
            cwd=root,
            check=True,
        )
        spec = Path(temporary) / "mabinogi-addon.spec"
        extend_spec(spec, root)
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(spec)],
            cwd=root,
            check=True,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        parser.error("version must be X.Y.Z")
    if sys.platform != "win32":
        parser.error("exe verification requires Windows")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, "packaging/make_version_info.py", args.version],
        cwd=root,
        check=True,
    )
    from blackbox_bundle import prepare
    with tempfile.TemporaryDirectory(prefix="mabinogi-blackbox-") as temporary:
        extra = prepare(root, Path(temporary) / "blackbox")
        build(root, blackbox_options=extra)
    exe = root / "dist" / "mabinogi-addon.exe"
    if not exe.is_file() or exe.stat().st_size == 0:
        raise RuntimeError("PyInstaller did not produce a non-empty exe")
    print(f"Verified exe: {exe.name} ({exe.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
