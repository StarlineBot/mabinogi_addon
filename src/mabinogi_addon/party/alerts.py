"""키워드 알림 중복 억제. (섯다라인봇 shouldAlert 포팅)

서명별 5분 슬라이딩 TTL: 같은 파티가 5분 안에 계속 외쳐도 알림은 1회.
5분간 조용하면 '모집 끝'으로 보고 다음에 다시 뜨면 재알림.
"""

from __future__ import annotations

import time

TTL_SEC = 5 * 60


class AlertState:
    def __init__(self) -> None:
        self._seen: dict[str, float] = {}

    def should_alert(self, signature: str, now: float | None = None) -> bool:
        """이 서명에 지금 알림을 내야 하나. 만료 서명 정리 후 판정, 매 호출 시각 갱신."""
        now = time.monotonic() if now is None else now
        for sig in list(self._seen):
            if now - self._seen[sig] > TTL_SEC:
                del self._seen[sig]
        is_new = signature not in self._seen
        self._seen[signature] = now  # 계속 외치면 갱신돼 재알림 안 됨
        return is_new
