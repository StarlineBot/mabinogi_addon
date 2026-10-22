"""최근 영상의 순수 구간 관리. 캡처·파일 IO·앱 실행 경로는 아직 연결하지 않는다.

한 객체는 한 앱/게임 실행에만 속한다. 호출자는 검증된 게임 영상의 완결 구간만
전달하고 모든 호출을 한 제어 스레드에서 직렬화해야 한다. 구간 내부에는 중단이나
오류 누락이 없어야 하며 시간은 동일 단조 시계의 정수 microseconds다.
source는 저장소 어댑터가 발급한 불변 참조다. 이 모듈은 경로를 열거나 삭제하지 않는다.
반환된 retired 구간만 저장소 정리 후보이며 저장 완료 클립은 이 객체에 넣지 않는다.
실제 파일 삭제 실패/인코딩 중 공간도 저장소 계층에서 별도 관리해야 한다.
"""

from dataclasses import dataclass


DEFAULT_RETENTION_US = 10 * 60 * 1_000_000


def _positive(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f'{name} must be a positive integer')


@dataclass(frozen=True)
class Segment:
    session: str
    source: str
    start_us: int
    end_us: int
    size_bytes: int
    format_key: str

    def __post_init__(self):
        if not all(isinstance(x, str) and x for x in
                   (self.session, self.source, self.format_key)):
            raise ValueError('session, source and format_key are required')
        if type(self.start_us) is not int or self.start_us < 0:
            raise ValueError('start_us must be a nonnegative integer')
        _positive(self.end_us, 'end_us')
        _positive(self.size_bytes, 'size_bytes')
        if self.end_us <= self.start_us:
            raise ValueError('empty or reversed segment')

    @property
    def duration_us(self) -> int:
        return self.end_us - self.start_us


@dataclass(frozen=True)
class Slice:
    segment: Segment
    offset_us: int
    duration_us: int


@dataclass(frozen=True)
class SavePlan:
    request_us: int
    slices: tuple[Slice, ...]

    @property
    def duration_us(self) -> int:
        return sum(part.duration_us for part in self.slices)


@dataclass(eq=False)
class SaveReservation:
    request_us: int
    segments: list[Segment]
    retention_us: int


class BufferFullError(RuntimeError):
    """보호된 내보내기 때문에 신규 구간을 보관할 수 없음. 기존 자료는 유지."""


class ReplayBuffer:
    """완결 구간 메타데이터와 저장 중 참조의 유한 보관소.

    용량/구간 수에는 기본값을 두지 않는다. 이 범용 모델의 동시 저장 수는 호출자가
    지정하며 제품 runtime의 승인 정책은 1개 처리+1개 대기다.
    retention_us만 승인된 기본 10분이다. 시간 경계 구간은 통째 보관하고 저장
    계획에서 정확히 자른다. 실제 인코더의 키프레임/음성 오차 검증은 별도다.
    """

    def __init__(self, session: str, *, max_bytes: int, max_segments: int,
                 max_saves: int, retention_us: int = DEFAULT_RETENTION_US):
        if not isinstance(session, str) or not session:
            raise ValueError('session is required')
        for name, value in (('max_bytes', max_bytes), ('max_segments', max_segments),
                            ('max_saves', max_saves), ('retention_us', retention_us)):
            _positive(value, name)
        self.session = session
        self.max_bytes = max_bytes
        self.max_segments = max_segments
        self.max_saves = max_saves
        self._retention_us = retention_us
        self._recent: list[Segment] = []
        self._owned: list[Segment] = []
        self._plans: list[SavePlan] = []
        self._reservations: list[SaveReservation] = []
        self._last_end_us = 0

    @property
    def retained_bytes(self) -> int:
        """시간 범위 밖이어도 저장 중 보호하는 원본을 포함한다."""
        return sum(segment.size_bytes for segment in self._owned)

    @property
    def available_us(self) -> int:
        return min(self._retention_us, sum(s.duration_us for s in self._recent))

    def _protected(self) -> set[Segment]:
        return ({part.segment for plan in self._plans for part in plan.slices}
                | {segment for pending in self._reservations for segment in pending.segments})

    @staticmethod
    def _trim(recent: list[Segment], duration_us: int) -> None:
        total = sum(s.duration_us for s in recent)
        while recent and total - recent[0].duration_us >= duration_us:
            total -= recent.pop(0).duration_us

    def _commit(self, recent: list[Segment], owned: list[Segment]) -> tuple[Segment, ...]:
        keep = set(recent) | self._protected()
        retired = tuple(s for s in owned if s not in keep)
        self._recent = recent
        self._owned = [s for s in owned if s in keep]
        return retired

    def append(self, segment: Segment) -> tuple[Segment, ...]:
        """성공했을 때만 등록하고 보호되지 않은 정리 후보를 반환한다."""
        if segment.session != self.session:
            raise ValueError('different game/app session')
        if segment.start_us < self._last_end_us:
            raise ValueError('overlapping or late segment')
        if any(s.source == segment.source for s in self._owned):
            raise ValueError('source is already retained')
        recent = [*self._recent, segment]
        self._trim(recent, self._retention_us)
        protected = self._protected()
        while True:
            keep = set(recent) | protected
            if (sum(s.size_bytes for s in keep) <= self.max_bytes
                    and len(keep) <= self.max_segments):
                break
            if len(recent) <= 1:
                raise BufferFullError('temporary budget exhausted; existing segments preserved')
            recent.pop(0)
        for pending in self._reservations:
            if segment.start_us < pending.request_us:
                pending.segments.append(segment)
        retired = self._commit(recent, [*self._owned, segment])
        self._last_end_us = segment.end_us
        return retired

    def set_retention(self, duration_us: int) -> tuple[Segment, ...]:
        _positive(duration_us, 'retention_us')
        recent = self._recent.copy()
        self._trim(recent, duration_us)
        self._retention_us = duration_us
        return self._commit(recent, self._owned)

    def request_save(self, request_us: int) -> SavePlan:
        """요청 시점의 구간을 고정한다. 이후 도착한 영상은 계획에 추가하지 않는다.

        현재 인코딩 구간의 flush/완결 및 요청 시각 전달은 호출자 책임이다.
        format_key 일치는 연결 성공 보증이 아니다. 다른 형식은 별도 검증 전 거부한다.
        """
        if type(request_us) is not int or request_us < self._last_end_us:
            raise ValueError('request must follow the latest completed segment')
        return self.request_save_at(request_us)

    def request_save_at(self, request_us: int) -> SavePlan:
        """flush 완료가 늦어도 최초 요청 시각에서 끝을 자른다. 미래 프레임은 제외한다."""
        if type(request_us) is not int or request_us < 0:
            raise ValueError('nonnegative request timestamp required')
        if len(self._plans) + len(self._reservations) >= self.max_saves:
            raise BufferFullError('save request limit reached')
        plan = self._make_plan(request_us, self._recent)
        self._plans.append(plan)
        return plan

    def _make_plan(self, request_us, segments, retention_us=None):
        remaining = self._retention_us if retention_us is None else retention_us
        parts = []
        for segment in reversed(sorted(segments, key=lambda item: item.start_us)):
            available = min(segment.end_us, request_us) - segment.start_us
            if available <= 0:
                continue
            duration = min(remaining, available)
            parts.append(Slice(segment, available - duration, duration))
            remaining -= duration
            if not remaining:
                break
        if not parts:
            raise ValueError('no valid video available')
        if len({part.segment.format_key for part in parts}) != 1:
            raise ValueError('mixed formats require a validated export adapter')
        return SavePlan(request_us, tuple(reversed(parts)))

    def reserve_save(self, request_us):
        if type(request_us) is not int or request_us < 0:
            raise ValueError('nonnegative request timestamp required')
        if len(self._plans) + len(self._reservations) >= self.max_saves:
            raise BufferFullError('save reservation limit reached')
        pending = SaveReservation(request_us, [s for s in self._recent if s.start_us < request_us], self._retention_us)
        self._reservations.append(pending)
        return pending

    def retain_reserved(self, pending, segment):
        if not any(p is pending for p in self._reservations):
            raise ValueError('unknown save reservation')
        if segment.session != self.session or segment.start_us >= pending.request_us:
            raise ValueError('source outside accepted request')
        existing = next((s for s in self._owned if s.source == segment.source), None)
        if existing is not None and existing != segment:
            raise ValueError('source identity changed')
        if existing is None:
            if (self.retained_bytes + segment.size_bytes > self.max_bytes or len(self._owned) >= self.max_segments):
                raise BufferFullError('accepted source exceeds buffer bounds')
            if any(s.start_us < segment.end_us and segment.start_us < s.end_us for s in self._owned):
                raise ValueError('overlapping accepted source')
            self._owned.append(segment)
        if segment not in pending.segments:
            pending.segments.append(segment)

    def finish_reservation(self, pending):
        if not any(p is pending for p in self._reservations):
            raise ValueError('unknown save reservation')
        plan = self._make_plan(pending.request_us, pending.segments, pending.retention_us)
        self._reservations.remove(pending)
        self._plans.append(plan)
        return plan

    def cancel_reservation(self, pending):
        if not any(p is pending for p in self._reservations):
            raise ValueError('unknown save reservation')
        self._reservations.remove(pending)
        return self._commit(self._recent, self._owned)

    def release_save(self, plan: SavePlan) -> tuple[Segment, ...]:
        """내보내기가 원본을 더 사용하지 않을 때만 해제. 저장 성공을 뜻하지 않는다.

        실패 자료의 복구/재시도 정책을 결정하기 전에는 해제하지 않는다.
        접근 해제·녹화 중단 여부와 무관하게 기존 요청을 정리할 수 있다.
        """
        index = next((i for i, active in enumerate(self._plans) if active is plan), None)
        if index is None:
            raise ValueError('unknown or already released save plan')
        self._plans.pop(index)
        return self._commit(self._recent, self._owned)

    def clear(self) -> tuple[Segment, ...]:
        """앱 종료용. 진행 중 저장이 있으면 정리를 거부하고 모두 보존한다.

        사용 해제/게임 종료 시 호출하지 않는다. 그때는 append만 중단해 저장 기회를 유지한다.
        """
        if self._plans or self._reservations:
            raise BufferFullError('save plans still reference temporary video')
        return self._commit([], self._owned)
