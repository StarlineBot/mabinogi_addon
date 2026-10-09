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


def test_second_alert_fires_once_then_rearms_on_extension():
    """2차 알림은 한 '수명' 동안 1회만. 단, **연장이 확정되면 재무장**되어 다음
    임박에 다시 울린다(상시 유지 버프를 갱신하면 다음 갱신 타이밍도 알려야 함).
    같은 순간의 중복(플리커)은 연장으로 확정되지 않아 재무장되지 않는다."""
    sm = BuffStateMachine(alert_before=30, alert_before2=20)
    _appear(sm, reading=100, t0=0.0)
    assert sm.check_second_alert(10.4) is False  # remaining ~90, 아직 위
    sm.observe(detected=True, reading=18, now=82.0)  # remaining ~18
    assert sm.check_second_alert(82.0) is True  # 20초 이하 교차 → 1회
    assert sm.check_second_alert(83.0) is False  # 같은 수명에선 재알림 없음
    # 연장(80초로) 확정 → 2차 재무장
    sm.observe(detected=True, reading=80, now=84.0)
    sm.observe(detected=True, reading=80, now=84.2)  # 연장 확정
    assert sm.check_second_alert(84.2) is False  # remaining ~80, 아직 교차 전
    # 시계가 다시 15초에 도달 → 재무장됐으므로 2차 다시 울림
    sm.observe(detected=True, reading=15, now=149.2)
    assert sm.check_second_alert(149.2) is True  # 연장 후 다음 임박에 재알림


def test_no_second_alert_when_disabled():
    sm = BuffStateMachine(alert_before=30, alert_before2=None)
    _appear(sm, reading=10, t0=0.0)
    assert sm.check_second_alert(1.0) is False


def test_alert_fires_once_at_threshold():
    sm = BuffStateMachine(alert_before=30)
    _appear(sm, reading=100, t0=0.0)
    # 시계가 자연히 25초 부근 도달 → 판독 25가 시계와 일치 → 임박 진입(점멸+소리)
    assert sm.observe(detected=True, reading=25, now=75.0) is Event.ALERT
    assert sm.state is State.EXPIRING
    # 계속 줄어도 재알림 없음
    assert sm.observe(detected=True, reading=24, now=76.0) is Event.NONE


def test_extension_clears_alert():
    sm = BuffStateMachine(alert_before=30)
    _appear(sm, reading=100, t0=0.0)
    sm.observe(detected=True, reading=25, now=75.0)  # 시계 도달 → 임박(ALERT)
    assert sm.state is State.EXPIRING
    # 위로 튀는 판독은 한 프레임만으론 안 믿는다(오독 방지) → 다음 프레임에서
    # 이어질 때 비로소 연장으로 확정된다.
    assert sm.observe(detected=True, reading=120, now=75.2) is Event.NONE
    assert sm.state is State.EXPIRING  # 아직 확정 전 → 알림 유지
    assert sm.observe(detected=True, reading=120, now=75.4) is Event.EXTENDED
    assert sm.state is State.ACTIVE


def test_single_frame_upward_spike_does_not_clear_alert():
    """임박(≤30초) 중 한 프레임짜리 상향 오독('2분3초' 등)은 연장으로 오인되지
    않아야 한다. 오인되면 연장 알림이 꺼져 전행비 연장 타이밍을 놓친다(딜로스)."""
    sm = BuffStateMachine(alert_before=30)
    _appear(sm, reading=23, t0=0.0)  # 23초 → 임박
    assert sm.state is State.EXPIRING
    # 빨강 오독으로 한 프레임 123초(2분3초)로 튐 → 무시, 알림 유지
    assert sm.observe(detected=True, reading=123, now=0.6) is Event.NONE
    assert sm.state is State.EXPIRING
    assert sm.remaining(0.6) < 25  # 123으로 안 튐(내부 시계 23에서 감소)
    # 다음 프레임 다시 정상(22초) → 그대로 임박 유지
    assert sm.observe(detected=True, reading=22, now=0.8) is Event.NONE
    assert sm.state is State.EXPIRING
    assert sm.remaining(0.8) < 25


def test_single_frame_downward_spike_does_not_false_alert():
    """시간이 충분한데 밝은 배경 탓에 '분'을 놓쳐 수초로 읽히는 하향 오독은
    무시된다 → 거짓 임박 알림/시간 급락 방지(게임엔 2분20초인데 20초로 뜨는 문제)."""
    sm = BuffStateMachine(alert_before=30)
    _appear(sm, reading=140, t0=0.0)  # 2분20초 → 여유
    assert sm.state is State.ACTIVE
    # 한 프레임 '20초'로 오독(분 유실) → 무시, 시계 유지, 거짓 임박 없음
    assert sm.observe(detected=True, reading=20, now=1.0) is Event.NONE
    assert sm.state is State.ACTIVE
    assert sm.remaining(1.0) > 130  # 20으로 안 떨어짐
    # 다음 프레임 정상(139) → 그대로 유지
    assert sm.observe(detected=True, reading=139, now=1.2) is Event.NONE
    assert sm.remaining(1.2) > 130


def test_sustained_downward_resyncs():
    """두 프레임 연속 일관된 하향값은(오독이 아니라고 보고) 반영된다 → 시계가
    실제보다 높게 어긋나 있었다면 매끄럽게 재동기화."""
    sm = BuffStateMachine(alert_before=30)
    _appear(sm, reading=140, t0=0.0)
    sm.observe(detected=True, reading=40, now=1.0)  # 후보(미반영)
    sm.observe(detected=True, reading=40, now=1.2)  # 이어짐 → 반영
    assert abs(sm.remaining(1.2) - 40.0) < 1.0


def test_inconsistent_spikes_ignored():
    """서로 다른 오독이 연달아 와도(자기일관 아님) 반영되지 않는다."""
    sm = BuffStateMachine(appear_frames=3)
    _appear(sm, reading=20, t0=0.0)
    sm.observe(detected=True, reading=123, now=1.0)  # 후보 123
    sm.observe(detected=True, reading=145, now=1.2)  # 다른 쓰레기값 → 미확정
    assert sm.remaining(1.2) < 25  # 여전히 ~19, 튐 반영 안 됨


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


def test_late_reappear_below_alert_does_not_refire():
    """만료 임박 버프가 깜빡여(해제→재감지) 이미 알림 시점 아래에서 다시 등장해도
    1차·2차 알림을 '다시' 울리지 않는다. (비바체 30/10 설정에 0초 알림이 추가로
    오던 버그 회귀 방지)"""
    sm = BuffStateMachine(
        appear_frames=1, alert_before=30.0, alert_before2=10.0, disappear_sec=0.4
    )
    fired = []
    now = 0.0

    def tick(detected, reading, dt=0.05):
        nonlocal now
        ev = sm.observe(detected=detected, reading=reading, now=now)
        if ev is Event.ALERT:
            fired.append("1차")
        if sm.check_second_alert(now):
            fired.append("2차")
        now += dt

    # 40초 등장 → 5초까지 정상 카운트다운(30·10 각 1회)
    t = 40.0
    while t > 5:
        tick(True, round(t))
        t -= 0.25
    # 0.6초 아이콘 깜빡(해제) 후 4초로 재감지 → 재발동 없어야
    for _ in range(12):
        tick(False, None)
    t = 4.0
    while t >= 0:
        tick(True, round(t))
        t -= 0.25
    assert fired == ["1차", "2차"]  # 0초 추가 알림 없음


def test_fresh_recast_alerts_again():
    """버프가 만료된 뒤 새로 걸리면(풀 지속시간으로 재등장) 알림은 다시 울린다."""
    sm = BuffStateMachine(appear_frames=1, alert_before=30.0, disappear_sec=0.4)
    fired = []
    now = 0.0

    def tick(detected, reading, dt=0.05):
        nonlocal now
        ev = sm.observe(detected=detected, reading=reading, now=now)
        if ev is Event.ALERT:
            fired.append(round(now, 1))
        now += dt

    t = 40.0  # 첫 캐스트
    while t >= 0:
        tick(True, round(t))
        t -= 0.5
    for _ in range(12):  # 만료(미감지)
        tick(False, None)
    t = 40.0  # 새 캐스트(풀 지속시간)
    while t > 25:
        tick(True, round(t))
        t -= 0.5
    assert len(fired) == 2  # 캐스트마다 1차 1회씩


def test_first_alert_rearms_on_extension_and_on_fresh_recast():
    """1차 알림은 연장이 확정되면 재무장되어 다음 임박에 다시 울린다(상시 유지
    버프를 30초에 갱신하면 그다음 갱신 타이밍도 알려야 함). 완전히 소멸한 뒤 새로
    걸릴 때도 다시 울린다. 단, 같은 순간의 중복(플리커)은 연장으로 확정되지 않아
    재무장되지 않으므로 한 번만 울린다."""
    sm = BuffStateMachine(appear_frames=1, alert_before=30.0, disappear_sec=0.4)
    fired = []
    now = 0.0

    def tick(detected, reading, dt=0.05):
        nonlocal now
        ev = sm.observe(detected=detected, reading=reading, now=now)
        if ev is Event.ALERT:
            fired.append(round(now, 1))
        now += dt

    # 40→8 (1차 1회) → 연장(40으로 재시전) → 다시 40→0 (재무장돼 1차 또 1회)
    for _ in range(2):
        tick(True, 40.0)
    t = 40.0
    while t > 8:
        tick(True, round(t, 1)); t -= 0.3
    tick(True, 40.0); tick(True, 39.9)  # 연장 확정 → 재무장
    t = 39.7
    while t >= 0:
        tick(True, round(t, 1)); t -= 0.3
    assert len(fired) == 2  # 연장 후 다음 임박에 다시 울림

    # 완전 소멸 후 새 캐스트 → 또 울림
    for _ in range(12):
        tick(False, None)
    for _ in range(2):
        tick(True, 40.0)
    t = 40.0
    while t > 25:
        tick(True, round(t, 1)); t -= 0.3
    assert len(fired) == 3  # 새 버프에서 1차 다시
