"""Verify approved muted text attempts for flags-zero native composition.

This checks display/sound policy, not actual Windows compositor transparency.
Run with PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen python -m pytest
scripts/qa_dialogue_ambiguous_composition_20261020.py -q --tb=short.
"""

import sys

import pytest

from scripts.qa_dialogue_transparent_occlusion import native_model  # noqa: F401
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: F401
from test_navigation import window  # noqa: F401
from mabinogi_addon.system import dialogue_visibility as visibility


@pytest.mark.parametrize("automatic", [False, True])
def test_unknown_composition_allows_muted_text_until_evidence_changes(
        window, native_model, monkeypatch, automatic):
    w, app = window
    state = native_model
    state.owner = int(w.winId())
    state.client = (0, 0, w.width(), w.height())
    state.cover = (0, 0, 2559, 1440)
    gui = sys.modules["win32gui"]
    monkeypatch.setattr(gui, "GetLayeredWindowAttributes", lambda hwnd: (0, 0, 0))
    monkeypatch.setattr(gui, "CreateRectRgnIndirect", lambda rect: object(), raising=False)
    monkeypatch.setattr(gui, "GetWindowRgn", lambda *args: 0, raising=False)
    monkeypatch.setattr(gui, "DeleteObject", lambda *args: None, raising=False)
    monkeypatch.setattr(gui, "GetClassName", lambda hwnd: "CEF-OSC-WIDGET", raising=False)
    d = w.creator_dialogue
    d.timer.stop()
    d.clock = lambda: 100.0
    d.session.rng.random = lambda: 0.0
    w.settings_tab.dialogue_sound_enabled.setChecked(True)
    sounds = []
    d.sound = sounds.append
    assert d.enabled and d.session.entries
    assert d.visibility is visibility.display_available
    detail = {}
    assert visibility.display_available(state.owner, [(20, 20, 48, 48)],
                                            (w.width(), w.height()), diagnostic=detail)
    assert detail["visibility"] == "unknown"
    assert detail["alpha_flags"] == 0 and detail["region_type"] == 0
    if automatic:
        d.tick()
    else:
        assert d.request()
    assert d.bubble.isVisible() and not sounds
    assert len(d.session.shown) == int(automatic)
    assert (d.session.last_draw is not None) is automatic

    # Clear the native cover and make a fresh request; data/settings/focus stay intact.
    state.present = False
    d.dismiss()
    assert d.request()  # New visible manual dialogue may play; no queued sound resumes.
    assert d.bubble.isVisible() and len(sounds) == 1
    assert len(d.session.shown) == int(automatic)
    d.dismiss()
    app.processEvents()
