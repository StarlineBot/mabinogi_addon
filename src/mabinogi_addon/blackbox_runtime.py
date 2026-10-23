"""승인된 1개 처리+1개 대기 저장 정책의 제어 스레드 연결.

실제 캡처/인코더는 주입한다. 용량·품질 기본값과 Windows 기술은 여기서 정하지 않는다.
완료 결과 인수 전까지 원본 pin을 보존하고 실패는 명시적 복구/포기까지 유지한다.
"""
from pathlib import Path
from dataclasses import replace
import time

from .blackbox_export import ExportJob
from .blackbox_queue import ExportQueue
from .feature_access import is_creator


class BlackboxRuntime:
    def __init__(self, session, budget, *, max_output_bytes: int, encode, validate,
                 retire, creator_check=is_creator, queue=None):
        if type(max_output_bytes) is not int or max_output_bytes <= 0:
            raise ValueError('explicit positive output limit required')
        self.session = session
        self.queue = queue if queue is not None else ExportQueue(budget, max_workers=1, max_jobs=2,
                                 creator_check=creator_check)
        self._limit = max_output_bytes
        self._encode = encode
        self._validate = validate
        self._retire = retire
        self._plans = {}
        self.requested_at = {}  # ticket → 저장 요청 시각(벽시계, 화면 표시용)
        self._pending = {}
        self._pending_retired = []

    def request_save(self, request_us: int, output: Path) -> str:
        plan = self.session.request_save_at(request_us)
        try:
            job = ExportJob(plan, output, max_output_bytes=self._limit)
            ticket = self.queue.submit(job, self._encode, self._validate)
        except BaseException:
            self._retire_segments(self.session.release_save(plan))
            raise
        self._plans[ticket] = plan
        self.requested_at[ticket] = time.time()
        return ticket

    def reserve_save(self, request_us, output):
        pending = self.session.reserve_save(request_us)
        try:
            reservation = self.queue.reserve_output(output, self._limit)
        except BaseException:
            self._retire_segments(self.session._replay.cancel_reservation(pending))
            raise
        token = object()
        self._pending[token] = (pending, reservation, output)
        return token

    def retain_reserved(self, token, segment):
        pending, _, _ = self._pending[token]
        self.session._replay.retain_reserved(pending, segment)

    def complete_reserved(self, token):
        pending, reservation, output = self._pending[token]
        plan = self.session._replay.finish_reservation(pending)
        try:
            job = ExportJob(plan, output, max_output_bytes=self._limit)
            ticket = self.queue.submit_reserved(reservation, job, self._encode, self._validate)
        except BaseException as exc:
            del self._pending[token]
            self.queue.cancel_reservation(reservation)
            try:
                self._retire_segments(self.session.release_save(plan))
            except OSError as cleanup:
                exc.add_note(f'source cleanup pending: {cleanup}')
            raise
        del self._pending[token]
        self._plans[ticket] = plan
        self.requested_at[ticket] = time.time()
        return ticket

    def cancel_reserved(self, token):
        pending, reservation, _ = self._pending.pop(token)
        self.queue.cancel_reservation(reservation)
        self._retire_segments(self.session._replay.cancel_reservation(pending))

    @property
    def tickets(self):
        return tuple(self._plans)

    def accept_completed(self, ticket: str):
        result = self.queue.result(ticket)
        if result is None or not result.completed:
            raise RuntimeError('successful completed export required')
        # 정리 실패 partial은 명시적 정리 뒤 인수한다. 원본 pin은 그 전까지 유지.
        result = self.queue.acknowledge(ticket)
        plan = self._plans.pop(ticket)
        result = replace(result, duration_us=plan.duration_us)
        try:
            self._retire_segments(self.session.release_save(plan))
        except OSError as exc:
            # 저장/결과 인수는 완료됐다. 정리 실패 때문에 그 결과를 잃지 않는다.
            result = replace(result, cleanup_error=f'source cleanup pending: {exc}')
        return result

    def retry_failed(self, ticket: str, output: Path):
        """기존 계획/끝점으로 재인코딩. 이전 실패 파일도 명시적 정리 전까지 보존한다."""
        replacement = ExportJob(self._plans[ticket], output, max_output_bytes=self._limit)
        self.queue.retry_encode(ticket, replacement, self._encode, self._validate)

    def discard_failed(self, ticket: str):
        """사용자의 복구 포기 후 호출. 캡처 버퍼 자체나 저장한 클립을 삭제하지 않는다."""
        result = self.queue.result(ticket)
        if result is None or result.completed:
            raise RuntimeError('finished failed export required')
        self.queue.discard_partial(ticket)
        result = self.queue.acknowledge(ticket)
        try:
            self._retire_segments(self.session.release_save(self._plans.pop(ticket)))
        except OSError as exc:
            # 저장/결과 인수는 완료됐다. 정리 실패 때문에 그 결과를 잃지 않는다.
            result = replace(result, cleanup_error=f'source cleanup pending: {exc}')
        return result

    def _retire_segments(self, segments):
        self._pending_retired.extend(segments)
        self.retry_cleanup()

    def retry_cleanup(self) -> int:
        """정리 대기 원본을 다시 지운다. 정리한 개수를 돌려준다."""
        cleaned = 0
        while self._pending_retired:
            self._retire((self._pending_retired[0],))
            self._pending_retired.pop(0)
            cleaned += 1
        return cleaned

    def begin_close(self):
        self.session.begin_close()
        self.queue.begin_close()

    def finish_close(self) -> bool:
        self.retry_cleanup()
        if not self.queue.finish_close():
            return False
        self._retire_segments(self.session.finish_close())
        return True
