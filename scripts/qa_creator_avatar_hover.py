"""Reproduce creator avatar hover panels without changing product code."""

from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config
from mabinogi_addon.ui.main_window import MainWindow
from test_support.boundaries import ExternalBoundaries


def pixels(widget):
    image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(image.constBits(), np.uint8).reshape(
        image.height(), image.bytesPerLine()
    )[:, :image.width() * 4].reshape(image.height(), image.width(), 4).copy()


@pytest.mark.parametrize("location", ["footer", "settings"])
def test_avatar_hover_keeps_area_outside_circle_unchanged(location):
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    raw = {"general": {"skipSetup": True}}
    out = Path("/tmp/creator-hover-qa")
    out.mkdir(exist_ok=True)
    with ExternalBoundaries() as boundary, \
            patch.object(config, "_read_local_config", side_effect=lambda *a, **k: deepcopy(raw)), \
            patch.object(config, "_write_local_config"), \
            patch.object(config, "load_discord_user", return_value={"id": "qa", "name": "qa"}), \
            patch.object(QApplication, "quit"), patch("os._exit"):
        window = MainWindow()
        try:
            window.show()
            if location == "settings":
                window._tabs.setCurrentIndex(3)
                button = window.settings_tab.creator_avatar
            else:
                dialogue = window.creator_dialogue
                dialogue.visibility = lambda *a: True
                dialogue.refresh()
                button = dialogue.face
            app.processEvents()
            QTest.mouseMove(window, QPoint(1, 1))
            app.processEvents()
            assert not button.underMouse()
            before = pixels(button)
            button.grab().save(str(out / f"{location}-normal.png"))
            QTest.mouseMove(button, button.rect().center())
            app.processEvents()
            assert button.underMouse()
            after = pixels(button)
            button.grab().save(str(out / f"{location}-hover.png"))
            yy, xx = np.indices(before.shape[:2])
            outside = (xx - 23.5) ** 2 + (yy - 23.5) ** 2 > 24 ** 2
            changed = np.any(before != after, axis=2) & outside
            count = int(changed.sum())
            print(f"{location}: changed pixels outside circular avatar={count}")
            assert count == 0, f"{location}: hover paints {count} pixels outside circular avatar"
        finally:
            window._force_quit = True
            window.close()
            app.processEvents()
        assert not boundary.violations
