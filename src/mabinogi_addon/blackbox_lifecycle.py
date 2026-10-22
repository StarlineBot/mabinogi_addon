"""네이티브 생산자와 저장 runtime의 비차단 종료 계약.

Windows 구현은 없다. CaptureContext/permit 검증은 session이 담당하고,
실제 HWND/PID 실행 식별·프레임/음성 수신·인코더 flush는 어댑터 구현 책임이다.
생산자는 request_stop에서 기다리지 않으며 is_stopped가 True일 때만 모든 콜백과
파일 쓰기가 끝난 것으로 간주한다. stop 요청과 실제 종료를 혼동하지 않는다.
"""
from typing import Protocol


class Producer(Protocol):
    def request_stop(self) -> None:
        """신규 수신을 중단하고 유한한 종료를 요청. 제어 스레드를 차단하지 않는다."""
        ...

    def is_stopped(self) -> bool:
        """콜백/쓰기/네이티브 핸들 정리가 모두 끝났으면 정확히 True."""
        ...


class BlackboxLifecycle:
    def __init__(self, runtime, spool, *, producers: tuple[Producer, ...]):
        self.runtime = runtime
        self.spool = spool
        self._producers = tuple(producers)
        self._requested = set()
        self._closing = False
        self._closed = False
        self.pending_reason = None

    def prepare_close(self) -> bool:
        """완료 시만 True. 타임아웃 강제종료/자동 폐기/권한 검사를 하지 않는다."""
        if self._closed:
            return True
        if not self._closing:
            self.runtime.begin_close()  # 먼저 permit 폐기·신규 저장 차단
            self._closing = True
        failures = []
        for index, producer in enumerate(self._producers):
            if index in self._requested:
                continue
            try:
                producer.request_stop()
                self._requested.add(index)
            except Exception as exc:
                failures.append(f'producer {index} stop failed: {exc}')
        if failures:
            self.pending_reason = '; '.join(failures)
            return False
        try:
            if not all(p.is_stopped() is True for p in self._producers):
                self.pending_reason = 'capture/encoder shutdown pending'
                return False
            if not self.runtime.finish_close():
                self.pending_reason = 'export results or recovery decisions pending'
                return False
            # runtime에서 retired 원본 정리가 끝난 뒤에만 전용 폴더를 닫는다.
            self.spool.close()
        except Exception as exc:
            self.pending_reason = f'cleanup pending: {exc}'
            return False
        self._closed = True
        self.pending_reason = None
        return True
