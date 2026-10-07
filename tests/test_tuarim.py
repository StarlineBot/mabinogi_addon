"""투아림 트래커 + % 리더 + config 테스트."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from mabinogi_addon import config
from mabinogi_addon.detect.tuarim_reader import read_percent
from mabinogi_addon.tracker import TuarimTracker

_SAMPLES = Path(__file__).parent / "data" / "tuarim_samples"


@pytest.mark.parametrize(
    "value",
    [0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
)
def test_read_percent_on_real_samples(value):
    """실게임 수집 샘플(선명한 프레임)을 기본 템플릿으로 정확히 판독한다."""
    img = cv2.imread(str(_SAMPLES / f"{value:02d}.png"))
    assert img is not None
    assert read_percent(img) == value


# ---- 트래커 (완만한 상승 교차 = edge) ----
def test_fires_on_gradual_crossing():
    t = TuarimTracker([95, 98])
    assert t.observe(93) == []  # 기준점
    assert t.observe(94) == []
    assert t.observe(95) == [95]  # 94→95 교차
    assert t.observe(96) == []
    assert t.observe(97) == []
    assert t.observe(98) == [98]  # 97→98 교차
    assert t.observe(99) == []


def test_reentry_jump_does_not_fire():
    """자리 비웠다 복귀로 값이 점프하면(이미 임계 이상) 울리지 않는다."""
    t = TuarimTracker([90])
    assert t.observe(85) == []
    assert t.observe(93) == []  # 85→93 점프 → 교차 아님


def test_big_jump_does_not_fire():
    t = TuarimTracker([95, 98])
    assert t.observe(10) == []
    assert t.observe(99) == []  # 큰 점프는 교차로 보지 않음


def test_misread_drop_recovery_does_not_fire():
    """90%대에서 한 틱 급락 후 복구돼도(큰 하강→큰 상승) 울리지 않는다."""
    t = TuarimTracker([90])
    assert t.observe(91) == []
    assert t.observe(92) == []
    assert t.observe(10) == []  # 오탐 급락
    assert t.observe(92) == []  # 10→92 급등 → 교차 아님


def test_refires_next_cycle_after_reset():
    t = TuarimTracker([95])
    assert t.observe(94) == []
    assert t.observe(95) == [95]
    assert t.observe(1) == []  # 리셋(급락)
    assert t.observe(94) == []  # 급등 구간은 무음
    assert t.observe(95) == [95]  # 94→95 완만 교차 → 다음 주기 재발동


def test_none_value_keeps_prev():
    t = TuarimTracker([95])
    assert t.observe(94) == []
    assert t.observe(None) == []  # 판독 실패는 직전 값 유지
    assert t.observe(95) == [95]  # 94→95 교차(None 틱 건너뜀)


# ---- % 리더 ----
def _digit(rows: list[str]) -> np.ndarray:
    """'.'/'#' 문자열 리스트 → 이진(0/255) 템플릿."""
    return np.array(
        [[255 if c == "#" else 0 for c in r] for r in rows], dtype=np.uint8
    )


def test_read_percent_none_without_templates():
    region = np.zeros((16, 40, 3), dtype=np.uint8)
    assert read_percent(region, templates={}) is None
    assert read_percent(region) is None  # 번들 템플릿 아직 없음


def test_read_percent_reads_two_digits():
    one = _digit(["..##..", "..##..", "..##..", "..##..", "..##..", "..##.."])
    three = _digit(["####..", "....#.", "..##..", "....#.", "....#.", "####.."])
    templates = {"1": one, "3": three}
    region = np.zeros((12, 40, 3), dtype=np.uint8)
    region[3:9, 4:10, :] = one[:, :, None]
    region[3:9, 22:28, :] = three[:, :, None]
    assert read_percent(region, templates=templates, threshold=0.6) == 13


# ---- config ----
def test_tuarim_config_defaults(tmp_path):
    p = tmp_path / "config.local.json"
    d = config.load_tuarim(p)
    assert d["enabled"] is False
    assert d["thresholds"] == [95, 98]
    assert d["sounds"] == [True, True]
    assert d["box"] is None


def _make_tab(monkeypatch, reads):
    """읽기값 시퀀스(reads)를 돌려주는 가짜 리더로 TuarimTab을 구성."""
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from mabinogi_addon.ui import tuarim_tab as mod

    seq = list(reads)
    monkeypatch.setattr(mod, "read_percent", lambda _f: seq.pop(0) if seq else None)

    class W:
        def is_game_active(self):
            return True

        def is_self_active(self):
            return False

    tab = mod.TuarimTab(W())
    tab._region = {"x": 0, "y": 0, "w": 28, "h": 13}
    tab._grab_rect = lambda *a: np.zeros((13, 28, 3), np.uint8)
    tab._tracker = TuarimTracker([70])
    tab.enable.setChecked(True)
    fired = []
    tab._play = lambda t: fired.append(t)
    return tab, fired, len(reads)


def test_single_misread_spike_does_not_fire(monkeypatch):
    """65 유지 중 한 프레임만 71로 오탐 → 임계 70 알림이 울리면 안 된다."""
    tab, fired, n = _make_tab(monkeypatch, [65, 65, 71, 65, 65, 65])
    for _ in range(n):
        tab._tick()
    tab.shutdown()
    assert fired == []


def test_genuine_crossing_fires_once(monkeypatch):
    """69→70으로 올라가면(확정) 임계 70이 정확히 한 번만 울린다."""
    tab, fired, n = _make_tab(monkeypatch, [69, 69, 70, 70, 71, 71])
    for _ in range(n):
        tab._tick()
    tab.shutdown()
    assert fired == [70]


def test_tuarim_config_roundtrip(tmp_path):
    p = tmp_path / "config.local.json"
    config.save_tuarim(
        {"enabled": True, "box": {"x": 1, "y": 2, "w": 3, "h": 4, "locked": True},
         "thresholds": [90, 97], "sounds": [True, False]},
        p,
    )
    d = config.load_tuarim(p)
    assert d["enabled"] is True
    assert d["box"]["w"] == 3
    assert d["thresholds"] == [90, 97]
    assert d["sounds"] == [True, False]
