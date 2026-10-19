"""Live requirement: known battle + decreasing timer survives hidden boss bar."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tests'))
from conftest import _isolated_runtime, _no_leaked_qthreads
from test_halo_presentation import creator_section, window

import pytest
import mabinogi_addon.ui.halo_capture_section as module


@pytest.mark.parametrize('output', ['countdown', 'warning'])
def test_confirmed_battle_keeps_outputs_while_timer_advances_without_boss_bar(window, monkeypatch, output):
    _, _, section = creator_section(window, monkeypatch)
    monkeypatch.setattr(section._watcher, 'is_game_active', lambda: True)
    monkeypatch.setattr(section._watcher, 'is_self_active', lambda: False)
    now = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    section._target = (11, 22, 0, 0, 1920, 1080)
    for moment, raw in ((100, 838), (100.5, 838), (101, 837)):
        now[0] = moment
        section.set_boss_context('lenen_miir_hoehan')
        section._monitor(raw)
    assert section._clock.anchor == (837, 101)
    assert section._countdown.isVisible()
    alerts = []
    monkeypatch.setattr(section._warning, 'show_message', lambda *args: alerts.append(args))
    # A normal boss pattern hides the bar; the registered game and timer persist.
    now[0] = 102
    section.set_boss_context(None)
    section._monitor(836)
    if output == 'countdown':
        assert section._countdown.isVisible(), 'valid decreasing timer loses its countdown when the known boss bar hides'
    else:
        now[0] = 103
        section.set_boss_context(None)
        section._monitor(835)
        assert alerts == [('헤일로 5초 전', 5000)], 'known-battle warning at 13:55 is suppressed solely by the missing boss bar'
