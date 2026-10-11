"""투아림 트래커 + % 리더 + config 테스트."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from mabinogi_addon import config
from mabinogi_addon.detect.tuarim_reader import read_percent
from mabinogi_addon.tracker import TuarimTracker

_SAMPLES = Path(__file__).parent / "data" / "tuarim_samples"
_HI = Path(__file__).parent / "data" / "tuarim_hi"


@pytest.mark.parametrize("value", list(range(90, 100)) + [85, 89])
def test_read_percent_high_range(value):
    """실게임 캡처(밝은 게이지 배경)에서 90%대와 경계를 정확히 판독한다.

    투아림 트래커의 목적이 100% 직전(90%대)에 쿨 초기화 스킬을 터는 것이라,
    90~99 + 89/90 경계 판독이 핵심이다. NCC 레퍼런스 뱅크(refs.npz) 기반.
    """
    img = cv2.imread(str(_HI / f"{value:02d}.png"))
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


def test_boundary_jitter_fires_once():
    """임계 경계(95%)에서 판독값이 흔들려도(94→95→94→95) 한 번만 울린다.
    (배포판에서 '95%에 두세 번 울리던' 문제 회귀 방지 — 재무장 전까지 억제.)"""
    t = TuarimTracker([95, 98])
    fired = []
    for v in [93, 94, 95, 94, 95, 96, 95, 96, 95]:
        fired += t.observe(v)
    assert fired == [95]  # 흔들려도 95는 한 번만


def test_small_dip_within_hysteresis_does_not_rearm():
    """임계 바로 아래로 조금만 내려갔다 다시 오르는 건 재무장 안 됨(같은 주기)."""
    t = TuarimTracker([95])
    assert t.observe(94) == []
    assert t.observe(95) == [95]
    assert t.observe(90) == []  # 95-10=85보다 위 → 재무장 안 함
    assert t.observe(94) == []
    assert t.observe(95) == []  # 여전히 억제


def test_none_value_keeps_prev():
    t = TuarimTracker([95])
    assert t.observe(94) == []
    assert t.observe(None) == []  # 판독 실패는 직전 값 유지
    assert t.observe(95) == [95]  # 94→95 교차(None 틱 건너뜀)


# ---- % 리더 ----
def test_read_percent_none_on_blank():
    """빈(검은) 영역은 판독 불가 → None."""
    assert read_percent(np.zeros((13, 28, 3), dtype=np.uint8)) is None


def test_reader_tracker_fires_at_90_and_95():
    """실캡처 90~99 프레임을 순서대로 읽어 트래커(임계 90·95)에 흘리면,
    90·95를 각각 정확히 한 번 넘는다(놓침·거짓발동 없음). 판독기+트래커 결합 회귀."""
    t = TuarimTracker([90, 95])
    fired = []
    for value in [88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99]:
        img = cv2.imread(str(_HI / f"{value:02d}.png"))
        if img is None:
            continue
        fired += t.observe(read_percent(img))
    assert fired == [90, 95]


# ---- config ----
def test_tuarim_config_defaults(tmp_path):
    p = tmp_path / "config.local.json"
    d = config.load_tuarim(p)
    assert d["enabled"] is False
    assert d["thresholds"] == [90, 95]
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


@pytest.mark.parametrize(
    "name",
    [
        "v01_124.png",  # 실제 "1%"
        "v01_151.png",  # 실제 "4%"
        "v05_155.png",  # 실제 "5%"
        "v08_172.png",  # 실제 "8%"
        "v00_113.png",  # 실제 "0%"
        "v06_159.png",  # 실제 "6%"
    ],
)
def test_single_digit_not_given_spurious_tens(name):
    """한 자리 값에 게이지·배경 잡음이 '십의 자리'로 붙어 9X처럼 읽혀 거짓 투아림
    알림이 나던 버그 회귀 방지(예: 5%→95%). 한 자리는 한 자리(<10)로 읽혀야 한다.
    (십의 자리는 NCC>=0.6을 요구 — 진짜 십의 자리는 ~1.0, 잡음은 <=0.49)"""
    shots = Path(__file__).parent / "data" / "tuarim_shots"
    p = shots / name
    if not p.exists():
        pytest.skip(f"샘플 없음: {name}")
    got = read_percent(cv2.imread(str(p)))
    assert got is None or got < 10, f"{name}: 한 자리인데 {got}로 읽힘(가짜 십의 자리)"
