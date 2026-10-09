"""보스 패턴 트래커: 하강 교차 2단 경고 + 재무장 (기획서 12)."""

from mabinogi_addon.tracker.boss_pattern import BossPatternTracker


def _fire(tracker, seq):
    """HP 시퀀스를 흘려보내 (threshold, stage) 발동 목록을 모은다."""
    got = []
    for hp in seq:
        got += [(a.threshold, a.stage) for a in tracker.observe(hp)]
    return got


def test_two_stage_fire_on_crossing():
    t = BossPatternTracker("고목의 페타크", [85])
    # 95 → ... → 84. 90(=85+5) 통과 시 pre, 86(=85+1) 통과 시 near.
    got = _fire(t, [95, 91, 89, 87, 85])
    assert got == [(85, "pre"), (85, "near")]


def test_message_text_and_sound():
    t = BossPatternTracker("고목의 페타크", [85])
    t.observe(95)
    alerts = t.observe(89)  # 90 통과 → pre
    assert len(alerts) == 1
    assert alerts[0].text == "고목의 페타크 85% 패턴 준비"
    assert alerts[0].sound == "pre"


def test_near_fires_at_threshold_plus_one_not_at_threshold():
    """임박(near)은 임계+1(예 81)에 도달할 때 떠야 한다 — 임계(80, 패턴 시작점)에서
    뜨면 늦다. (보스 HP는 임계에서 고정되므로 반드시 '전'에)"""
    t = BossPatternTracker("레넨의 미이르", [80])  # near 지점 81
    t.observe(83)
    assert t.observe(82) == []  # 아직 82 — near 미발동
    near = t.observe(81)  # 81 도달 → 발동
    assert [(a.threshold, a.stage) for a in near] == [(80, "near")]
    assert t.observe(80) == []  # 80(고정점)에선 재발동 없음


def test_no_fire_on_first_observe():
    t = BossPatternTracker("보스", [85])
    assert t.observe(80) == []  # 직전값 없음 → 교차 판정 불가


def test_rearm_after_phase_reset():
    t = BossPatternTracker("보스", [85])
    _fire(t, [95, 84])  # 90·86 둘 다 통과 → pre+near 발동
    # 페이즈 리셋: HP 100으로 복귀 → 재무장 → 다시 하강하면 또 발동
    got = _fire(t, [100, 84])
    assert got == [(85, "pre"), (85, "near")]


def test_no_double_fire_while_below():
    t = BossPatternTracker("보스", [85])
    _fire(t, [95, 84])  # 발동
    # 계속 아래에서 오르내려도(재무장 지점 위로 안 오르면) 재발동 없음
    assert _fire(t, [83, 85, 83]) == []


def test_multiple_thresholds():
    t = BossPatternTracker("보스", [85, 35])
    got = _fire(t, [100, 84, 50, 34])
    # 85: 90·86 통과(위에서) → pre,near / 35: 40·36 통과 → pre,near
    assert got == [(85, "pre"), (85, "near"), (35, "pre"), (35, "near")]


def test_none_reading_ignored():
    t = BossPatternTracker("보스", [85])
    t.observe(95)
    assert t.observe(None) == []  # 판독 실패 프레임 무시
    assert _fire(t, [89]) == [(85, "pre")]  # 직전 95 유지 → 정상 교차
