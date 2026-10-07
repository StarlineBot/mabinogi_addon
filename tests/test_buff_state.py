from mabinogi_addon.tracker import BuffStateMachine, Event, State


def _appear(sm, reading=100.0, t0=0.0):
    """appear_frames만큼 연속 감지시켜 ACTIVE로."""
    ev = None
    for i in range(sm.appear_frames):
        ev = sm.observe(detected=True, reading=reading, now=t0 + i * 0.2)
    return ev


def test_appears_after_n_frames():
    sm = BuffStateMachine(appear_frames=3)
    assert sm.observe(detected=True, reading=100, now=0.0) is Event.NONE
    assert sm.state is State.ABSENT
    assert sm.observe(detected=True, reading=100, now=0.2) is Event.NONE
    assert sm.observe(detected=True, reading=100, now=0.4) is Event.APPEARED
    assert sm.state is State.ACTIVE


def test_internal_clock_counts_down():
    sm = BuffStateMachine()
    _appear(sm, reading=100, t0=0.0)
    # 마지막 판독 100 @0.4 → 10초 뒤 약 90.4 남음
    assert abs(sm.remaining(10.4) - 90.0) < 0.01


def test_resume_after_inactive_gap_keeps_state_and_clock():
    """게임 비활성(관측 끊김) 동안 상태 동결·내부 시계 유지 → 복귀 시 정상.

    비활성 중엔 observe()가 아예 호출되지 않으므로 상태는 그대로이고,
    복귀하면 실제 경과시간(monotonic)만큼 줄어든 남은 시간이 그대로 이어진다.
    """
    sm = BuffStateMachine(appear_frames=3)
    _appear(sm, reading=100, t0=0.0)  # 100초 버프, @0.4 활성
    assert sm.state is State.ACTIVE

    # --- 여기서 60초간 '잠깐 쉼'(관측 없음, 시계만 흐름) ---
    # 복귀: 화면에 버프가 그대로 있으면 신선한 판독값으로 재탐지
    ev = sm.observe(detected=True, reading=40, now=60.4)
    assert ev is Event.NONE  # 이미 ACTIVE 유지
    assert sm.state is State.ACTIVE
    assert abs(sm.remaining(60.4) - 40.0) < 0.01


def test_buff_expires_while_inactive_then_removed_on_return():
    """비활성 동안 수명이 다한 버프는 복귀 후 미감지 1프레임에 즉시 만료."""
    sm = BuffStateMachine(appear_frames=3)
    _appear(sm, reading=5, t0=0.0)  # 5초 버프
    # 10초 쉬고 복귀 → 화면엔 이미 사라짐 + 내부 시계 소진 → 즉시 EXPIRED
    assert sm.observe(detected=False, reading=None, now=10.4) is Event.EXPIRED
    assert sm.state is State.ABSENT


def test_second_alert_fires_once_and_rearms_on_extension():
    sm = BuffStateMachine(alert_before=30, alert_before2=20)
    _appear(sm, reading=100, t0=0.0)
    # 아직 2차 기준(20초) 위 → 안 울림
    assert sm.check_second_alert(10.4) is False  # remaining ~90
    sm.observe(detected=True, reading=18, now=11.0)  # 18초로 판독
    assert sm.check_second_alert(11.0) is True  # 20초 이하 교차 → 1회
    assert sm.check_second_alert(12.0) is False  # 재알림 없음
    # 연장(80초로) → 2차 재무장
    sm.observe(detected=True, reading=80, now=13.0)
    assert sm.check_second_alert(13.0) is False  # remaining 80 > 20
    sm.observe(detected=True, reading=15, now=14.0)
    assert sm.check_second_alert(14.0) is True  # 다시 1회


def test_no_second_alert_when_disabled():
    sm = BuffStateMachine(alert_before=30, alert_before2=None)
    _appear(sm, reading=10, t0=0.0)
    assert sm.check_second_alert(1.0) is False


def test_alert_fires_once_at_threshold():
    sm = BuffStateMachine(alert_before=30)
    _appear(sm, reading=100, t0=0.0)
    # 남은시간 25로 판독 → 임박 진입(점멸+소리)
    assert sm.observe(detected=True, reading=25, now=1.0) is Event.ALERT
    assert sm.state is State.EXPIRING
    # 계속 줄어도 재알림 없음
    assert sm.observe(detected=True, reading=24, now=2.0) is Event.NONE


def test_extension_clears_alert():
    sm = BuffStateMachine(alert_before=30)
    _appear(sm, reading=100, t0=0.0)
    sm.observe(detected=True, reading=25, now=1.0)  # ALERT
    # 다시 판독값이 크게 늘면 연장
    assert sm.observe(detected=True, reading=120, now=2.0) is Event.EXTENDED
    assert sm.state is State.ACTIVE


def test_expired_when_clock_zero_and_missing():
    sm = BuffStateMachine()
    _appear(sm, reading=2, t0=0.0)
    # 내부시계 소진 후 미감지 → 만료
    assert sm.observe(detected=False, reading=None, now=5.0) is Event.EXPIRED
    assert sm.state is State.ABSENT


def test_mid_release_when_missing_long_enough():
    sm = BuffStateMachine(disappear_sec=2.0)
    _appear(sm, reading=100, t0=0.0)
    assert sm.observe(detected=False, reading=None, now=1.0) is Event.NONE
    # 2초 이상 연속 미감지(시간 남았는데) → 중간 해제
    assert sm.observe(detected=False, reading=None, now=3.0) is Event.RELEASED
    assert sm.state is State.ABSENT


def test_frozen_on_invalid_frame():
    sm = BuffStateMachine(disappear_sec=2.0)
    _appear(sm, reading=100, t0=0.0)
    # 판정 불가: 미감지여도 사라짐 처리 안 함(내부 시계는 아직 양수)
    for t in (1.0, 5.0, 10.0):
        assert sm.observe(detected=False, reading=None, now=t, frame_valid=False) is Event.NONE
    assert sm.state is State.ACTIVE


def test_frozen_clock_expires_when_zero():
    """판정 불가(앵커 오래 안 보임) 중에도 내부 시계가 0에 닿으면 만료·제거.

    시간 경과는 화면과 무관한 사실 → 동결 원칙을 깨지 않는다. 다시 보일 때
    버프가 살아 있으면 재감지로 다시 뜬다.
    """
    sm = BuffStateMachine(appear_frames=3, alert_before=2)
    _appear(sm, reading=5, t0=0.0)  # 5초 버프, @0.4 활성(알림 기준 2초라 ACTIVE 유지)
    assert sm.state is State.ACTIVE
    # 앵커가 계속 안 보이는 동안(frame_valid=False) 시계만 흐름
    assert sm.observe(detected=False, reading=None, now=3.0, frame_valid=False) is Event.NONE
    assert sm.state is State.ACTIVE
    # 시계 소진(5초 경과) → 화면을 못 봐도 만료 처리
    assert sm.observe(detected=False, reading=None, now=6.0, frame_valid=False) is Event.EXPIRED
    assert sm.state is State.ABSENT


def test_duration_less_buff_never_alerts():
    sm = BuffStateMachine()
    # 판독값 없는(무기한) 버프: 앵커/시간없는 그룹
    for i in range(5):
        sm.observe(detected=True, reading=None, now=i * 0.2)
    assert sm.state is State.ACTIVE
    assert sm.remaining(100.0) is None
    assert not sm.alerting
