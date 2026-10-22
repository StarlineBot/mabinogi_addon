"""유한 저장 작업 큐. UI/게임 중단과 독립적으로 접수한 저장을 끝낸다.

수와 시간 정책은 외부 필수 인자다. 제품 화면·인코더 어댑터는 아직 연결하지 않는다.
작업 완료/실패 결과와 미정리 partial도 슬롯을 차지하며 acknowledge 전까지 유실되지 않는다.
정상 종료는 신규 접수만 막고 기존 작업은 계속한다. 강제 종료는 없으며, 유한 시간 안에
종료/취소되는 어댑터가 필요하다. wait_idle=False는 종료 가능이 아니라 작업 정체/진행 중이다.
원본 plan pin은 항상 제어 스레드가 결과/복구 결정을 확인한 뒤 별도로 해제해야 한다.
"""

from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
import math
from pathlib import Path
from threading import Event, Lock
import uuid

from .blackbox_budget import DiskBudget
from .blackbox_export import ExportJob, ExportResult
from .feature_access import is_creator


class QueueFullError(RuntimeError):
    pass


@dataclass
class _Entry:
    job: ExportJob
    allocation: object | None
    cancel: Event = field(default_factory=Event)
    future: Future | None = None
    result: ExportResult | None = None
    previous: list = field(default_factory=list)


class ExportQueue:
    def __init__(self, budget: DiskBudget, *, max_workers: int, max_jobs: int,
                 creator_check=is_creator):
        if any(type(n) is not int or n <= 0 for n in (max_workers, max_jobs)):
            raise ValueError('worker/job bounds must be positive integers')
        if max_workers > max_jobs:
            raise ValueError('workers must not exceed job slots')
        self.budget = budget
        self.max_jobs = max_jobs
        self._creator_check = creator_check
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='blackbox-export')
        self._entries: dict[str, _Entry] = {}
        self._reservations = {}
        self._closing = False
        self._lock = Lock()

    def _allowed(self):
        try:
            return self._creator_check() is True
        except Exception:
            return False

    def submit(self, job: ExportJob, encode, validate) -> str:
        """거부 시 plan을 소비하지 않는다. 접수 후 접근 회수는 기존 작업을 취소하지 않는다."""
        with self._lock:
            if self._closing or not self._allowed():
                raise PermissionError('new exports are unavailable')
            if len(self._entries) + len(self._reservations) >= self.max_jobs:
                raise QueueFullError('export/result slots full; acknowledge or resolve existing jobs')
            if job.started or any(e.job is job for e in self._entries.values()):
                raise ValueError('export job already submitted or started')
            allocation = self.budget.reserve(job.output.parent, job.max_output_bytes)
            entry = _Entry(job, allocation)
            ticket = uuid.uuid4().hex
            self._entries[ticket] = entry
            try:
                entry.future = self._executor.submit(self._run, entry,
                    lambda: job.run(encode, validate, cancel=entry.cancel))
            except Exception:
                del self._entries[ticket]
                self.budget.release(allocation)
                raise
            return ticket

    def reserve_output(self, output: Path, max_bytes: int):
        with self._lock:
            if self._closing or not self._allowed():
                raise PermissionError('new exports unavailable')
            if len(self._entries) + len(self._reservations) >= self.max_jobs:
                raise QueueFullError('save slots already reserved')
            output = Path(output).absolute()
            allocation = self.budget.reserve(output.parent, max_bytes)
            token = object()
            self._reservations[token] = (output, max_bytes, allocation)
            return token

    def cancel_reservation(self, token):
        with self._lock:
            _, _, allocation = self._reservations.pop(token)
            self.budget.release(allocation)

    def submit_reserved(self, token, job, encode, validate):
        with self._lock:
            output, limit, allocation = self._reservations[token]
            if job.output != output or job.max_output_bytes != limit or job.started:
                raise ValueError('job differs from accepted reservation')
            if any(e.job is job for e in self._entries.values()):
                raise ValueError('job already queued')
            entry = _Entry(job, allocation)
            ticket = uuid.uuid4().hex
            self._entries[ticket] = entry
            try:
                entry.future = self._executor.submit(self._run, entry,
                    lambda: job.run(encode, validate, cancel=entry.cancel))
            except BaseException:
                del self._entries[ticket]
                raise
            del self._reservations[token]
            return ticket

    def _settle(self, entry: _Entry):
        if entry.allocation is not None:
            if entry.job.has_partial:
                self.budget.settle(entry.allocation, entry.job.retained_bytes)
            else:
                self.budget.release(entry.allocation)
                entry.allocation = None

    def _run(self, entry, operation):
        try:
            result = operation()
        except BaseException as exc:
            # 소유권은 큐에 있다. 어댑터/작업 경계의 예상 밖 실패도 결과 슬롯에 남긴다.
            result = ExportResult(False, None, entry.job.partial_path, False, f'{type(exc).__name__}: {exc}')
        with self._lock:
            try:
                self._settle(entry)
            except (OSError, ValueError, RuntimeError) as exc:
                result = replace(result, cleanup_error=f'budget reconciliation required: {exc}')
            entry.result = result
        return result

    def result(self, ticket: str) -> ExportResult | None:
        """대기하지 않는다. None은 아직 실행/대기 중이며 실패나 성공이 아니다."""
        with self._lock:
            return self._entries[ticket].result

    def cancel(self, ticket: str) -> bool:
        """명시적 취소 요청. worker/validator가 아직 반환하지 않으면 완료로 표시하지 않는다."""
        with self._lock:
            entry = self._entries[ticket]
            if entry.result is not None:
                return False
            entry.cancel.set()
            return True

    def begin_close(self):
        """새 접수만 중단. 큐의 기존 저장/실패 복구 자료는 그대로 유지한다."""
        with self._lock:
            self._closing = True

    def wait_idle(self, timeout: float) -> bool:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError('finite nonnegative timeout required')
        with self._lock:
            futures = [e.future for e in self._entries.values() if e.future is not None]
        _, pending = wait(futures, timeout=timeout)
        return not pending

    def retry_publish(self, ticket: str, output: Path | None = None):
        """접수된 저장의 복구이므로 접근 해제/종료 대기 중에도 가능하다. 원본 pin은 유지한다."""
        with self._lock:
            entry = self._entries[ticket]
            if entry.future is not None and not entry.future.done():
                raise RuntimeError('export still running')
            if entry.result is None or entry.result.completed or not entry.result.validated:
                raise ValueError('no validated failed export')
            entry.cancel.clear()
            future = self._executor.submit(self._run, entry,
                lambda: entry.job.retry_publish(output, cancel=entry.cancel))
            entry.result = None
            entry.future = future

    def retry_encode(self, ticket: str, replacement: ExportJob, encode, validate):
        """수락된 같은 계획을 재인코딩. 이전 실패 자료는 명시적 폐기까지 예산에 남긴다."""
        with self._lock:
            entry = self._entries[ticket]
            if entry.future is not None and not entry.future.done():
                raise RuntimeError('export still running')
            if entry.result is None or entry.result.completed:
                raise ValueError('failed export required')
            if (replacement.plan is not entry.job.plan or replacement.started
                    or any(e.job is replacement for e in self._entries.values())):
                raise ValueError('unstarted replacement of the same frozen plan required')
            allocation = self.budget.reserve(replacement.output.parent, replacement.max_output_bytes)
            old_job, old_allocation = entry.job, entry.allocation
            old_result = entry.result
            entry.job, entry.allocation = replacement, allocation
            entry.cancel.clear()
            try:
                future = self._executor.submit(self._run, entry,
                    lambda: replacement.run(encode, validate, cancel=entry.cancel))
            except BaseException:
                entry.job, entry.allocation = old_job, old_allocation
                entry.result = old_result
                self.budget.release(allocation)
                raise
            if old_allocation is not None or old_job.has_partial:
                entry.previous.append((old_job, old_allocation))
            entry.result = None
            entry.future = future

    def discard_partial(self, ticket: str):
        """호출자가 복구 포기를 결정한 뒤 정리. 실패하면 슬롯과 예산을 보존한다."""
        with self._lock:
            entry = self._entries[ticket]
            if entry.future is not None and not entry.future.done():
                raise RuntimeError('export still running')
            while entry.previous:
                prior_job, prior_allocation = entry.previous[0]
                prior_job.discard_partial()
                if prior_allocation is not None:
                    self.budget.release(prior_allocation)
                entry.previous.pop(0)
            entry.job.discard_partial()
            self._settle(entry)
            if entry.result is not None:
                entry.result = replace(entry.result, partial=None, cleanup_error=None)

    def acknowledge(self, ticket: str) -> ExportResult:
        """제어 스레드가 결과를 인수한다. 미정리 자료가 있으면 조용히 잊지 않는다."""
        with self._lock:
            entry = self._entries[ticket]
            if entry.result is None or entry.future is None or not entry.future.done():
                raise RuntimeError('export still running')
            if entry.allocation is not None or entry.job.has_partial or entry.previous:
                raise RuntimeError('partial/recovery budget must be resolved first')
            del self._entries[ticket]
            return entry.result

    def finish_close(self) -> bool:
        """결과 인수와 실패 복구가 모두 끝나 슬롯이 비었을 때만 thread pool을 닫는다."""
        with self._lock:
            if not self._closing:
                raise RuntimeError('begin_close required')
            if self._entries or self._reservations:
                return False
            self._executor.shutdown(wait=False)
            return True
