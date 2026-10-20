"""Run the original failing test with compact pixel/state diagnostics.

No network download or file replacement is performed by this test. It retains
the original assertions and capture timing, without adding repaint or sleeps.
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
    from PySide6.QtWidgets import QApplication
    from mabinogi_addon.ui.update_splash import UpdateSplash

    app = QApplication.instance() or QApplication([])
    original = UpdateSplash.grab
    sequence = 0

    def capture(screen, *a, **k):
        nonlocal sequence
        pixmap = original(screen, *a, **k)
        image = pixmap.toImage()
        sequence += 1
        print("UPDATE_FRAME_DIAG " + json.dumps(dict(
            sequence=sequence, platform=sys.platform, clock=time.monotonic(),
            text=screen.msg.text(), mode=screen._mode,
            image=[image.width(), image.height()], dpr=image.devicePixelRatio(),
            geometry=[screen.x(), screen.y(), screen.width(), screen.height()],
            label=[screen.msg.x(), screen.msg.y(), screen.msg.width(), screen.msg.height()],
            font_pixels=screen.msg.font().pixelSize(), visible=screen.isVisible(),
            rendered_sha256=sha256(bytes(image.constBits())).hexdigest(),
        ), ensure_ascii=True), flush=True)
        return pixmap

    target = "tests" if args.full_suite else (
        "tests/test_manual_update_progress.py::"
        "test_manual_update_shares_layout_numbers_and_existing_success_failure_lifetime[success]"
    )
    # Plain assertions preserve the verdict without dumping full RGBA buffers.
    with patch.object(UpdateSplash, "grab", capture):
        return pytest.main([target, "-q", "-s", "-m", "not windows_integration",
                            "--assert=plain", "--tb=short", "--show-capture=no"])


if __name__ == "__main__":
    raise SystemExit(main())
