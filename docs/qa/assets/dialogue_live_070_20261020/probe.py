"""Unchanged CEF-like unknown-region veto, isolated from data/chance/Qt clicks."""

from pathlib import Path
import sys

import pytest
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'tests'))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from scripts.qa_dialogue_transparent_occlusion import native_model, window, app  # noqa: E402,F401
from mabinogi_addon.system import dialogue_visibility as visibility  # noqa: E402


@pytest.mark.parametrize('automatic', [False, True])
def test_unknown_region_still_vetoes_and_removing_only_blocker_restores_display(
        window, app, native_model, monkeypatch, automatic):
    d = window.creator_dialogue
    state = native_model
    state.owner = int(window.winId())
    state.client = (0, 0, window.width(), window.height())
    state.cover = (0, 0, 2559, 1440)
    gui = sys.modules['win32gui']
    monkeypatch.setattr(gui, 'GetLayeredWindowAttributes', lambda hwnd: (0, 0, 0))
    monkeypatch.setattr(gui, 'GetClassName', lambda hwnd: 'CEF-OSC-WIDGET', raising=False)
    live = set()

    def create(rect):
        live.add(1)
        return 1

    def no_region(*args):
        raise OSError(0, 'no explicit region')

    monkeypatch.setattr(gui, 'CreateRectRgnIndirect', create, raising=False)
    monkeypatch.setattr(gui, 'GetWindowRgn', no_region, raising=False)
    monkeypatch.setattr(gui, 'DeleteObject', live.remove, raising=False)
    d.timer.stop()
    d.visibility = visibility.exposed
    d.clock = lambda: 100.0
    d.session.rng.random = lambda: 0.0
    assert d.session.entries

    def request():
        if automatic:
            d.tick()
        else:
            QTest.mouseClick(d.face, Qt.MouseButton.LeftButton)

    request()
    assert not d.bubble.isVisible()
    assert 'occluded' in d._ineligible_reason and not live
    state.present = False
    request()
    assert d.bubble.isVisible() and not live
