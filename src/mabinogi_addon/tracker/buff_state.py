"""버프 상태 머신 + 내부 시계 (기획서 4.5).

프레임마다 observe()로 관측을 넣는다. 시계 테스트를 위해 현재 시각(now, 초)을
외부에서 주입한다(단조 시계 값).

상태: ABSENT → ACTIVE → EXPIRING(만료임박: 점멸+소리 1회)
- ABSENT→ACTIVE: appear_frames 연속 감지
- ACTIVE→EXPIRING: 내부 시계 ≤ alert_before
- EXPIRING→ACTIVE: 시간 증가(연장) 감지 → 알림 해제
- ACTIVE/EXPIRING→ABSENT: 사라짐 판정
내부 시계: 마지막 정상 판독값 − 경과시간. 알림은 내부 시계 기준(화면 안 보여도 울림).
판정 불가(frame_valid=False: 앵커 미검출·게임 비활성): 화면 기반 판단은 동결하되,
  내부 시계가 0에 닿으면 만료 처리(시간 경과는 화면과 무관).

튐 가드: 믿을 기준은 내부 시계다. 판독값이 시계와 어긋나면(위로든 아래로든) 한
프레임만으론 반영하지 않고, 다음 프레임이 그 값에서 매끄럽게 이어질 때(자기일관)만
반영한다. 밝은 게임 지형 위 글자가 흐려져 생기는 한 프레임짜리 오독을 양방향으로
막는다: 위로 튐('2분3초' 등)은 거짓 연장→알림 꺼짐을, 아래로 튐(분을 놓쳐 '20초'로)
은 거짓 임박을 유발하는데, 둘 다 이어지지 않으므로 무시되고 내부 시계가 그대로
흐른다. 위로 튐이 이어지면 연장(EXTENDED), 아래로 튐이 이어지면 조용히 재동기화.
"""

from __future__ import annotations

from enum import Enum, auto


class State(Enum):
    ABSENT = auto()
    ACTIVE = auto()
    EXPIRING = auto()


class Event(Enum):
    NONE = auto()
    APPEARED = auto()
    ALERT = auto()  # 만료임박 진입(점멸+소리 1회)
    EXTENDED = auto()  # 연장 성공 → 알림 해제
    EXPIRED = auto()  # 시간이 다 됨
    RELEASED = auto()  # 중간 해제(시간 남았는데 사라짐)


# 판독 지터(±1초)를 연장으로 오인하지 않도록 한 여유값
_EXTEND_EPS = 2.0
# 판독값이 내부 시계와 '일치'한다고 볼 허용 오차(초). 이 밖이면 튐으로 보고 확인 대기.
_AGREE_EPS = 2.0


class BuffStateMachine:
    def __init__(
        self,
        *,
        alert_before: float = 30.0,
        alert_before2: float | None = None,
        appear_frames: int = 3,
        disappear_sec: float = 0.4,
    ) -> None:
        self.alert_before = alert_before
        self.alert_before2 = alert_before2  # None=2차 알림 없음
        self.appear_frames = appear_frames
        self.disappear_sec = disappear_sec

        self.state = State.ABSENT
        self._last_read: float | None = None  # 마지막 판독한 남은 시간
        self._last_read_at: float | None = None  # 그때의 now
        self._detections = 0
        self._missing_since: float | None = None
        self._alerted = False  # 1차 알림 1회 발생 플래그(소멸·연장 시 재무장)
        self._alerted2 = False  # 2차 알림 1회 발생 플래그(소멸·연장 시 재무장)
        # 위로 튄 판독의 연장 후보 (reading, now). 다음 프레임에서 이어지는지 확인용.
        self._pending: tuple[float, float] | None = None

    # ---- 조회 ----
    def remaining(self, now: float) -> float | None:
        """내부 시계 기준 남은 시간(초). 판독값 없으면 None(무기한 버프 등)."""
        if self._last_read is None or self._last_read_at is None:
            return None
        return self._last_read - (now - self._last_read_at)

    @property
    def alerting(self) -> bool:
        return self.state is State.EXPIRING

    def check_second_alert(self, now: float) -> bool:
        """2차 알림 시점(만료 before_sec2 이하)을 1회 교차하면 True.

        1차 알림과 독립. 한 '수명' 동안 1회만 울린다. 재무장(다시 울릴 수 있게)되는
        건 두 경우: 버프가 완전히 사라졌다 새로 걸릴 때(reset), 그리고 **연장이
        확정될 때**(다시 건 것이므로 새 수명 → 다음 임박에 또 알림). 플리커로 인한
        같은 순간 중복은 연장으로 확정되지 않아 재무장되지 않는다.
        """
        if self.alert_before2 is None or self._alerted2:
            return False
        remaining = self.remaining(now)
        if remaining is None:
            return False
        if remaining <= self.alert_before2 and self.state in (
            State.ACTIVE,
            State.EXPIRING,
        ):
            self._alerted2 = True
            return True
        return False

    # ---- 갱신 ----
    def observe(
        self,
        *,
        detected: bool,
        reading: float | None,
        now: float,
        frame_valid: bool = True,
    ) -> Event:
        # 판정 불가: 화면 기반 판단(감지·연장·해제)은 멈추되(상태 동결), 내부 시계가
        # 0에 닿으면 만료 처리한다. "시간이 다 됐다"는 화면을 안 읽어도 아는 사실이라
        # 동결 원칙을 깨지 않는다 → 앵커가 오래 안 보여도 0초면 오버레이에서 사라지고,
        # 다시 보일 때 버프가 살아 있으면 재감지로 다시 뜬다.
        if not frame_valid:
            remaining = self.remaining(now)
            if (
                self.state is not State.ABSENT
                and remaining is not None
                and remaining <= 0
            ):
                self._reset()
                return Event.EXPIRED
            return Event.NONE

        if detected:
            return self._on_detected(reading, now)
        return self._on_missing(now)

    def _on_detected(self, reading: float | None, now: float) -> Event:
        self._missing_since = None
        self._detections += 1
        event = Event.NONE

        extended = False
        if reading is not None:
            extended = self._anchor(reading, now)

        if self.state is State.ABSENT:
            if self._detections >= self.appear_frames:
                self.state = State.ACTIVE
                event = Event.APPEARED
                # 이미 알림 시점 아래에서 '뒤늦게' 등장(만료 임박 버프가 깜빡여
                # 해제됐다 재감지되는 등) → 알림을 다시 울리지 않는다. 조용히 임박
                # 상태로 두고, 지난 2차 시점도 발동한 것으로 표시.
                rem = self.remaining(now)
                if rem is not None and rem <= self.alert_before:
                    self.state = State.EXPIRING
                    self._alerted = True  # 이미 1차 시점 아래 → 1차 발동한 것으로
                    if self.alert_before2 is not None and rem <= self.alert_before2:
                        self._alerted2 = True
            else:
                return Event.NONE

        if extended:
            return Event.EXTENDED
        return self._check_alert(now) or event

    def _commit(self, reading: float, now: float) -> None:
        self._last_read = reading
        self._last_read_at = now

    def _anchor(self, reading: float, now: float) -> bool:
        """판독값을 내부 시계에 반영할지 결정한다. 연장으로 확정됐으면 True.

        - 첫 기준값: 즉시 반영.
        - 시계와 일치(정상 감소분·판독지터 포함): 즉시 반영.
        - 시계와 어긋남(위/아래로 튐): 한 프레임만으론 안 믿는다. 다음 프레임이 그
          후보에서 매끄럽게 이어질 때만(자기일관) 반영한다. 위로 이어지면 연장(알림
          해제), 아래로 이어지면 조용히 재동기화. 한 프레임짜리 오독은 양방향 모두
          무시되어, 거짓 연장(알림 꺼짐)도 거짓 임박(알림 켜짐)도 생기지 않는다.
        """
        prev = self.remaining(now)
        # 첫 기준값(갓 등장 등) → 바로 반영
        if prev is None:
            self._commit(reading, now)
            return False
        # 내부 시계와 일치 → 정상 반영
        if abs(reading - prev) <= _AGREE_EPS:
            self._pending = None
            self._commit(reading, now)
            return False
        # --- 시계와 어긋남(위/아래로 튐): 확인 대기 ---
        pend = self._pending
        if pend is not None:
            pred = pend[0] - (now - pend[1])  # 후보가 이어졌다면 지금쯤의 예상값
            if abs(reading - pred) <= _AGREE_EPS:
                # 후보에서 매끄럽게 이어짐 → 반영
                self._pending = None
                extended = self.state is State.EXPIRING and reading > prev + _EXTEND_EPS
                self._commit(reading, now)
                if extended:  # 위로 이어짐 + 임박 중 → 연장
                    self.state = State.ACTIVE  # 점멸 해제
                    # 연장 = 버프를 다시 건 것(음악 버프 연장, 상시 유지 버프 갱신 등).
                    # 다음에 다시 임박(≤alert_before)이 되면 "또 갱신해라"를 정상적으로
                    # 다시 알려야 하므로 알림을 재무장한다. 플리커는 위로 '이어지는'
                    # 상승 점프를 못 만들어(돌아올 때 값이 더 낮음) 여기 오지 않으므로,
                    # 같은 순간 중복 알림은 여전히 울리지 않는다.
                    self._alerted = False
                    self._alerted2 = False
                    return True
                return False
        # 아직 확정 못 함: 후보만 갱신하고 내부 시계는 유지(튐 반영 안 함)
        self._pending = (reading, now)
        return False

    def _on_missing(self, now: float) -> Event:
        self._detections = 0
        self._pending = None  # 미감지 프레임은 연장 확인 연쇄를 끊는다
        if self.state is State.ABSENT:
            return Event.NONE

        if self._missing_since is None:
            self._missing_since = now
        remaining = self.remaining(now)

        # 1) 내부 시계 소진 + 미감지 → 만료
        if remaining is not None and remaining <= 0:
            self._reset()
            return Event.EXPIRED
        # 2) 시간 남았는데 정상 프레임에서 disappear_sec 이상 연속 미감지 → 중간 해제
        if now - self._missing_since >= self.disappear_sec:
            self._reset()
            return Event.RELEASED
        return Event.NONE

    def _check_alert(self, now: float) -> Event | None:
        remaining = self.remaining(now)
        if remaining is None:
            return None  # 무기한 버프는 알림 없음
        if self.state is State.ACTIVE and remaining <= self.alert_before:
            self.state = State.EXPIRING  # 상태(점멸)는 전이, 소리는 1회만
            if not self._alerted:
                self._alerted = True
                return Event.ALERT
        return None

    def _reset(self) -> None:
        self.state = State.ABSENT
        self._last_read = None
        self._last_read_at = None
        self._detections = 0
        self._missing_since = None
        self._alerted = False  # 소멸 → 다음 버프에서 1차 알림 재무장
        self._alerted2 = False  # 소멸 → 2차 알림 재무장
        self._pending = None
