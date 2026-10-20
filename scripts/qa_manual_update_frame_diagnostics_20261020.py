"""Run the original failing test with compact pixel/state diagnostics.

No network download or file replacement is performed by this test. It retains
the five distinct-frame requirement; compares native grab with controlled Qt
rendering without adding repaint or sleeps.
Use --full-suite only to investigate order-dependent state across the suite.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "tests")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-suite", action="store_true")
    args = parser.parse_args()
    import pytest
    from PySide6.QtGui import QFontInfo, QRawFont
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    import test_manual_update_progress as regression

    original = regression.render_frame
    sequence = 0

    def capture(screen):
        nonlocal sequence
        native = screen.grab().toImage()
        image = original(screen)
        sequence += 1
        print("UPDATE_FRAME_DIAG " + json.dumps(dict(
            sequence=sequence, platform=sys.platform, clock=time.monotonic(),
            text=screen.msg.text(), mode=screen._mode,
            image=[image.width(), image.height()], dpr=image.devicePixelRatio(),
            geometry=[screen.x(), screen.y(), screen.width(), screen.height()],
            label=[screen.msg.x(), screen.msg.y(), screen.msg.width(), screen.msg.height()],
            font_pixels=screen.msg.font().pixelSize(), visible=screen.isVisible(),
            resolved_font=QFontInfo(screen.msg.font()).family(),
            digit_glyphs=[QRawFont.fromFont(screen.msg.font()).supportsCharacter(ord(c))
                          for c in "01379"],
            rendered_sha256=sha256(bytes(image.constBits())).hexdigest(),
            native_grab_sha256=sha256(bytes(native.constBits())).hexdigest(),
            native_size=[native.width(), native.height()],
            native_dpr=native.devicePixelRatio(),
            render_format=image.format().name, native_format=native.format().name,
        ), ensure_ascii=True), flush=True)
        return image

    target = "tests" if args.full_suite else (
        "tests/test_manual_update_progress.py::"
        "test_manual_update_shares_layout_numbers_and_existing_success_failure_lifetime[success]"
    )
    # Plain assertions preserve the verdict without dumping full RGBA buffers.
    with patch.object(regression, "render_frame", capture):
        return pytest.main([target, "-q", "-s", "-m", "not windows_integration",
                            "--assert=plain", "--tb=short", "--show-capture=no"])


if __name__ == "__main__":
    raise SystemExit(main())
