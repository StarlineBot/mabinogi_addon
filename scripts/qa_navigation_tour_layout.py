"""Independent seeded-state and small-work-area navigation/tour checks."""

from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QAction, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads
from mabinogi_addon import config
from mabinogi_addon.ui import main_window


KEYS = ("buff", "debuff", "tuarim", "boss", "stat_bars", "dorcha", "custom", "skillbar", "memo")


@pytest.mark.parametrize("area", [(0, 0, 900, 1000), (0, 0, 800, 600), (-1600, 120, 900, 700)])
@pytest.mark.parametrize("large_font", [False, True])
@pytest.mark.parametrize("finish", ["complete", "skip"])
def test_seeded_navigation_and_tour(area, large_font, finish, monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "qa", "name": "qa"})
    inactive = SimpleNamespace(is_game_active=lambda: False, is_self_active=lambda: False)
    monkeypatch.setattr(main_window, "create_window_watcher", lambda **kw: inactive)
    screen = type(app.primaryScreen())
    monkeypatch.setattr(screen, "geometry", lambda self: QRect(*area))
    monkeypatch.setattr(screen, "availableGeometry", lambda self: QRect(*area))
    box = dict(x=121, y=233, w=42, h=16)
    raw = {
        "general": {"skipSetup": True, "tourShown": True},
        "buffTracker": {"enabled": True, "captureRegion": box, "overlay": dict(x=40,y=50,locked=True)},
        "debuffTracker": {"enabled": True, "captureRegion": box},
        "tuarim": {"enabled": True, "box": box, "thresholds": [90,95], "sounds": [True,False]},
        "dorcha": {"enabled": True, "box": dict(x=577,y=123,w=28,h=23),
                   "pos": dict(x=700,y=500), "scale": 125, "locked": True},
        "statBars": {"enabled": True, "box": box, "scale": 175},
        "skillbar": {"enabled": True, "anchor": dict(x=10,y=20), "scale": 125},
        "memo": {"enabled": True, "text": "QA memo", "locked": True, "fontSize": 18},
        "qaUnknown": {"preserve": [1,2,3]},
    }
    config._write_local_config(raw)
    window = main_window.MainWindow()
    window._post_show_done = True
    try:
        window.move(area[0] + 5, area[1] + 5)
        window._leave_setup()
        window.show()
        for timer in window.findChildren(QTimer):
            timer.stop()
        if large_font:
            for widget in window.findChildren(QWidget):
                font = widget.font()
                font.setPixelSize(20)
                widget.setFont(font)
        app.processEvents()
        window._booting = False
        # Linux offscreen has no tray; provide the QAction created by Windows tray setup.
        if not hasattr(window, "_pause_act"):
            window._pause_act = QAction(window)
        window._set_paused(True)
        before = deepcopy(config._read_local_config())
        for key in raw:
            if key not in ("buffTracker", "general"):
                assert before[key] == raw[key], key
        timers = set(window.findChildren(QTimer))
        for _ in range(3):
            for key in KEYS:
                assert window._open_setup_feature(key)
                app.processEvents()
                page = window._combat_pages[key]
                assert window._tracker_tabs.currentWidget() is page
                assert page.isVisible()
                assert page.horizontalScrollBar().maximum() == 0, key
        assert set(window.findChildren(QTimer)) == timers
        assert config._read_local_config() == before
        window._tabs.setCurrentIndex(2)
        window._convenience_tabs.setCurrentIndex(2)
        window._run_tour()
        tour = window._tour
        for index in list(range(7)) + list(reversed(range(7))):
            tour._i = index
            tour._show_step()
            initial_target = tour._target_rect()
            initial_card = tour._card.geometry()
            loop = QEventLoop()
            QTimer.singleShot(50, loop.quit)
            loop.exec()
            for _ in range(8):
                app.processEvents()
            target = tour._steps[index].target
            if target is not None:
                rect = tour._target_rect()
                assert rect is not None and not rect.isEmpty(), (area, large_font, index)
                assert tour.rect().contains(rect)
                if rect.intersects(tour._card.geometry()):
                    print({"step": index + 1, "initial_target": str(initial_target),
                           "settled_target": str(rect), "initial_card": str(initial_card),
                           "settled_card": str(tour._card.geometry())})
                    image = QPixmap(tour.size())
                    image.fill(Qt.GlobalColor.white)
                    painter = QPainter(image)
                    painter.drawPixmap(window.mapToGlobal(QPoint()) - tour.pos(), window.grab())
                    painter.drawPixmap(0, 0, tour.grab())
                    painter.end()
                    image.save("/tmp/qa_navigation_large_tour_overlap.png")
                assert not rect.intersects(tour._card.geometry()), (area, large_font, index)
            assert tour.rect().contains(tour._card.geometry())
            for button in (tour._next, tour._skip):
                rect = QRect(button.mapTo(tour, QPoint()), button.size())
                assert button.isVisible() and tour.rect().contains(rect)
            assert not window.creator_dialogue._eligible()
        if finish == "complete":
            tour._i = 6
            tour._go_next()
        else:
            tour._skip.click()
        app.processEvents()
        assert window._tour is None
        assert window._tabs.currentWidget() is window._convenience_tabs
        assert window._convenience_tabs.currentIndex() == 2
        assert window._tracker_tabs.currentWidget() is window._combat_pages["memo"]
        assert window._paused
        assert config._read_local_config() == before
        assert set(window.findChildren(QTimer)) == timers
    finally:
        window._force_quit = True
        window.close()
        app.processEvents()
