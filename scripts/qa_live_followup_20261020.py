"""Independent follow-up: default dialogue gate and reversible sidebar sizing.

PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen python -m pytest
scripts/qa_live_followup_20261020.py -q -s
"""

from pathlib import Path
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_navigation import window  # noqa: E402,F401
from test_calculator_result_state import test_sidebar_font_growth_and_return_preserve_selection  # noqa: E402,F401
from scripts.qa_dialogue_transparent_occlusion import native_model  # noqa: E402,F401
from mabinogi_addon.system.dialogue_visibility import display_available  # noqa: E402


def test_current_default_gate_survives_repeated_clicks_and_window_reopen(
        window, native_model, monkeypatch):
    w, app = window
    d = w.creator_dialogue
    assert d.visibility is display_available
    native_model.owner = int(w.winId())
    native_model.client = (0, 0, w.width(), w.height())
    native_model.cover = (0, 0, 2559, 1440)
    gui = sys.modules['win32gui']

    def forbidden(*args):
        raise AssertionError('default dialogue consulted an external covering window')

    for name in ('EnumWindows', 'GetWindowRgn', 'GetLayeredWindowAttributes'):
        monkeypatch.setattr(gui, name, forbidden, raising=False)
    d.timer.stop()
    d.clock = lambda: 100.0
    d.session.rng.random = lambda: 0.0
    timers = set(d.findChildren(QTimer))
    for index in range(30):
        w._tabs.setCurrentIndex((0, 2, 3)[index % 3])
        app.processEvents()
        if index % 3 == 2:
            w._tabs.widget(3).ensureWidgetVisible(w.settings_tab.creator_avatar)
            app.processEvents()
        QTest.mouseClick(d._anchor(), Qt.MouseButton.LeftButton)
        assert d.bubble.isVisible()
        assert not d.session.shown
        assert set(d.findChildren(QTimer)) == timers
        if index % 5 == 0:
            w.hide()
            app.processEvents()
            assert not d.bubble.isVisible()
            w.show()
            app.processEvents()
            d.timer.stop()
    d.dismiss()
    d.tick()
    assert d.bubble.isVisible() and len(d.session.shown) == 1
    d.clock = lambda: 103.0
    d.tick()
    assert not d.bubble.isVisible() and len(d.session.shown) == 1
    assert set(d.findChildren(QTimer)) == timers
