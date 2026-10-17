"""Render actual navigation offline with temporary, sample-only settings."""

from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import argparse
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from mabinogi_addon import config
from mabinogi_addon.ui.main_window import MainWindow
from test_support.boundaries import ExternalBoundaries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("/tmp/navigation-implemented"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    raw = {"general": {"skipSetup": True}, "buffTracker": {"enabled": False},
           "debuffTracker": {"enabled": False}}

    def settle():
        for _ in range(8):
            app.processEvents()

    with ExitStack() as stack:
        boundary = stack.enter_context(ExternalBoundaries())
        stack.enter_context(patch.object(config, "_read_local_config", lambda *a, **k: deepcopy(raw)))
        stack.enter_context(patch.object(config, "_write_local_config", lambda *a, **k: None))
        stack.enter_context(patch.object(config, "load_discord_user", lambda *a, **k: {"id": "preview", "name": "미리보기"}))
        stack.enter_context(patch.object(QApplication, "quit", lambda: None))
        stack.enter_context(patch("os._exit", lambda *a: None))
        screen = type(app.primaryScreen())
        stack.enter_context(patch.object(screen, "availableGeometry", lambda self: QRect(0, 0, 900, 1000)))
        stack.enter_context(patch.object(screen, "geometry", lambda self: QRect(0, 0, 900, 1000)))
        window = MainWindow()
        window._post_show_done = True
        try:
            window.move(0, 0)
            window._leave_setup()
            window.buff_tab.buff_list.setCurrentRow(1)
            window.show()
            for timer in window.findChildren(QTimer):
                timer.stop()
            for key in window._combat_pages:
                window._open_setup_feature(key)
                settle()
                assert window.grab().save(str(args.out / f"{key}.png"))
            window._tabs.setCurrentIndex(2)
            settle()
            assert window.grab().save(str(args.out / "convenience.png"))
            fonts = {widget: widget.font() for widget in window.findChildren(QWidget)}
            for widget, original in fonts.items():
                font = QFont(original)
                font.setPixelSize(20)
                widget.setFont(font)
            for key in ("buff", "debuff"):
                window._open_setup_feature(key)
                settle()
                assert window.grab().save(str(args.out / f"large-font-{key}.png"))
            for widget, original in fonts.items():
                widget.setFont(original)
            window._run_tour(from_guide=True)
            tour = window._tour
            for index in range(7):
                tour._i = index
                tour._show_step()
                settle()
                image = QPixmap(tour.size())
                image.fill(Qt.GlobalColor.white)
                painter = QPainter(image)
                painter.drawPixmap(window.mapToGlobal(QPoint()) - tour.pos(), window.grab())
                painter.drawPixmap(0, 0, tour.grab())
                painter.end()
                assert image.save(str(args.out / f"tour-{index+1}.png"))
            assert not boundary.violations, boundary.violations
            print(args.out, flush=True)
        finally:
            window._force_quit = True
            window.close()
            settle()


if __name__ == "__main__":
    main()
