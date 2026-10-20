"""Observe current covered-window sound requests with a modeled Windows boundary.

This records the pre-fix behavior, not the desired acceptance criteria. It does
not test actual Windows composition or audio-device playback.
"""

import pytest

from scripts.qa_dialogue_transparent_occlusion import native_model  # noqa: F401
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: F401
from test_navigation import window  # noqa: F401
from mabinogi_addon.system import dialogue_visibility as visibility


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("covered", [False, True])
def test_observe_current_sound_request_under_modeled_cover(window, native_model,
                                                         automatic, covered):
    w, app = window
    state = native_model
    state.owner = int(w.winId())
    state.client = (0, 0, w.width(), w.height())
    state.alpha = 255 if covered else 0
    dialogue = w.creator_dialogue
    dialogue.timer.stop()
    dialogue.clock = lambda: 100.0
    dialogue.session.rng.random = lambda: 0.0
    w.settings_tab.dialogue_sound_enabled.setChecked(True)
    calls = []
    dialogue.sound = calls.append

    assert dialogue.visibility is visibility.display_available
    assert visibility.exposed(state.owner, [(20, 20, 48, 48)],
                              (w.width(), w.height())) is not covered
    assert visibility.display_available(state.owner, [(20, 20, 48, 48)],
                                        (w.width(), w.height()))
    assert dialogue._eligible()
    if automatic:
        dialogue.tick()
    else:
        assert dialogue.request()

    assert dialogue.bubble.isVisible()
    assert calls == [dialogue.session.last_text]
    assert len(dialogue.session.shown) == int(automatic)
    dialogue.dismiss()
    app.processEvents()
