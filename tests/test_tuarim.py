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


# ---- 트래커 (임계 도달 = level + 리셋 기반 재무장) ----
# 실게임 데이터상 게이지가 저값→90대로 '점프'하듯 차서(완만한 상승이 캡처에 안 잡힘),
# 옛 edge 방식은 한 번도 안 울렸다. 그래서 '임계에 FIRE_FRAMES 연속 도달하면 1회' 방식.
def test_level_fires_on_reaching_threshold():
    t = TuarimTracker([95, 98])
    assert t.observe(94) == []
    assert t.observe(95) == []  # 1프레임만으론 아직(단발 오독 방지)
    assert t.observe(96) == [95]  # 95 이상 2연속 → 95 도달 발화
    assert t.observe(97) == []  # 95는 이미 울림(재무장 전까지 억제)
    assert t.observe(98) == []  # 98 1프레임
    assert t.observe(99) == [98]  # 98 이상 2연속 → 98 발화


def test_jump_into_threshold_fires():
    """게이지가 점프하듯 차올라도(저값→90대) 도달하면 울린다(옛 edge는 못 울렸음)."""
    t = TuarimTracker([90])
    assert t.observe(10) == []
    assert t.observe(99) == []  # 점프 직후 1프레임
    assert t.observe(99) == [90]  # 2연속 90+ → 발화


def test_single_spike_does_not_fire():
    """임계 이상이 단 1프레임(오독 고값)이면 울리지 않는다(FIRE_FRAMES=2)."""
    t = TuarimTracker([90])
    assert t.observe(50) == []
    assert t.observe(99) == []  # 단발 스파이크
    assert t.observe(50) == []


def test_transient_low_does_not_rearm():
    """울린 뒤 한두 틱 오독 급락(10)이 끼어도 재무장 안 됨 → 같은 주기에 또 안 울린다."""
    t = TuarimTracker([90])
    assert t.observe(95) == []
    assert t.observe(95) == [90]  # 2연속 → 발화
    assert t.observe(10) == []  # 오독 급락 1틱(리셋 아님)
    assert t.observe(95) == []  # 아직 억제(재무장 안 됨)
    assert t.observe(95) == []


def test_refires_next_cycle_after_sustained_reset():
    """게이지가 실제로 0 근처까지 내려가 리셋되면(저값 연속) 다음 주기에 다시 울린다."""
    from mabinogi_addon.tracker.tuarim import REARM_FRAMES, REARM_VALUE

    t = TuarimTracker([95])
    t.observe(95)
    assert t.observe(95) == [95]  # 1주기 발화
    for _ in range(REARM_FRAMES):  # 0 근처 연속 → 리셋 → 재무장
        t.observe(REARM_VALUE - 5)
    assert t.observe(96) == []
    assert t.observe(96) == [95]  # 다음 주기 재발화


def test_hold_at_100_does_not_refire():
    """100%에서 영역이 '100'을 잘라 판독이 80/60/90/100으로 요동해도(0 근처가 아님),
    재무장되지 않아 같은 주기에 다시 울리지 않는다(릴리즈 전 회귀 — 클립된 100% 거짓 재알림).

    노이즈에 0 근처(≤REARM_VALUE) 단발이 섞여도 REARM_FRAMES 연속이 아니면 재무장 안 됨."""
    t = TuarimTracker([90, 95])
    for v in range(88, 100):  # 완만히 올라 90·95 도달(1주기 발화)
        t.observe(v)
    fired_hold = []
    # 100% 유지 중 클립 요동 — 60·80·90·100 + 단발 저값(4). 0 근처 연속이 아니다.
    for v in [80, 4, 100, 60, 80, 100, 90, 80, 90, 100, 80, 60, 80, 100] * 5:
        fired_hold += t.observe(v)
    assert fired_hold == [], f"100% 유지 중 재발화: {fired_hold}"


def test_small_dip_within_hysteresis_does_not_rearm():
    """임계 바로 아래로 조금만 내려갔다 다시 올라도 재무장 안 됨(같은 주기)."""
    t = TuarimTracker([95])
    t.observe(95)
    assert t.observe(95) == [95]
    for v in [90, 90, 90, 90, 90]:  # 95-10=85보다 위 → 리셋 아님
        assert t.observe(v) == []
    assert t.observe(95) == []
    assert t.observe(95) == []  # 여전히 억제


def test_none_value_is_skipped():
    t = TuarimTracker([95])
    assert t.observe(95) == []
    assert t.observe(None) == []  # 판독 실패/보류는 상태 변화 없이 건너뜀
    assert t.observe(95) == [95]  # None 무시, 95 2연속 → 발화


# ---- 리더+트래커 통합 회귀: 실세션 전체 재생(수집 2926장) → 알림은 정확히 2회만 ----
# (전투 내내 게이지가 여러 번 차고 100% 유지되지만, 진짜로 임계를 '처음 넘는' 2회만 울려야
#  한다. 100% 클립 요동·빈배경 오독으로 인한 거짓 재알림이 없어야 한다.)
import re as _re  # noqa: E402
import zipfile as _zip  # noqa: E402

_TUARIM_SESSION_ZIP = Path(__file__).parent / "data" / "raw_7603.zip"


def test_full_session_replay_fires_exactly_twice():
    if not _TUARIM_SESSION_ZIP.exists():
        pytest.skip("세션 zip 없음")
    with _zip.ZipFile(_TUARIM_SESSION_ZIP) as z:
        names = [n for n in z.namelist() if _re.match(r"(raw|v\d+)_\d+\.png", n)]
        names.sort(key=lambda n: int(_re.search(r"_(\d+)\.png", n).group(1)))
        reads = []
        for n in names:
            img = cv2.imdecode(np.frombuffer(z.read(n), np.uint8), cv2.IMREAD_COLOR)
            reads.append(read_percent(img))
    t = TuarimTracker([90, 95])
    fired = []
    for v in reads:
        fired += t.observe(v)
    assert fired == [90, 95], f"거짓 알림/누락: {fired}"


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


# ---- 리더 R 자동정렬: 전투 이펙트로 '%' 끝이 밀려 고게이지(98/95)를 한 자릿수(3/5)로
#      오독하던 회귀. 실프레임 crop(수집모드)에서 이제 두 자리로 바르게 읽혀야 한다. ----
import zipfile  # noqa: E402

_TUARIM_ZIP = Path(__file__).parent / "data" / "raw_7603.zip"
# (zip 내 파일, 화면 실제값) — 전투 이펙트로 배경이 밝은 프레임. 옛 리더는 3/5로 오독했다.
_FLOODED_HIGH = [("v03_6904.png", 98), ("v03_6905.png", 98), ("v05_6823.png", 95)]


@pytest.mark.parametrize("entry,real", _FLOODED_HIGH)
def test_reads_high_gauge_despite_bright_bg(entry, real):
    if not _TUARIM_ZIP.exists():
        pytest.skip("데이터 zip 없음")
    with zipfile.ZipFile(_TUARIM_ZIP) as z:
        buf = np.frombuffer(z.read(entry), np.uint8)
    crop = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    assert crop is not None, entry
    got = read_percent(crop)
    # 핵심: 고게이지를 낮은 한 자릿수로 오독하지 않는다(옛 버그 3/5 재발 방지).
    assert got is not None and got >= 90, f"{entry}: 실제 {real}인데 {got}로 오독"


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
