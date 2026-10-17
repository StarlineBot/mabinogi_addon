"""Replay live Pellom screenshots with the actual boss locator and name matcher."""

from pathlib import Path
import sys

import cv2
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads
from mabinogi_addon import image_io
from mabinogi_addon.detect.boss_bar import locate_boss_bar, make_validator
from mabinogi_addon.detect.boss_hp_reader import read_percent
from mabinogi_addon.detect.boss_name_matcher import _binary, identify, load_name_templates

SAMPLES = ("001116", "001216", "001307", "001541", "001801")
EXPECTED_HP = (99, 87, 75, 42, 8)


def upper_box(stamp):
    return (1018, 1248, 521, 37) if stamp == "001116" else (1016, 1246, 521, 37)


def crop(image, box):
    x, y, w, h = box
    return image[y:y+h, x:x+w]


def inspect_sample(stamp):
    path = ROOT / f"tests/data/스크린샷 2026-10-18 {stamp}.png"
    image = image_io.imread(path)
    assert image is not None
    diagnostics = {}
    box = locate_boss_bar(image, make_validator(), diagnostics=diagnostics)
    frame = crop(image, upper_box(stamp))
    name = frame[:, :int(frame.shape[1]*.60)]
    binary = _binary(name)
    scores = {}
    for boss, template in load_name_templates().items():
        if template.shape[0] <= binary.shape[0] and template.shape[1] <= binary.shape[1]:
            result = cv2.matchTemplate(binary, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, position = cv2.minMaxLoc(result)
            scores[boss] = dict(score=round(score, 6), position=position, shape=template.shape)
    result = dict(sample=stamp, shape=image.shape, auto_box=box, upper_box=upper_box(stamp), identified=identify(name),
                  hp=read_percent(frame[:, int(frame.shape[1]*.58):]), scores=scores,
                  locator=diagnostics)
    return result, image, frame


@pytest.mark.parametrize("stamp", SAMPLES)
def test_visible_pellom_is_identified(stamp):
    result, _, _ = inspect_sample(stamp)
    print(result)
    assert result["identified"] == "pellom", result


@pytest.mark.parametrize("stamp,expected_hp", tuple(zip(SAMPLES, EXPECTED_HP)))
def test_upper_boss_hp_is_read(stamp, expected_hp):
    result, _, _ = inspect_sample(stamp)
    assert result["hp"] == expected_hp, result


def test_low_hp_autofind_never_selects_erg_bar():
    result, _, _ = inspect_sample("001801")
    x, y, w, h = result["auto_box"]
    expected = upper_box("001801")
    assert abs(y + h / 2 - expected[1] - expected[3] / 2) < 10, result


@pytest.mark.parametrize("sample", ("195115", "001216"))
def test_actual_boss_tick_starts_pellom_tracking(monkeypatch, sample):
    from types import SimpleNamespace
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
    from mabinogi_addon.ui import dpi
    from mabinogi_addon.ui.boss_tab import BossTab

    app = QApplication.instance() or QApplication([])
    old = sample == "195115"
    path = ROOT / f"tests/data/스크린샷 2026-10-{'09' if old else '18'} {sample}.png"
    image = image_io.imread(path)
    # Keep the registered region identical for the old control and new live image.
    box = (1018, 1248, 521, 37)
    watcher = SimpleNamespace(is_game_active=lambda: True, is_self_active=lambda: False)
    tab = BossTab(watcher)
    tab._timer.stop()
    tab._region = dict(zip(("x", "y", "w", "h"), box))
    screen = SimpleNamespace(geometry=lambda: SimpleNamespace(height=lambda: image.shape[0]))
    monkeypatch.setattr(QGuiApplication, "primaryScreen", lambda: screen)
    monkeypatch.setattr(dpi, "to_physical", lambda reg: tuple(reg[key] for key in ("x", "y", "w", "h")))
    monkeypatch.setattr(tab, "_grab_rect", lambda *actual: crop(image, actual))
    sounds = []
    monkeypatch.setattr(tab, "_play", sounds.append)
    try:
        for _ in range(4):
            tab._tick()
        expected_hp = read_percent(crop(image, box)[:, int(box[2] * .58):])
        print(dict(sample=sample, hp_reader=expected_hp, boss=tab._cur_boss,
                   stable_hp=tab._stable_hp, raw_hp=tab._last_raw_hp,
                   tracker=tab._tracker is not None, sounds=sounds))
        assert expected_hp is not None
        assert tab._cur_boss == "pellom"
        assert tab._tracker is not None
        assert tab._stable_hp == expected_hp
        assert tab._region == dict(zip(("x", "y", "w", "h"), box))
    finally:
        tab.shutdown()
        tab.close()
        assert app is not None


if __name__ == "__main__":
    import json
    cv2.setNumThreads(1)
    for stamp in SAMPLES:
        result, _, frame = inspect_sample(stamp)
        print(json.dumps(result, ensure_ascii=False))
        image_io.imwrite(Path(f"/tmp/qa-pellom-{stamp}.png"), frame)
