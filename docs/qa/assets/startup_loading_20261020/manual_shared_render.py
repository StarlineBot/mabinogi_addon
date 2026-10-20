"""Render the real manual-update entry with download/thread boundaries replaced.

QT_QPA_PLATFORM=offscreen python docs/qa/assets/startup_loading_20261020/manual_shared_render.py
Set QT_SCALE_FACTOR=1.5 or 2 to inspect Linux DPI scaling; no real update runs.
"""

from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox
from mabinogi_addon.ui.main_window import MainWindow


class Owner(QObject):
    _update_progress = Signal(int)
    _update_result = Signal(bool, str)
    _on_update_progress = MainWindow._on_update_progress
    _on_update_result = MainWindow._on_update_result
    _pending_update = {"version": "0.8.0"}
    _update_splash = None

    def hide(self):
        pass

    def show(self):
        pass


def main():
    app = QApplication.instance() or QApplication([])
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    output.mkdir(parents=True, exist_ok=True)
    owner = Owner()
    with (
        patch("threading.Thread"),
        patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ),
        patch.object(QMessageBox, "warning"),
    ):
        MainWindow._on_update_clicked(owner)
        screen = owner._update_splash
        try:
            for percent in (0, 37, 100):
                owner._update_progress.emit(percent)
                app.processEvents()
                assert screen.grab().save(str(output / f"manual-a-{percent}.png"))
            screen.prepare_apply()
            assert screen.grab().save(str(output / "manual-a-applying.png"))
        finally:
            owner._on_update_result(False, "render only")
        owner._pending_update = {
            "version": "0.8.0-beta.20261020+0123456789abcdef0123456789abcdef"
        }
        MainWindow._on_update_clicked(owner)
        screen = owner._update_splash
        try:
            owner._update_progress.emit(100)
            app.processEvents()
            assert screen.grab().save(str(output / "manual-a-long-version.png"))
        finally:
            owner._on_update_result(False, "render only")


if __name__ == "__main__":
    main()
