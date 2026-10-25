"""게임 프로세스가 바뀌었는지 판정(2026-10-25 사용자 결정 A: 내부 시계 추적기 전부 초기화). OS 없이 테스트한다.

게임을 껐다 켜면 새 게임 로고 화면에서 이전 버프가 남은 시간과 함께 그대로 보였다(앵커 미검출 → 동결 상태 유지).
초기화 기준은 창이 아니라 **프로세스**다. 새 프로세스(PID·시작 시각이 다름)가 보이면 바로, 게임 프로세스가 없으면
몇 초 유예 뒤 초기화한다(창 재생성·최소화처럼 창만 잠깐 안 잡히는 경우는 프로세스 생존 확인으로 걸러진다).
포커스(알트탭)·가림은 같은 프로세스라 초기화하지 않는다(지금처럼 동결 유지).
"""
from __future__ import annotations

GONE_GRACE_S = 3.0


class GameSession:
    def __init__(self, grace: float = GONE_GRACE_S) -> None:
        self.grace = grace
        self.identity = None  # 지금 추적 중인 게임 프로세스 (pid, 시작 시각)
        self._gone_since: float | None = None

    def update(self, identity, now: float) -> str | None:
        """identity: 지금 게임 프로세스(없으면 None). 초기화가 필요하면 이유('exit'|'restart'), 아니면 None."""
        if identity is not None:
            self._gone_since = None
            previous, self.identity = self.identity, identity
            if previous is not None and previous != identity:
                return 'restart'
            return None
        if self.identity is None:
            return None
        if self._gone_since is None:
            self._gone_since = now
            return None
        if now - self._gone_since >= self.grace:
            self.identity, self._gone_since = None, None
            return 'exit'
        return None
