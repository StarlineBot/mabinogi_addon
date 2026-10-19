"""Independent full-battle/continuity checks with native and audio boundaries isolated."""

from pathlib import Path
import sys

import numpy as np
import pytest
from PySide6.QtCore import QObject, QRect, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'tests'))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_halo_presentation import creator_section, window  # noqa: E402,F401
from test_halo_timer import frame  # noqa: E402
from mabinogi_addon import config  # noqa: E402
from mabinogi_addon.detect.halo_timer import locate_timer, read_seconds, references  # noqa: E402
from mabinogi_addon.ui import halo_capture_section as module, notifier  # noqa: E402


def prepare(window, monkeypatch):
    w, app, section = creator_section(window, monkeypatch)
    monkeypatch.setattr(config, 'load_discord_user', lambda: {'id': 'ordinary-beta'})
    monkeypatch.setattr(section._watcher, 'is_game_active', lambda: True)
    moment = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: moment[0])
    section._target = (11, 22, 0, 0, 1920, 1080)
    for t, raw in ((100, 900), (100.5, 900), (101, 899)):
        moment[0] = t
        section.set_boss_context('lenen_miir_hoehan')
        section._monitor(raw)
    assert section._battle_target == (11, 22)
    section.set_boss_context(None)
    return w, app, section, moment


def test_entire_battle_without_boss_bar_warns_once_per_round_without_object_growth(window, monkeypatch):
    _, _, section, moment = prepare(window, monkeypatch)
    players, alerts = [], []

    class Audio(QObject):
        def __init__(self, sounds, parent=None, volume=1):
            super().__init__(parent)
            self.calls = []
            players.append(self)

        def play(self, key):
            self.calls.append((key, moment[0]))

        def stop(self):
            pass

    monkeypatch.setattr(notifier, 'SoundNotifier', Audio)
    section.sound.setChecked(True)
    show = section._warning.show_message

    def record(*args):
        alerts.append(moment[0])
        show(*args)

    monkeypatch.setattr(section._warning, 'show_message', record)
    timers = set(section.findChildren(QTimer))
    for tick in range(3, 1801):
        elapsed = tick / 2
        moment[0] = 100 + elapsed
        section.set_boss_context(None)
        section._monitor(900 - int(elapsed))
        assert section._session is None
    assert alerts == [100 + 2 + 63 * n for n in range(15)]
    assert len(players) == 1 and len(players[0].calls) == 15
    assert not section._clock.armed and section._battle_target is None
    assert not section._warning.isVisible() and not section._countdown.isVisible()
    assert set(section.findChildren(QTimer)) == timers


def test_focus_gap_crossing_warning_does_not_replay_after_bossless_recovery(window, monkeypatch):
    _, _, section, moment = prepare(window, monkeypatch)
    alerts = []
    monkeypatch.setattr(section._warning, 'show_message', lambda *args: alerts.append(moment[0]))
    for t in (101.5, 102, 102.5, 103):
        moment[0] = t
        section._monitor(None)
        assert not section._countdown.isVisible()
    for tick in range(7, 135):
        elapsed = tick / 2
        moment[0] = 100 + elapsed
        section._monitor(900 - int(elapsed))
    # Reconfirmation uses integer OCR samples, so its anchor can shift by one sample.
    assert len(alerts) == 1 and 165.0 <= alerts[0] <= 166.0
    assert {1, 2}.issubset(section._clock.fired)
    assert section._countdown.isVisible()


@pytest.mark.parametrize('x,y,width,height', [
    (500, 50, 1280, 720), (1000, 100, 1920, 1080),
    (800, 150, 2560, 1440), (1800, 180, 3840, 2160),
])
def test_same_timer_pixels_can_be_found_at_different_positions_and_screen_sizes(x, y, width, height):
    crop = frame(1)
    source = np.zeros((height, width, 3), np.uint8)
    h, w = crop.shape[:2]
    source[y:y+h, x:x+w] = crop
    trace = {}
    box = locate_timer(source, references(), trace)
    assert box is not None, trace
    bx, by, bw, bh = box
    assert read_seconds(source[by:by+bh, bx:bx+bw]) == read_seconds(crop)
    assert source[y:y+h, x:x+w].tobytes() == crop.tobytes()


def test_large_font_small_window_controls_remain_reachable(window, monkeypatch):
    w, app, section = creator_section(window, monkeypatch)
    monkeypatch.setattr(type(app.primaryScreen()), 'availableGeometry',
                        lambda self: QRect(0, 0, 800, 652))
    for widget in w.findChildren(QWidget):
        font = QFont(widget.font())
        font.setPixelSize(20)
        widget.setFont(font)
    section.disclosure.setChecked(True)
    w.creator_dialogue.refresh()
    for _ in range(8):
        app.processEvents()
    assert w.height() == 620
    inner = w.boss_tab.pattern_tabs.widget(1)
    outer = w._combat_pages['boss']
    for button in (section.auto_find_btn, section.region_btn, section.sound,
                   section.snapshot, section.folder):
        inner.ensureWidgetVisible(button)
        outer.ensureWidgetVisible(button)
        for _ in range(3):
            app.processEvents()
        center = button.mapTo(w, button.rect().center())
        assert w.rect().contains(center), button.text()
        assert w.childAt(center) is button, (button.text(), center, w.childAt(center))
