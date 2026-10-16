"""Independent follow-up probes; run explicitly with pytest, not product edits."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.tracker.debuff_engine import DebuffEngine


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs/qa/assets/debuff_native_20261016"
PAIR = ("프라가라흐(마법)", "프라가라흐(물리)")


@pytest.fixture(params=("bundled", "native"))
def library(request):
    directory = ROOT / "src/mabinogi_addon/assets/debuff/icon" if request.param == "bundled" else DATA / "candidates"
    return {name: image_io.imread(directory / f"{name}.png") for name in PAIR}


@pytest.fixture(scope="module")
def inputs():
    shot = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-15 213313.png")
    floor = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-12 024008.png")
    assert shot is not None and floor is not None
    region = shot[1195:1283, 1016:1537].copy()
    region[:51] = 0
    bar = shot[1246:1283, 1016:1537].copy()
    return region, bar, floor[1195:1283, 1016:1537].copy()


def icons_on_bar(inputs, identities, x=7, dy=0):
    region = inputs[0].copy()
    for index, identity in enumerate(identities):
        pixels = image_io.imread(DATA / "candidates" / f"{identity}.png")
        sx, sy = x + index * 18, 17 + dy
        region[sy:sy+16, sx:sx+16] = pixels
    assert DebuffEngine._bar_present(region)
    return region


def settle(engine, region, bar, start=0):
    for index in range(12):
        result = engine.tick(region, now=start + index * .15, bar_region=bar)
    return {entry.buff_id for entry in result.entries}


@pytest.mark.parametrize("mode", ("off", "band", "percent"))
@pytest.mark.parametrize("actual", PAIR)
@pytest.mark.parametrize("position", ((7, 0), (8, -1), (220, 1)))
def test_actual_bar_gate_and_position_keep_single_identity(library, inputs, mode, actual, position):
    region = icons_on_bar(inputs, [actual], *position)
    engine = DebuffEngine(library, list(reversed(PAIR)), gate_mode=mode)
    assert settle(engine, region, inputs[1]) == set(PAIR) - {actual}
    if mode != "off":
        assert engine.bar_seen, "must exercise an active gate, not startup fallback"


@pytest.mark.parametrize("mode", ("off", "band", "percent"))
def test_repeated_identity_and_boss_transitions(library, inputs, mode):
    engine = DebuffEngine(library, list(PAIR), gate_mode=mode)
    now = 0
    for _ in range(12):
        for identities in ([PAIR[0]], list(PAIR), [PAIR[1]], []):
            assert settle(engine, icons_on_bar(inputs, identities), inputs[1], now) == set(PAIR) - set(identities)
            now += 2
        assert settle(engine, inputs[2], inputs[2][51:], now) == set(PAIR)
        now += 2
        for state in (engine._matched, engine._shown, engine._detect_since, engine._absent_since):
            assert len(state) == 2
    assert settle(engine, icons_on_bar(inputs, PAIR), inputs[1], now) == set()


def test_other_named_real_icons_do_not_claim_fragarach(library):
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    known = {entry["id"] for entry in manifest["candidates"]} - {"D13", "D14"}
    count = 0
    for scene in manifest["scenes"]:
        frame = image_io.imread(ROOT / scene["source"])
        for slot, identity in enumerate(scene["labels"]):
            if identity not in known:
                continue
            x, y = scene["row_xy"]
            x += scene["stride"] * slot
            patch = frame[y:y+16, x:x+16]
            assert settle(DebuffEngine(library, list(PAIR)), patch, None) == set(PAIR), (scene["id"], slot)
            count += 1
    assert count == 75


def test_percent_missing_capture_does_not_reset_visible_icons(library, inputs):
    engine = DebuffEngine(library, list(PAIR), gate_mode="percent")
    region = icons_on_bar(inputs, [PAIR[0]])
    expected = {PAIR[1]}
    assert settle(engine, region, inputs[1]) == expected
    assert engine.bar_seen
    assert settle(engine, region, None, start=2) == expected
    assert settle(engine, region, inputs[1], start=4) == expected


@pytest.mark.parametrize("mode", ("band", "percent"))
def test_dark_bar_and_unreadable_percent_are_not_boss_absence(library, inputs, mode):
    engine = DebuffEngine(library, list(PAIR), gate_mode=mode)
    normal = icons_on_bar(inputs, [PAIR[1]])
    assert settle(engine, normal, inputs[1]) == {PAIR[0]}
    assert engine.bar_seen
    dark = normal.copy()
    dark[51:] = 0
    black_bar = np.zeros_like(inputs[1])
    assert not engine._bar_present(dark)
    assert not engine._is_background(black_bar)
    assert settle(engine, dark, black_bar, start=2) == {PAIR[0]}


@pytest.mark.parametrize("tracked", PAIR)
def test_hiding_peer_and_restart_must_not_change_identity(library, tracked, monkeypatch):
    from mabinogi_addon import config
    from mabinogi_addon.ui.main_window import MainWindow

    monkeypatch.setattr(config, "load_debuff_settings", lambda: [
        SimpleNamespace(id=name, hidden=name != tracked) for name in PAIR
    ])
    order = MainWindow._debuff_order(None, [SimpleNamespace(id=name) for name in PAIR])
    assert order == [tracked]
    actual = next(name for name in PAIR if name != tracked)
    pixels = image_io.imread(DATA / "candidates" / f"{actual}.png")
    running = DebuffEngine(library, list(PAIR))
    running.set_order(order)
    before_restart = settle(running, pixels, None)
    assert before_restart == {tracked}
    restarted = DebuffEngine({name: library[name] for name in order}, order)
    after_restart = settle(restarted, pixels, None)
    assert after_restart == before_restart, {
        "tracked": tracked, "actual": actual,
        "before_restart": sorted(before_restart), "after_restart": sorted(after_restart),
    }
