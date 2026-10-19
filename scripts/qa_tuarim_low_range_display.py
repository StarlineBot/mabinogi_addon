"""Replay missing tens digits while preserving the existing safe 100% hold."""

from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile
import sys

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads
from mabinogi_addon import config, image_io
from mabinogi_addon.detect import tuarim_reader as reader

CASES = (("v06_7466.png", 16), ("v06_7465.png", 16),
         ("v12_179.png", 12), ("v14_183.png", 14), ("v18_197.png", 18),
         ("v16_192.png", 16), ("v06_161.png", 6))


def sample(name):
    if name in ("v06_7466.png", "v06_7465.png"):
        with ZipFile(ROOT / "tests/data/raw_7603.zip") as archive:
            image = cv2.imdecode(np.frombuffer(archive.read(name), np.uint8), cv2.IMREAD_COLOR)
    else:
        image = image_io.imread(ROOT / "tests/data/tuarim_shots" / name)
    assert image is not None
    return image


def hundred():
    image = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-09 185117.png")
    assert image is not None
    return image[920:936, 742:784]


def trace(image):
    v = reader._prep(image)
    binary = reader._binarize(v)
    columns = np.flatnonzero(binary.any(axis=0))
    right = int(columns[-1])
    Ro, Lo, Rt, Lt = reader._REFS
    options = []
    for r in range(right, max(right - reader._R_SCAN, 1), -1):
        digit, score = reader._classify(reader._norm(reader._cell(v, r, reader._ONES)), Ro, Lo)
        options.append((score, r, digit))
    ones_score, r, ones = max(options)
    tens, tens_score = reader._classify(reader._norm(reader._cell(v, r, reader._TENS)), Rt, Lt)
    ink = int((binary[:, max(0, r - 25):max(0, r - 17)] > 0).sum())
    return dict(right=r, ones=ones, ones_score=ones_score, tens=tens,
                tens_score=tens_score, tens_ink=ink, actual=reader.read_percent(image))


@pytest.mark.parametrize("name,expected", CASES)
def test_low_range_word_keeps_visible_tens(name, expected):
    image = sample(name)
    assert reader.read_percent(image) == expected, trace(image)


@pytest.fixture
def pipeline(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from mabinogi_addon.ui import dpi
    from mabinogi_addon.ui.tuarim_tab import TuarimTab
    from mabinogi_addon.ui.dorcha_tab import DorchaTab
    from mabinogi_addon.ui.resource_tab import ResourceTab

    app = QApplication.instance() or QApplication([])
    from mabinogi_addon.feature_access import CREATOR_DISCORD_ID
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": CREATOR_DISCORD_ID})
    watcher = SimpleNamespace(is_game_active=lambda: True, is_self_active=lambda: False)
    t, d = TuarimTab(watcher), DorchaTab(watcher)
    panel = ResourceTab(d, t)
    t._timer.stop()
    d._timer.stop()
    t.enable.setChecked(False)
    d.enable.setChecked(False)
    assert d._alpha_ready and not panel.percent_chk.isChecked()
    panel.percent_chk.setChecked(True)
    assert panel.percent_chk.isChecked() and d.percent_requested()
    current = [None]
    monkeypatch.setattr(dpi, "to_physical", lambda region: tuple(region[k] for k in ("x", "y", "w", "h")))
    monkeypatch.setattr(t, "_grab_rect", lambda *args: current[0])
    sounds = []
    monkeypatch.setattr(t, "_play", sounds.append)

    def pump(image):
        current[0] = image
        t._region = dict(x=0, y=0, w=image.shape[1], h=image.shape[0])
        for _ in range(3):
            t._tick_enabled()
        assert d._overlay is not None and d._overlay.isVisible()
        assert sounds == []
        return dict(raw=t._last_value, stable=t._stable_value,
                    overlay=d._overlay.percent, label=d.value_label.text())

    try:
        yield pump, d
    finally:
        t.shutdown()
        d.shutdown()
        panel.close()
        panel.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("name,expected", (("v06_7466.png", 16), ("v14_183.png", 14),
                                          ("v16_192.png", 16), ("v06_161.png", 6)))
def test_real_reader_value_reaches_percent_overlay(pipeline, name, expected):
    pump, _ = pipeline
    result = pump(sample(name))
    assert result["overlay"] == expected, result


def test_existing_full_percent_contract_remains_safe(pipeline):
    pump, _ = pipeline
    assert reader.read_percent(hundred()) is None
    result = pump(hundred())
    assert result["overlay"] is None and "--%" in result["label"], result


