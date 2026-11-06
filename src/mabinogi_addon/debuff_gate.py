"""디버프 오버레이를 보스바가 보일 때만(사용자 요청 2026-11-06). OS·Qt 없이 시각과 보스바 신호만으로 결정한다.

- 옵션 끔 또는 보스 체력바 영역 미등록 → 항상 표시(지금 동작).
- 보스바가 보이면 표시, 사라진 뒤 GRACE_SECONDS 더 표시(패턴·컷신·검은 바 깜빡임 방지), 다시 보이면 즉시.
- 게임 비활성(present=None, 판정 불가)이면 직전 상태 유지 — 블랙박스 전투 녹화와 같은 CombatGate 규칙.
숨겨진 동안도 디버프 탐지는 계속한다(창만 숨김).
"""
from __future__ import annotations

from .blackbox_combat import CombatGate

GRACE_SECONDS = 10.0


class DebuffOverlayGate:
    def __init__(self, grace: float = GRACE_SECONDS):
        self._gate = CombatGate(grace=grace)
        self.visible = True

    def update(self, now: float, *, enabled: bool, registered: bool, present) -> bool:
        if not enabled or not registered:
            self._gate.update(now, None, False)  # 상태 초기화(다시 켜면 보스바를 다시 볼 때까지 숨김)
            self.visible = True
            return True
        if present is None and self._gate.state in ("waiting", "unregistered"):
            return self.visible  # 판정 불가 → 직전 상태 유지(처음 켤 때 포함)
        self.visible = bool(self._gate.update(now, present, True))
        return self.visible
