"""코덱 독립적인 로컬 내보내기 경계. UI 스레드에서 실행하지 않는다.

encode(plan, sink)는 유한 시간 안에 종료/취소되는 어댑터여야 하며 sink.write만 사용한다.
validate(path, plan)는 실제 디코딩·길이/형식 검증 실패 시 예외를 발생시켜야 한다.
이 모듈은 코덱/오차/파일명 정책을 선택하거나 캡처하지 않는다. 원본 저장 계획의 pin은
제어 스레드가 완료 결과를 받은 뒤 해제하며 실패 시 복구 결정 전까지 보존한다.
hard link의 원자적 create-only 확정을 지원하지 않는 파일시스템에서는 실패한다.
합산 예산과 여유 공간은 blackbox_budget/queue가 관리하며 원본 파일 등록은 저장소 어댑터 책임이다.
전원 손실/강제 종료 복구는 아직 구현하지 않았다.
"""

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
from threading import Event, Lock

from .blackbox import SavePlan


class OutputLimitError(OSError):
    pass


class ExportCancelled(RuntimeError):
    pass


def _check_cancelled(cancel: Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise ExportCancelled('export cancellation requested; originals preserved')


class ByteSink:
    """스트림 인코더용 쓰기 전용 상한. 인코더에 경로나 fileno를 제공하지 않는다."""

    def __init__(self, stream, limit: int, cancel: Event | None = None):
        self._stream = stream
        self._limit = limit
        self._written = 0
        self._cancel = cancel

    def check_cancelled(self) -> None:
        """긴 인코더 처리 중에도 주기적으로 호출한다. 임의 Python 작업을 강제 종료하지 않는다."""
        _check_cancelled(self._cancel)

    def write(self, data: bytes) -> int:
        self.check_cancelled()
        if type(data) is not bytes:
            raise TypeError('encoder output must be bytes')
        size = len(data)
        if size > self._limit - self._written:
            raise OutputLimitError('encoded output exceeds the configured byte limit')
        count = self._stream.write(data)
        self._written += count
        if count != size:
            raise OSError('incomplete output write')
        return count


@dataclass(frozen=True)
class ExportResult:
    completed: bool
    output: Path | None
    partial: Path | None
    validated: bool
    error: str | None = None
    cleanup_error: str | None = None


def _validate_plan(plan: SavePlan) -> None:
    if not isinstance(plan, SavePlan) or not plan.slices:
        raise ValueError('a nonempty save plan is required')
    previous = None
    for part in plan.slices:
        if (type(part.offset_us) is not int or type(part.duration_us) is not int
                or part.offset_us < 0 or part.duration_us <= 0
                or part.offset_us + part.duration_us > part.segment.duration_us):
            raise ValueError('invalid source slice')
        if previous is not None and (
                part.segment.session != previous.session
                or part.segment.format_key != previous.format_key
                or part.segment.start_us < previous.end_us):
            raise ValueError('mixed or unordered source segments')
        previous = part.segment
    if type(plan.request_us) is not int or plan.request_us < plan.slices[-1].segment.start_us + plan.slices[-1].offset_us + plan.slices[-1].duration_us:
        raise ValueError('request precedes completed source')


class ExportJob:
    """수락된 저장 계획 하나의 실행. 재호출/동시 호출로 새 파일을 늘리지 않는다.

    실패한 partial은 자동 삭제하지 않는다. 검증된 파일만 retry_publish로 재확정 가능하고,
    미검증 파일은 자동 복구하지 않는다. discard_partial은 호출자의 명시적 복구 포기 이후용이다.
    """

    def __init__(self, plan: SavePlan, output: Path, *, max_output_bytes: int):
        _validate_plan(plan)
        if type(max_output_bytes) is not int or max_output_bytes <= 0:
            raise ValueError('max_output_bytes must be a positive integer')
        self._plan = plan
        self._output = Path(output).absolute()
        self._max_output_bytes = max_output_bytes
        self._lock = Lock()
        self._started = False
        self._partial: Path | None = None
        self._identity = None
        self._directory_identity = None
        self._digest: str | None = None
        self._result: ExportResult | None = None

    @property
    def plan(self) -> SavePlan:
        return self._plan

    @property
    def output(self) -> Path:
        return self._output

    @property
    def max_output_bytes(self) -> int:
        return self._max_output_bytes

    def _owned_partial(self) -> Path:
        if self._partial is None:
            raise ValueError('no owned partial file')
        stat = self._partial.lstat()
        if self._partial.is_symlink() or (stat.st_dev, stat.st_ino) != self._identity:
            raise OSError('partial file was replaced; refusing to use or delete it')
        return self._partial

    def _hash(self) -> str:
        with self._owned_partial().open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()

    @property
    def started(self) -> bool:
        return self._started

    @property
    def retained_bytes(self) -> int:
        """실패/정리 대기 partial의 실제 크기. 소유권 확인 실패는 호출자에게 전달한다."""
        return self._owned_partial().stat().st_size if self._partial is not None else 0

    @property
    def has_partial(self) -> bool:
        return self._partial is not None

    @property
    def partial_path(self) -> Path | None:
        return self._partial

    def _failed(self, exc: Exception) -> ExportResult:
        self._result = ExportResult(False, None, self._partial, self._digest is not None,
                                    f'{type(exc).__name__}: {exc}')
        return self._result

    def _publish(self) -> ExportResult:
        partial = self._owned_partial()
        # os.replace/일반 복사로 폴백하지 않는다. 경쟁 중 생긴 기존 클립도 보존한다.
        os.link(partial, self.output)
        cleanup_error = None
        try:
            self._owned_partial().unlink()
            self._partial = None
        except OSError as exc:
            cleanup_error = str(exc)
        self._result = ExportResult(True, self.output, self._partial, True,
                                    cleanup_error=cleanup_error)
        return self._result

    def run(self, encode: Callable[[SavePlan, ByteSink], None],
            validate: Callable[[Path, SavePlan], None], *, cancel: Event | None = None) -> ExportResult:
        if not self._lock.acquire(blocking=False):
            raise RuntimeError('export already running')
        try:
            if self._started:
                raise RuntimeError('export job has already run')
            self._started = True
            try:
                _check_cancelled(cancel)
                if self.output.exists() or self.output.is_symlink():
                    raise FileExistsError('destination already exists')
                fd, name = tempfile.mkstemp(prefix='.blackbox-', suffix='.partial',
                                            dir=self.output.parent)
                self._partial = Path(name)
                with os.fdopen(fd, 'wb') as stream:
                    stat = os.fstat(stream.fileno())
                    self._identity = (stat.st_dev, stat.st_ino)
                    directory_stat = self.output.parent.stat()
                    self._directory_identity = (directory_stat.st_dev, directory_stat.st_ino)
                    encode(self.plan, ByteSink(stream, self.max_output_bytes, cancel))
                    _check_cancelled(cancel)
                    stream.flush()
                    if stream.tell() == 0:
                        raise ValueError('encoder produced empty output')
                    os.fsync(stream.fileno())
                _check_cancelled(cancel)
                validate(self._owned_partial(), self.plan)
                _check_cancelled(cancel)
                self._digest = self._hash()
                _check_cancelled(cancel)
                return self._publish()
            except Exception as exc:
                return self._failed(exc)
        finally:
            self._lock.release()

    def retry_publish(self, output: Path | None = None, *, cancel: Event | None = None) -> ExportResult:
        """검증 후 확정만 실패한 경우. 재인코딩 없이 같은 바이트를 명시적으로 재시도."""
        if not self._lock.acquire(blocking=False):
            raise RuntimeError('export already running')
        try:
            if self._result is None or self._result.completed or self._digest is None:
                raise ValueError('no validated failed export to retry')
            try:
                _check_cancelled(cancel)
                expected_digest = self._digest
                self._digest = None  # 소유권/읽기 실패도 현재 partial의 검증을 무효화
                if self._hash() != expected_digest:
                    raise OSError('validated partial contents changed')
                self._digest = expected_digest
                if output is not None:
                    self._output = Path(output).absolute()
                _check_cancelled(cancel)
                return self._publish()
            except Exception as exc:
                return self._failed(exc)
        finally:
            self._lock.release()

    def discard_partial(self) -> None:
        """소유 partial만 정리한다. 성공 클립·원본 영상·다른 파일은 건드리지 않는다."""
        if not self._lock.acquire(blocking=False):
            raise RuntimeError('export already running')
        try:
            if self._partial is not None:
                try:
                    self._owned_partial().unlink()
                except FileNotFoundError:
                    # 명시적 복구 포기 시에만, 같은 디렉터리가 존재하면서 파일만 사라졌는지 확인.
                    # 드라이브/상위 경로가 없거나 교체됐으면 정리 성공으로 위장하지 않는다.
                    directory_stat = self._partial.parent.stat()
                    if (directory_stat.st_dev, directory_stat.st_ino) != self._directory_identity:
                        raise OSError('partial directory changed; recovery location unavailable')
                    if self._partial.exists() or self._partial.is_symlink():
                        raise OSError('partial path changed during cleanup')
                self._partial = None
                self._digest = None
        finally:
            self._lock.release()
