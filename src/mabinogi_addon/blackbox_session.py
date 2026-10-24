"""블랙박스 실행 경계. 아직 앱/Windows 캡처 어댑터에 연결하지 않은 제어 계층.

한 게임 실행의 ReplayBuffer를 소유하며 모든 호출은 제어 스레드에서 직렬화한다.
대상 검증/잠금/절전 이벤트와 실제 캡처 중단은 후속 Windows 어댑터 책임이다.
조건 변경을 update_context에 전달하면 이전 캡처 허가를 폐기해 늦은 결과를 막는다.
권한은 feature_access.blackbox_available(디스코드 로그인)을 매 요청 재확인한다.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from .blackbox import ReplayBuffer, SavePlan, Segment
from .feature_access import blackbox_available


class State(str, Enum):
    DISABLED = 'disabled'
    ACCESS_DENIED = 'access_denied'
    WAITING = 'waiting'
    PAUSED = 'paused'
    PREPARING = 'preparing'
    RECORDING = 'recording'
    ERROR = 'error'
    CLOSING = 'closing'
    CLOSED = 'closed'


@dataclass(frozen=True)
class CaptureContext:
    # 단순 PID가 아닌 검증된 앱/게임 실행 식별자. None은 대상 없음/확인 실패.
    session: str | None = None
    foreground: bool = False
    minimized: bool = False
    locked: bool = False
    suspended: bool = False
    ready: bool = False

    def __post_init__(self):
        if self.session is not None and (not isinstance(self.session, str) or not self.session):
            raise ValueError('invalid session')
        if any(type(getattr(self, key)) is not bool for key in
               ('foreground', 'minimized', 'locked', 'suspended', 'ready')):
            raise ValueError('context flags must be booleans')


class BlackboxSession:
    def __init__(self, replay: ReplayBuffer, *, enabled: bool,
                 persist_enabled: Callable[[bool], None],
                 creator_check: Callable[[], bool] = blackbox_available):
        if type(enabled) is not bool:
            raise ValueError('enabled must be a boolean')
        self._replay = replay
        self._enabled = enabled
        self._persist_enabled = persist_enabled
        self._creator_check = creator_check
        self._context = CaptureContext()
        self._permit = None
        self._has_frame = False
        self._error = None
        self._closing = False
        self._closed = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def error(self) -> str | None:
        return self._error

    def _invalidate(self):
        self._permit = None
        self._has_frame = False

    def _allowed(self) -> bool:
        try:
            allowed = self._creator_check() is True
        except Exception:
            allowed = False
        if not allowed:
            self._invalidate()
        return allowed

    @property
    def state(self) -> State:
        if self._closed:
            return State.CLOSED
        if self._closing:
            return State.CLOSING
        if not self._allowed():
            return State.ACCESS_DENIED
        if not self._enabled:
            return State.DISABLED
        if self._error is not None:
            return State.ERROR
        context = self._context
        if context.session != self._replay.session:
            return State.WAITING
        if not context.foreground or context.minimized or context.locked or context.suspended:
            return State.PAUSED
        if not context.ready or not self._has_frame:
            return State.PREPARING
        return State.RECORDING

    def set_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError('enabled must be a boolean')
        if self._closing or self._closed or not self._allowed():
            raise PermissionError('blackbox settings unavailable')
        # 설정 쓰기가 실패하면 기존 체크와 실행 상태를 보존한다.
        self._persist_enabled(enabled)
        if enabled != self._enabled:
            self._invalidate()
        self._enabled = enabled

    def update_context(self, context: CaptureContext) -> None:
        if not isinstance(context, CaptureContext):
            raise TypeError('CaptureContext required')
        if context != self._context:
            self._invalidate()
        self._context = context
        self._allowed()

    def capture_permit(self) -> object:
        """신규 캡처 전에 확인. 비활성/잠금 전환마다 이전 허가는 무효화된다."""
        if self.state not in (State.PREPARING, State.RECORDING) or not self._context.ready:
            raise PermissionError('capture conditions not satisfied')
        if self._permit is None:
            self._permit = object()
        return self._permit

    def append(self, permit: object, segment: Segment) -> tuple[Segment, ...]:
        # 먼저 현재 권한/조건을 검사해서 권한 회수 후 늦게 온 결과도 차단한다.
        current = self.capture_permit()
        if permit is not current:
            raise PermissionError('stale capture result')
        try:
            retired = self._replay.append(segment)
        except (ValueError, RuntimeError) as exc:
            self.report_error(permit, str(exc))
            raise
        self._has_frame = True
        return retired

    def report_error(self, permit: object, reason: str) -> bool:
        """현재 캡처 작업의 실패만 반영한다. 이전 작업의 늦은 실패는 무시한다."""
        if not isinstance(reason, str) or not reason:
            raise ValueError('error reason required')
        if not self._allowed() or permit is None or permit is not self._permit:
            return False
        self._error = reason
        self._invalidate()
        return True

    def acknowledge_recovery(self) -> None:
        """어댑터가 복구를 검증한 후 호출. 타이머 기반 무한 재시도는 하지 않는다."""
        if self._closing or self._closed or not self._allowed():
            raise PermissionError('recovery unavailable')
        self._error = None
        self._invalidate()

    def request_save(self, request_us: int) -> SavePlan:
        # 체크 해제·게임 종료·캡처 오류 후에도 기존 구간 저장은 허용한다.
        if self._closing or self._closed or not self._allowed():
            raise PermissionError('new save requests unavailable')
        return self._replay.request_save(request_us)

    def reserve_save(self, request_us):
        if self._closing or self._closed or not self._allowed():
            raise PermissionError('new save reservations unavailable')
        return self._replay.reserve_save(request_us)

    def request_save_at(self, request_us: int) -> SavePlan:
        if self._closing or self._closed or not self._allowed():
            raise PermissionError('new save requests unavailable')
        return self._replay.request_save_at(request_us)

    def release_save(self, plan: SavePlan) -> tuple[Segment, ...]:
        # 접근 회수와 종료 요청은 이미 접수된 저장의 자료 보호/정리를 막지 않는다.
        return self._replay.release_save(plan)

    def begin_close(self) -> None:
        self._closing = True
        self._invalidate()

    def finish_close(self) -> tuple[Segment, ...]:
        if not self._closing:
            raise RuntimeError('begin_close must precede cleanup')
        retired = self._replay.clear()  # 저장 중이면 실패하고 원본을 보존
        self._closed = True
        return retired
