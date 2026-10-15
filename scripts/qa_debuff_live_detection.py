"""Independent original-PNG debuff recall probes. Run explicitly with pytest."""

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, image_io, setup_state
from mabinogi_addon import autofind_diagnostics as diagnostics
from mabinogi_addon.catalog import BuffDef, build_templates
from mabinogi_addon.tracker.debuff_engine import DebuffEngine
from mabinogi_addon.ui import setup_flow
from mabinogi_addon.ui.setup_page import SetupPage


ROOT = Path(__file__).resolve().parents[1]
MAGIC = "\ub9c8\ubc95 \ubc29\uc5b4\ub825 \ubcf4\ud638 \uac10\uc18c"
FRAGARACH = "\ud504\ub77c\uac00\ub77c\ud750(\ub9c8\ubc95)"
IDS = [MAGIC, FRAGARACH]
SHOT_PREFIX = "\uc2a4\ud06c\ub9b0\uc0f7 2026-10-15 "


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def templates():
    directory = ROOT / "src/mabinogi_addon/assets/debuff/icon"
    result = build_templates([
        BuffDef(bid, bid, directory / f"{bid}.png", None) for bid in IDS
    ])
    assert set(result) == set(IDS)
    return result


@pytest.fixture(params=["213313", "213734"])
def scene(request, app, monkeypatch, tmp_path):
    image = image_io.imread(ROOT / "tests/data" / f"{SHOT_PREFIX}{request.param}.png")
    assert image is not None and image.shape == (1436, 2556, 3)
    path = tmp_path / "settings.json"
    read, write = config._read_local_config, config._write_local_config
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: read(path))
    monkeypatch.setattr(config, "_write_local_config", lambda data, *a, **k: write(data, path))
    raw = {f.section: {"enabled": False} for f in setup_state.FEATURES}
    raw["general"] = {"gameExe": "Client.exe"}
    raw["debuffTracker"]["enabled"] = True
    config._write_local_config(raw)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "qa", "name": "QA"})
    storage = diagnostics.DiagnosticStore(tmp_path / "diagnostics")
    monkeypatch.setattr(diagnostics, "store", lambda: storage)
    monkeypatch.setattr(setup_flow, "capture_for_autofind", lambda **kwargs: (image, 0, 0))
    # Explicit 100% DPI scenario; no claim about the reporter's Windows settings.
    monkeypatch.setattr(setup_flow, "to_logical", lambda *box: box)
    page = SetupPage()
    approved = []

    def save(key, box):
        assert key == "debuff"
        approved.append(box)
        config.save_capture_region(*box, "debuffTracker")

    flow = setup_flow.SetupFlow(page, save)
    monkeypatch.setattr(flow, "_approve", lambda key, box: box)
    monkeypatch.setattr(flow, "_notice", lambda *args: pytest.fail(str(args)))
    try:
        flow.run(feature_keys=("debuff",))
        assert approved == [(1016, 1195, 521, 88)]
        saved = config.load_capture_region("debuffTracker")
        box = tuple(saved[k] for k in ("x", "y", "w", "h"))
        assert box == approved[0]
        yield request.param, image, box
    finally:
        flow.shutdown()
        if flow.future is not None:
            flow.future.result(timeout=5)
        page.close()
        page.deleteLater()
        app.processEvents()
        storage.io.close()


def crop(image, box):
    x, y, w, h = box
    return image[y:y + h, x:x + w]


def settle(engine, region, bar_region, start=0):
    result = None
    for tick in range(12):
        result = engine.tick(region, now=start + tick * 0.15, bar_region=bar_region)
    return result


def assert_applied(engine, region, bar_region, label):
    result = settle(engine, region, bar_region)
    shown = [entry.buff_id for entry in result.entries]
    assert not shown, {
        "scene": label, "shown_as_missing": shown,
        "scores": engine.best_scores(region),
        "detect_thresholds": {bid: engine.detect_threshold_for(bid) for bid in IDS},
    }


@pytest.mark.parametrize("mode", ["off", "band", "percent"])
def test_real_autofind_region_recognizes_both_visible_icons(scene, templates, mode):
    name, image, box = scene
    engine = DebuffEngine(templates, IDS, gate_mode=mode)
    assert_applied(engine, crop(image, box), image[1246:1283, 1016:1537], (name, mode, box))


@pytest.mark.parametrize("delta", [(1, 0, 0), (0, 0, -1), (0, 0, 1)],
                         ids=["x-plus-one", "height-minus-one", "height-plus-one"])
def test_roi_border_changes_keep_complete_icon_pixels_recognizable(scene, templates, delta):
    name, image, box = scene
    dx, dy, dh = delta
    x, y, w, h = box
    shifted = (x + dx, y + dy, w, h + dh)
    # Both real icons are inside this common interior, unchanged by ROI borders.
    assert np.array_equal(crop(image, box)[17:35, 7:177],
                          crop(image, shifted)[17 - dy:35 - dy, 7 - dx:177 - dx])
    assert_applied(DebuffEngine(templates, IDS), crop(image, shifted), None, (name, shifted))


def test_existing_match_can_survive_the_same_low_start_score(scene, templates):
    name, image, box = scene
    x, y, w, h = box
    engine = DebuffEngine(templates, IDS)
    assert_applied(engine, crop(image, (x, y + 1, w, h)), None, (name, "initial good region"))
    # This is a controlled input sequence, not evidence of an actual live ROI change.
    result = settle(engine, crop(image, box), None, start=2)
    assert not result.entries
