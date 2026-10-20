"""Manual updater must retain observable download progress after splash changes.

Run: QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest
     scripts/qa_startup_manual_update_progress_20261020.py -q -s
Current source fails: real progress callbacks produce identical rendered screens.
No download, update application, live capture or real MainWindow is started.
"""

from hashlib import sha256
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from PySide6.QtWidgets import QApplication, QProgressBar
from mabinogi_addon.ui.main_window import MainWindow
from mabinogi_addon.ui.splash import Splash


def test_manual_update_download_progress_remains_visible():
    app = QApplication.instance() or QApplication([])
    screen = Splash()
    owner = SimpleNamespace(_update_splash=screen)
    frames = []
    screen.show()
    try:
        for pct in (10, 90):
            MainWindow._on_update_progress(owner, pct)
            app.processEvents()
            image = screen.grab().toImage()
            frame = bytes(image.constBits())
            frames.append(frame)
            print(dict(percent=pct, text=screen.msg.text(),
                       progress_bars=len(screen.findChildren(QProgressBar)),
                       rendered_sha256=sha256(frame).hexdigest()))
        assert frames[0] != frames[1], (
            "Manual update's 10% and 90% screens are identical: the shared Splash "
            "removed the progress bar and ignores pct, while this caller sends "
            "the same status text without the percentage."
        )
    finally:
        screen.close()
        assert not screen._timer.isActive()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q", "-s", "--tb=short"]))
