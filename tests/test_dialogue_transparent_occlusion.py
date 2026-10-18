"""Explicit Windows API model; not a live compositor test."""

import sys
import pytest

from scripts.qa_dialogue_transparent_occlusion import (
    app, window, native_model,
    test_visibility_respects_real_coverage_not_just_window_bounds,
    test_transparent_overlay_does_not_block_actual_dialogue,
    test_real_zero_alpha_window_does_not_occlude_dialogue,
)
from mabinogi_addon.system import dialogue_visibility as visibility


@pytest.mark.parametrize("alpha", [1, 128, 255])
def test_partial_alpha_is_still_a_cover(native_model, alpha):
    native_model.alpha = alpha
    assert not visibility.exposed(11, [(20,20,48,48)], (800,800))


def test_nonlayered_zero_alpha_is_not_ignored(native_model):
    native_model.layered = False
    assert not visibility.exposed(11, [(20,20,48,48)], (800,800))


@pytest.mark.parametrize("failure", ["unavailable", "color_key"])
def test_uncertain_or_color_key_alpha_stays_conservative(native_model, monkeypatch, failure):
    gui = sys.modules["win32gui"]
    def get_alpha(hwnd):
        if failure == "unavailable":
            raise RuntimeError("per-pixel layered window")
        return 0, 0, 1
    monkeypatch.setattr(gui, "GetLayeredWindowAttributes", get_alpha)
    assert not visibility.exposed(11, [(20,20,48,48)], (800,800))
