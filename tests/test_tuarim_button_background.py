"""The live detector input must not depend on pixels outside the opaque button."""

import cv2
import numpy as np
import pytest

from mabinogi_addon import autofind_diagnostics as diag
from mabinogi_addon.autofind_replay import detector_assets, replay, run_detector
from scripts.qa_tuarim_right_structure_background import (
    diagnostic,
    single_opencv_thread,
    test_live_original_must_locate_visible_tuarim,
    test_saved_failure_records_current_assets_and_right_structure_rejection,
    test_opaque_button_pixels_are_exact_and_score_one,
    test_only_38_outside_pixels_change_rejection_to_acceptance,
    test_visible_zero_percent_is_independently_readable,
    test_same_original_dorcha_locates_and_reads_five,
    test_missing_right_button_is_still_rejected,
)


@pytest.mark.parametrize("scale", [0.75, 1.0, 1.25, 1.5, 2.0])
@pytest.mark.parametrize("background", [0, 255])
@pytest.mark.parametrize("shift", [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_button_background_and_pixel_phase_at_supported_scales(diagnostic, scale, background, shift):
    _, original, assets = diagnostic
    panel = original[106:167,569:645].copy()
    # Keep the ornament, opaque button and percentage. Replace only surrounding
    # scenery, including the formerly compared pixels beside/below the button.
    keep = np.zeros(panel.shape[:2], bool)
    keep[:57,:45] = True
    keep[33:45,47:71] = True
    keep[46:61,34:76] = True
    panel[~keep] = background
    panel = cv2.resize(panel, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    x, y = 60 + shift[0], 40 + shift[1]
    image = np.full((240,320,3), background, np.uint8)
    image[y:y+panel.shape[0],x:x+panel.shape[1]] = panel
    trace = {}
    expected = (x+round(34*scale), y+round(45*scale), round(42*scale), round(16*scale))
    assert run_detector("tuarim", image, assets, trace) == expected, trace


def test_new_live_input_zip_replays_without_installed_assets(diagnostic, tmp_path, monkeypatch):
    from mabinogi_addon.detect import tuarim_anchor, resource_anchor
    _, image, assets = diagnostic
    store = diag.DiagnosticStore(tmp_path / "투아림 진단")
    try:
        _, _, _, box = diag.perform_autofind("tuarim", lambda: (image, -2560, 120),
                                            storage=store, assets=assets)
        assert box == (603,151,42,16)
        store.io.wait()
        path = store.export(store.recent()[0], tmp_path / "재현 자료.zip")
        def forbidden(*a, **k):
            pytest.fail("replay loaded installed assets")
        monkeypatch.setattr(tuarim_anchor, "assets", forbidden)
        monkeypatch.setattr(resource_anchor, "assets", forbidden)
        result = replay(path)
        assert result["replayed"] and result["matches_recorded"]
        assert result["result"] == list(box)
    finally:
        store.io.close()


def test_missing_button_with_legacy_full_assets_still_rejected(diagnostic):
    _, image, assets = diagnostic
    image = image.copy()
    image[139:151,616:640] = 0
    legacy = {key: assets[key] for key in ("anchor", "mask")}
    assert run_detector("tuarim", image, legacy, {}) is None
