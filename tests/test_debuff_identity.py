import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.tracker.debuff_engine import DebuffEngine


ROOT = Path(__file__).resolve().parents[1]
PAIR = ("프라가라흐(마법)", "프라가라흐(물리)")
ASSETS = ROOT / "docs/qa/assets/debuff_native_20261016/candidates"


@pytest.fixture(params=["bundled", "native"])
def library(request):
    directory = (ROOT / "src/mabinogi_addon/assets/debuff/icon"
                 if request.param == "bundled" else ASSETS)
    templates = {bid: image_io.imread(directory / f"{bid}.png") for bid in PAIR}
    assert all(image is not None for image in templates.values())
    return templates


def run(engine, frame, start=0):
    for index in range(12):
        result = engine.tick(frame, now=start + index * .15)
    return {entry.buff_id for entry in result.entries}


@pytest.mark.parametrize("mode", ["off", "band", "percent"])
@pytest.mark.parametrize("padding", [0, 7])
@pytest.mark.parametrize("actual", PAIR)
def test_single_real_icon_does_not_hide_the_other_identity(library, actual, padding, mode):
    pixels = image_io.imread(ASSETS / f"{actual}.png")
    frame = np.pad(pixels, ((padding, padding), (padding, padding), (0, 0)))
    engine = DebuffEngine(library, list(PAIR), gate_mode=mode)
    assert run(engine, frame) == set(PAIR) - {actual}


def test_both_real_identities_at_different_positions_remain_detected(library):
    icons = [image_io.imread(ASSETS / f"{bid}.png") for bid in PAIR]
    frame = np.concatenate([icons[0], np.zeros((16, 2, 3), np.uint8), icons[1]], axis=1)
    engine = DebuffEngine(library, list(PAIR))
    assert run(engine, frame) == set()


def test_identity_change_releases_old_latch_and_empty_frame_restores_both(library):
    engine = DebuffEngine(library, list(PAIR))
    for index, actual in enumerate((*PAIR, PAIR[0])):
        pixels = image_io.imread(ASSETS / f"{actual}.png")
        assert run(engine, pixels, start=index * 2) == set(PAIR) - {actual}
    assert run(engine, np.zeros((16, 16, 3), np.uint8), start=6) == set(PAIR)


def test_identical_custom_templates_do_not_claim_two_identities(library):
    pixels = image_io.imread(ASSETS / f"{PAIR[0]}.png")
    engine = DebuffEngine({bid: pixels.copy() for bid in PAIR}, list(PAIR))
    assert run(engine, pixels) == set(PAIR)


def test_unregistered_peer_does_not_disable_a_single_template(library):
    for actual in PAIR:
        engine = DebuffEngine({actual: library[actual]}, [actual])
        pixels = image_io.imread(ASSETS / f"{actual}.png")
        assert run(engine, pixels) == set()


def test_annotated_original_scenes_and_single_slots_keep_identities(library):
    manifest = json.loads((ASSETS.parent / "manifest.json").read_text(encoding="utf-8"))
    names = {"D13": PAIR[0], "D14": PAIR[1]}
    checked = 0
    for scene in manifest["scenes"]:
        if not set(names).intersection(scene["labels"]):
            continue
        frame = image_io.imread(ROOT / scene["source"])
        x, y = scene["row_xy"]
        width = (len(scene["labels"]) - 1) * scene["stride"] + 16
        row = frame[y:y + 16, x:x + width]
        expected = set(PAIR) - {names[label] for label in scene["labels"] if label in names}
        assert run(DebuffEngine(library, list(PAIR)), row) == expected, scene["id"]
        for slot, label in enumerate(scene["labels"]):
            if label not in names:
                continue
            sx = x + slot * scene["stride"]
            patch = frame[y:y + 16, sx:sx + 16]
            assert run(DebuffEngine(library, list(PAIR)), patch) == set(PAIR) - {names[label]}, (
                scene["id"], slot, label)
            checked += 1
    assert checked > 2


def test_identity_verification_has_bounded_color_work(library, monkeypatch):
    from mabinogi_addon.tracker import debuff_engine as module

    pixels = image_io.imread(ASSETS / f"{PAIR[0]}.png")
    frame = np.pad(pixels, ((7, 7), (7, 7), (0, 0)))
    original = module.match_icon
    calls = []
    def record(region, template):
        calls.append(region.shape)
        return original(region, template)
    monkeypatch.setattr(module, "match_icon", record)
    engine = DebuffEngine(library, list(PAIR))
    engine.tick(frame, 0)
    assert 0 < len(calls) <= len(PAIR) * 4 * 2
    assert all(shape == (16, 16, 3) for shape in calls)


@pytest.fixture
def startup(library, monkeypatch):
    from mabinogi_addon import config, setup_state
    from mabinogi_addon.ui import main_window as module

    directory = (ASSETS if library[PAIR[0]].shape[0] == 16
                 else ROOT / "src/mabinogi_addon/assets/debuff/icon")
    catalog = [SimpleNamespace(id=bid, match_icon=directory / f"{bid}.png") for bid in PAIR]
    settings = [SimpleNamespace(id=bid, hidden=False) for bid in PAIR]
    monkeypatch.setattr(config, "load_debuff_settings", lambda: settings)
    monkeypatch.setattr(config, "load_capture_region", lambda *a: {"x": 0, "y": 0, "w": 16, "h": 16})
    monkeypatch.setattr(setup_state, "enabled", lambda *a: True)
    monkeypatch.setattr(module, "available_debuff_catalog", lambda: catalog)
    monkeypatch.setattr(module, "create_live_source", lambda *a: object())
    controllers = []
    class Controller:
        def __init__(self, *a, **k):
            self.stopped = 0
            controllers.append(self)
        def stop(self):
            self.stopped += 1
        def set_paused(self, value):
            pass
        def set_window_visible(self, value):  # 0.32.0 '오버레이 창 보이기'(실제 컨트롤러와 같은 메서드)
            pass
        def start(self, source, engine, **kwargs):
            self.engine = engine
            self.bar_source = kwargs.get("bar_source")
    monkeypatch.setattr(module, "BuffController", Controller)
    w = SimpleNamespace(_closing=False, _config_pending_restart=False, debuff_controller=None,
                        _debuff_engine=None, _paused=False, _watcher=None,
                        debuff_overlay=object(), debuff_tab=SimpleNamespace(effective_gate_mode=lambda: "off"),
                        _debuff_warn_gone_ids=lambda: set(), _on_debuff_gone=lambda *a: None)
    w._debuff_order = lambda entries: module.MainWindow._debuff_order(w, entries)
    w._start_debuff_tracking = lambda: module.MainWindow._start_debuff_tracking(w)
    return w, settings, controllers, module


@pytest.mark.parametrize("tracked", PAIR)
def test_real_startup_keeps_hidden_peer_reference_across_rebuilds(startup, tracked):
    w, settings, controllers, module = startup
    actual = next(bid for bid in PAIR if bid != tracked)
    pixels = image_io.imread(ASSETS / f"{actual}.png")
    w._start_debuff_tracking()
    next(item for item in settings if item.id == actual).hidden = True
    module.MainWindow._on_debuff_tracking_changed(w)
    assert run(w._debuff_engine, pixels) == {tracked}
    for _ in range(3):
        previous = w.debuff_controller
        w._start_debuff_tracking()
        engine = w._debuff_engine
        assert previous.stopped == 1
        assert set(engine._templates) == {tracked}
        assert set(engine._gray_variants) == {tracked}
        assert engine.reference_ids([tracked]) == {actual}
        assert run(engine, pixels) == {tracked}
        assert set(engine._matched) == {tracked}
    next(item for item in settings if item.id == actual).hidden = False
    previous = w.debuff_controller
    module.MainWindow._on_debuff_tracking_changed(w)
    assert previous.stopped == 1
    assert w._debuff_engine.can_track(list(PAIR))
    assert run(w._debuff_engine, pixels) == {tracked}


@pytest.mark.parametrize("tracked", PAIR)
def test_hidden_peer_is_never_globally_searched_or_returned(library, tracked, monkeypatch):
    engine = DebuffEngine({tracked: library[tracked]}, [tracked], reference_templates=library)
    actual = next(bid for bid in PAIR if bid != tracked)
    pixels = image_io.imread(ASSETS / f"{actual}.png")
    original = engine._candidate_best
    searched = []
    def record(frame, bid, gray, **kwargs):
        searched.append(bid)
        return original(frame, bid, gray, **kwargs)
    monkeypatch.setattr(engine, "_candidate_best", record)
    assert run(engine, pixels) == {tracked}
    assert set(searched) == {tracked}
    assert set(engine.best_scores(pixels)) == {tracked}


@pytest.mark.parametrize("hp_region", [None, {"x": 0, "y": 0, "w": 160, "h": 32}])
def test_auto_start_is_independent_of_boss_pattern_feature(startup, monkeypatch, hp_region):
    from mabinogi_addon import config, setup_state

    w, settings, controllers, module = startup
    w.debuff_tab.effective_gate_mode = lambda: "auto"
    monkeypatch.setattr(setup_state, "enabled", lambda feature: feature == "debuff")
    monkeypatch.setattr(config, "load_boss_pattern", lambda: {"enabled": False})
    monkeypatch.setattr(config, "load_boss_bar_region", lambda: hp_region)
    captures = []
    def capture(region):
        result = object()
        captures.append(result)
        return result
    monkeypatch.setattr(module, "create_live_source", capture)
    w._start_debuff_tracking()
    assert w._debuff_engine.gate_mode == "auto"
    assert len(captures) == (2 if hp_region else 1)
    assert w.debuff_controller.bar_source is (captures[1] if hp_region else None)
