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
    # 판정 불가: 미감지여도 사라짐 처리 안 함
    for t in (1.0, 5.0, 10.0):
        assert sm.observe(detected=False, reading=None, now=t, frame_valid=False) is Event.NONE
    assert sm.state is State.ACTIVE


def test_duration_less_buff_never_alerts():
    sm = BuffStateMachine()
    # 판독값 없는(무기한) 버프: 앵커/시간없는 그룹
    for i in range(5):
        sm.observe(detected=True, reading=None, now=i * 0.2)
    assert sm.state is State.ACTIVE
    assert sm.remaining(100.0) is None
    assert not sm.alerting
