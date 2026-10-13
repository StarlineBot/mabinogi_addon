"""보스 패턴 트래커: 구간(band) 기반 2단 경고 + 급락 가드 + 재무장 (기획서 12).

사양: 준비 [T+3,T+5], 임박 [T+1,T+2]. 구간 안 1회, 구간 밖/판독값 T 이하 0,
직전−현재 > 8 급락은 판정 제외(오독 방어).
"""

import os
import re
import zipfile

import cv2
import numpy as np
import pytest

from mabinogi_addon.tracker.boss_pattern import BossPatternTracker


def _fire(tracker, seq):
    """HP 시퀀스를 흘려 (threshold, stage) 발동 목록을 모은다."""
    got = []
    for hp in seq:
        got += [(a.threshold, a.stage) for a in tracker.observe(hp)]
    return got


def test_pre_fires_within_band():
    t = BossPatternTracker("보스", [50])
    assert t.observe(56) == []  # 56 > 55 → 준비 구간[53,55] 위
    assert [(a.threshold, a.stage) for a in t.observe(54)] == [(50, "pre")]  # 54 ∈ [53,55]


def test_near_fires_within_band_not_at_or_below_T():
    t = BossPatternTracker("보스", [50])
    t.observe(54)  # 준비
    assert t.observe(53) == []  # 아직 임박 구간[51,52] 위
    assert [(a.threshold, a.stage) for a in t.observe(52)] == [(50, "near")]  # 52 ∈ [51,52]


def test_no_fire_at_T_or_below():
    """판독값 T(50) 이하에서는 임박이 울리지 않는다(구간이 T+1부터)."""
    t = BossPatternTracker("보스", [50])
    t.observe(54)  # 준비만
    got = _fire(t, [50, 49, 40])  # T 및 그 이하 — 임박 없음
    assert got == []


def test_band_fires_once_anywhere_inside():
    """구간 안 여러 프레임이어도 1회만."""
    t = BossPatternTracker("보스", [50])
    assert len(t.observe(55)) == 1  # 준비 1회
    assert t.observe(54) == []  # 같은 구간 재발동 없음
    assert t.observe(53) == []


def test_skipped_band_is_omitted():
    """준비 구간을 (판독 공백으로) 건너뛰면 준비는 생략되고, 임박 구간만 울린다."""
    t = BossPatternTracker("보스", [50])
    assert t.observe(57) == []  # 준비[53,55] 위
    # 57 → 51 (낙폭 6 ≤ 8, 급락 가드 안 걸림): 준비[53,55]를 건너뜀, 51은 임박[51,52] 안
    got = [(a.threshold, a.stage) for a in t.observe(51)]
    assert got == [(50, "near")]  # 준비 생략, 임박만


def test_drop_guard_blocks_misread_into_other_band():
    """50%를 '5'로 오독(낙폭 >8)해도 5% 패턴 구간에 거짓 발동하지 않는다.
    (급락 가드 + 매 틱 같은 오독값이 반복돼도 — boss_tab 특성 — 울리지 않음.)"""
    t = BossPatternTracker("보스", [5, 50])
    t.observe(54)  # 50% 준비 발동(이후 _fire엔 안 잡힘)
    assert _fire(t, [5, 5, 5]) == []  # 5% 패턴 거짓 발동 없음


def test_drop_disarms_skipped_bands_repeated_misread():
    """48 확정 후 '18'로 오독된 값이 매 틱 반복돼도(boss_tab은 같은 확정 HP 반복) 15% 알림 0.
    (급락 시 건너뛴 구간을 무장 해제 → 2틱째부터 오독값이 구간에 들어가도 안 울림.)"""
    t = BossPatternTracker("보스", [15])
    got = _fire(t, [48, 18, 18, 18, 18])  # 48→18 급락, 이후 같은 18 반복
    assert got == []


def test_recovers_after_drop_misread():
    """48→18 오독으로 15% 구간이 무장 해제됐어도, 48로 복귀(재무장) 후 정상 하강하면
    15% 준비·임박이 각 1회 정상 발동한다."""
    t = BossPatternTracker("보스", [15])
    _fire(t, [48, 18, 18])  # 급락 오독 → 15% 무장 해제
    got = _fire(t, [48, 40, 32, 24, 20, 17])  # 복귀 재무장 후 ≤8 단계 하강
    assert got == [(15, "pre"), (15, "near")]


def test_big_drop_disarms_only_skipped_not_lower():
    """40→12 큰 하락: 건너뛴 25·15% 알림 0, 그 아래 5%는 정상 발동."""
    t = BossPatternTracker("보스", [5, 25, 15])
    got = _fire(t, [40, 12, 12, 10, 7])  # 40→12 급락(25·15 무장해제), 이후 5% 구간 하강
    assert (25, "pre") not in got and (25, "near") not in got
    assert (15, "pre") not in got and (15, "near") not in got
    assert got == [(5, "pre"), (5, "near")]


def test_rearm_above_band():
    t = BossPatternTracker("보스", [50])
    _fire(t, [54, 51])  # 준비+임박
    # 페이즈 리셋: 구간 위로 복귀 → 재무장 → 다시 구간 들어오면 또
    got = _fire(t, [60, 54, 51])
    assert got == [(50, "pre"), (50, "near")]


def test_none_ignored():
    t = BossPatternTracker("보스", [50])
    assert t.observe(None) == []
    assert [(a.threshold, a.stage) for a in t.observe(54)] == [(50, "pre")]


def test_message_text_and_sound():
    t = BossPatternTracker("고목의 페타크", [85])
    a = t.observe(88)  # 88 ∈ [88,90] 준비
    assert len(a) == 1 and a[0].text == "고목의 페타크 85% 패턴 준비" and a[0].sound == "pre"


def test_multiple_thresholds_each_band():
    t = BossPatternTracker("보스", [85, 35])
    # 89(준비85) → 86(임박85) → 39(준비35) → 36(임박35). 낙폭은 ≤8로 유지.
    got = _fire(t, [90, 89, 86, 44, 39, 36])
    assert got == [(85, "pre"), (85, "near"), (35, "pre"), (35, "near")]


# ---- 다음 패턴 목록(upcoming) ----
def test_upcoming_lists_thresholds_below_hp_descending():
    t = BossPatternTracker("보스", [90, 60, 30])
    t.observe(100)
    assert t.upcoming(100) == [90, 60, 30]


def test_upcoming_drops_threshold_when_pre_fires():
    t = BossPatternTracker("보스", [90, 60, 30])
    t.observe(100)
    assert t.upcoming(100) == [90, 60, 30]
    t.observe(94)  # 94 ∈ [93,95] → 90 준비 발동 → 빠짐
    assert t.upcoming(94) == [60, 30]
    for hp in [86, 78, 70, 64]:  # ≤8 단계로 하강(급락 가드 안 걸리게)
        t.observe(hp)
    assert t.upcoming(64) == [30]  # 64 ∈ [63,65] → 60 준비 → 빠짐


def test_upcoming_excludes_thresholds_above_current_hp():
    t = BossPatternTracker("보스", [90, 60, 30])
    t.observe(50)
    assert t.upcoming(50) == [30]


def test_upcoming_rearms_on_phase_reset():
    t = BossPatternTracker("보스", [90, 60])
    t.observe(100)
    t.observe(94)
    assert t.upcoming(94) == [60]
    t.observe(100)  # 리셋 → 재무장
    assert t.upcoming(100) == [90, 60]


def test_upcoming_holds_last_on_none():
    t = BossPatternTracker("보스", [90, 60])
    t.observe(100)
    assert t.upcoming(100) == [90, 60]
    assert t.upcoming(None) == [90, 60]


# ---- 실세션 재생 회귀: 모든 알림이 구간 안, 구간 밖 0, T 이하 0 ----
_ZIP = "tests/data/eotgallin_poinche_hp004_115.zip"
_THRESHOLDS = [90, 75, 60, 40, 25, 15]


def _norm37(im):
    from mabinogi_addon.detect.boss_bar import normalize_box_height

    th = normalize_box_height((0, 0, im.shape[1], im.shape[0]), 1440)[3]
    top = (im.shape[0] - th) // 2
    return im[top : top + th]


def test_full_replay_alerts_all_in_band():
    from mabinogi_addon.detect.boss_hp_reader import read_percent

    if not os.path.exists(_ZIP):
        pytest.skip("데이터 zip 없음")
    with zipfile.ZipFile(_ZIP) as z:
        names = [n for n in z.namelist() if n.endswith(".png")]
        names.sort(key=lambda n: int(re.search(r"_(\d+)\.png", n).group(1)))
        reads = []
        for n in names:
            im = cv2.imdecode(np.frombuffer(z.read(n), np.uint8), cv2.IMREAD_COLOR)
            reads.append(read_percent(_norm37(im)))
    t = BossPatternTracker("포인셰", _THRESHOLDS)
    bands = {
        (T, "pre"): (T + 3, T + 5) for T in _THRESHOLDS
    } | {(T, "near"): (T + 1, T + 2) for T in _THRESHOLDS}
    fired = []
    for hp in reads:
        for a in t.observe(hp):
            fired.append((a.threshold, a.stage, hp))
    assert fired, "알림이 하나도 안 울림"
    for T, stage, hp in fired:
        lo, hi = bands[(T, stage)]
        assert lo <= hp <= hi, f"{T}% {stage} 구간[{lo},{hi}] 밖에서 발동: hp={hp}"
        assert hp > T, f"{T}% {stage}가 판독값 T 이하에서 발동: hp={hp}"
