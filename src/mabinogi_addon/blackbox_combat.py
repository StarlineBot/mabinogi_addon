"""블랙박스 '전투 녹화' 판정(명세 12.2). OS·Qt 없이 시각과 보스바 신호만으로 결정한다.

- 보스 체력바 영역이 없으면 녹화하지 않는다(평소 녹화로 몰래 대체하지 않음).
- 보스바가 보이면 녹화, 사라진 뒤 GRACE_SECONDS 동안 더 녹화하고 멈춘다. 다시 보이면 이어서.
- 게임이 뒤에 있어 판정할 수 없는 동안(present=None)은 직전 전투 상태를 그대로 유지한다(유예 시간도 흐르지 않음).
"""
from __future__ import annotations

GRACE_SECONDS = 60.0  # 보스와 멀어짐·페이즈 전환·컷신·사망 대비(2026-10-23 사용자 보정)


class CombatGate:
    def __init__(self, grace=GRACE_SECONDS):
        self.grace = grace
        self._last_seen = None  # 마지막으로 보스바를 본 시각(판정 불가 시간은 빼고 셈)
        self._last_now = None
        self.state = 'waiting'  # 'unregistered' | 'waiting' | 'recording' | 'grace'
        self.grace_left = 0

    def update(self, now, present, registered):
        """present: True/False(판정함) 또는 None(게임이 뒤에 있어 판정 불가). 녹화 여부를 돌려준다."""
        if self._last_now is not None and present is None and self._last_seen is not None:
            self._last_seen += now - self._last_now  # 판정 불가 동안은 시간을 멈춘 것처럼 유지
        self._last_now = now
        if not registered:
            self._last_seen = None
            self.state, self.grace_left = 'unregistered', 0
            return False
        if present:
            self._last_seen = now
        if present is None and self.state in ('waiting', 'unregistered'):
            return False
        if self._last_seen is None:
            self.state, self.grace_left = 'waiting', 0
            return False
        since = now - self._last_seen
        if since <= 0:
            self.state, self.grace_left = 'recording', 0
            return True
        if since < self.grace:
            self.state, self.grace_left = 'grace', int(self.grace - since + 0.999)
            return True
        self._last_seen = None
        self.state, self.grace_left = 'waiting', 0
        return False
