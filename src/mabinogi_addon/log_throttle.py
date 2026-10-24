"""같은 미처리 예외의 반복 기록 억제. Qt 타이머 안에서 같은 예외가 100ms마다 나면 traceback이 초당 ~10건 쌓여
app.log(1MB×4 회전)가 약 30분 만에 이전 진단을 밀어낸다(0.14.1 실사용). 처음 1회는 traceback 전체를,
이후에는 EVERY회마다 한 줄 요약만 남긴다.
"""
from __future__ import annotations

import threading
import traceback

EVERY = 100


def exception_key(exc_type, tb) -> tuple:
    """예외 종류 + 발생 위치(마지막 프레임 파일·줄). 메시지는 값이 달라질 수 있어 빼고 본다."""
    frames = traceback.extract_tb(tb) if tb is not None else []
    last = frames[-1] if frames else None
    return (getattr(exc_type, '__name__', str(exc_type)),
            last.filename if last else '', last.lineno if last else 0)


class ExceptionThrottle:
    def __init__(self, every: int = EVERY) -> None:
        self.every = every
        self._counts: dict[tuple, int] = {}
        self._lock = threading.Lock()

    def record(self, key) -> tuple[str, int]:
        """('full'|'summary'|'skip', 누적 횟수)."""
        with self._lock:
            count = self._counts.get(key, 0) + 1
            self._counts[key] = count
        if count == 1:
            return 'full', count
        return ('summary' if count % self.every == 0 else 'skip'), count

    def log(self, logger, message, exc_info, *args) -> str:
        """기록하고 한 일('full'|'summary'|'skip')을 돌려준다."""
        exc_type, exc, tb = exc_info
        key = exception_key(exc_type, tb)
        action, count = self.record(key)
        if action == 'full':
            logger.critical(message, *args, exc_info=exc_info)
        elif action == 'summary':
            logger.critical(message + ' — 같은 예외 %d회 반복(%s:%s, 처음 1회만 traceback 기록): %s',
                            *args, count, key[1], key[2], f'{key[0]}: {exc}')
        return action
