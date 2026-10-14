"""최근 로그를 메모리에 보관(문의 '버그 신고' 첨부용).

터미널(stderr) 출력과 별개로 링버퍼 핸들러를 루트 로거에 하나 더 붙여, 최근 로그를
메모리에만 쌓아둔다. 문의하기에서 '버그'를 고르면 이 로그를 꺼내 Discord에 파일로
첨부한다. 파일을 만들지 않아 경로/정리 걱정이 없고, 앱 종료와 함께 사라진다.
"""

from __future__ import annotations

import logging
from collections import deque
from contextvars import ContextVar

run_id: ContextVar[str | None] = ContextVar("autofind_run_id", default=None)

_MAX_LINES = 2000  # DEBUG까지 담으므로 넉넉히(최근 맥락 유지)
_DEFAULT_FMT = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s"
_DEFAULT_DATEFMT = "%H:%M:%S"


class RingBufferHandler(logging.Handler):
    """최근 N줄만 보관하는 로그 핸들러."""

    def __init__(self, capacity: int = _MAX_LINES) -> None:
        super().__init__()
        self._buf: deque[tuple[str | None, str]] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._buf.append((run_id.get(), self.format(record)))
        except Exception:  # noqa: BLE001 — 로깅 중 예외는 삼킨다(표준 핸들러 관례)
            self.handleError(record)

    def text(self, *, scope: str | None = None, exclude_runs: bool = False) -> str:
        with self.lock:
            lines = list(self._buf)
        return "\n".join(line for tag, line in lines
                         if (scope is None or tag == scope) and (not exclude_runs or tag is None))


_handler: RingBufferHandler | None = None


def install(
    fmt: str = _DEFAULT_FMT, datefmt: str = _DEFAULT_DATEFMT
) -> RingBufferHandler:
    """루트 로거에 링버퍼 핸들러를 1회 설치(중복 설치 방지)."""
    global _handler
    if _handler is None:
        _handler = RingBufferHandler()
        _handler.setLevel(logging.DEBUG)  # 콘솔이 INFO여도 버퍼는 DEBUG까지 담는다
        _handler.setFormatter(logging.Formatter(fmt, datefmt))
        logging.getLogger().addHandler(_handler)
    return _handler


def recent_logs(max_chars: int = 150000, *, scope: str | None = None, exclude_runs: bool = False) -> str:
    """보관된 최근 로그(끝에서 max_chars). 미설치면 빈 문자열."""
    if _handler is None:
        return ""
    return _handler.text(scope=scope, exclude_runs=exclude_runs)[-max_chars:]
