"""Qt setup shared by pytest and standalone headless diagnostics."""

import os
from pathlib import Path
import sys


def configure_offscreen_fonts(*, platform=None, environ=None):
    """Give Windows' offscreen FreeType backend its system font directory.

    Call before QApplication construction. The native Windows backend discovers
    system fonts itself; the offscreen backend searches Qt's empty lib/fonts.
    Explicit font directories and non-Windows/native sessions are preserved.
    """
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    backend = environ.get("QT_QPA_PLATFORM", "").split(":", 1)[0]
    if platform != "win32" or backend != "offscreen":
        return
    if environ.get("QT_QPA_FONTDIR"):
        return
    root = environ.get("WINDIR") or environ.get("SystemRoot")
    if not root or not (Path(root) / "Fonts").is_dir():
        raise RuntimeError(
            "Windows offscreen tests need system fonts: Windows/Fonts was not found. "
            "Set QT_QPA_FONTDIR to an existing font directory before running pytest."
        )
    environ["QT_QPA_FONTDIR"] = str(Path(root) / "Fonts")
