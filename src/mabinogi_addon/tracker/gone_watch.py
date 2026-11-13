"""버프 '사라짐 경고' 확정 판단(포커스 복귀 유예 포함, 0.47.1 — 사용자 결정 11-13). Qt 없는 순수 로직.

- 경고를 켠 버프가 목록에서 빠지면 그 시각(사라진 시각)을 기억한다. 게임을 안 보는 동안(알트탭·듀얼 모니터)에도
  판단은 버리지 않고 계속 기억만 한다.
- 확정 시각 = max(사라진 시각 + CONFIRM_SEC, 마지막 포커스 복귀 시각 + GRACE_SEC). 확정은 게임을 보고 있을 때만.
  · 게임만 보고 있으면 예전처럼 사라지고 3초.
  · 다른 창을 보는 사이 빠졌거나, 나갈 때 있었는데 돌아와 보니 없는 버프는 복귀 5초에(예전엔 아예 안 울렸다).
- 그 전에 다시 보이면 취소. 복귀 유예와 관련된 취소(안 보는 사이 빠짐·복귀 5초 안)는 따로 알려 로그에 남긴다.
"""

from __future__ import annotations

CONFIRM_SEC = 3.0
GRACE_SEC = 5.0


class GoneWatch:
    def __init__(self, confirm_sec: float = CONFIRM_SEC, grace_sec: float = GRACE_SEC) -> None:
        self.confirm_sec = confirm_sec
        self.grace_sec = grace_sec
        self.game_active = True
        self.back_at: float | None = None  # 마지막 포커스 복귀 시각
        self.away_at: float | None = None  # 마지막 포커스 나간 시각
        self.absent_since: dict[str, float] = {}
        self.present_prev: set[str] = set()
        self.away_present: set[str] = set()  # 나갈 때 떠 있던 경고 버프(복귀 뒤 없으면 대상)
        self._check_away = False

    def focus(self, active: bool, now: float, warn_ids: set[str]) -> bool:
        """포커스 전환을 알린다. 실제로 바뀌었으면 True."""
        if active == self.game_active:
            return False
        self.game_active = active
        if active:
            self.back_at = now
            self._check_away = True
        else:
            self.away_at = now
            self.away_present = self.present_prev & set(warn_ids)
            self._check_away = False
        return True

    def due(self, since: float) -> float:
        at = since + self.confirm_sec
        if self.back_at is not None:
            at = max(at, self.back_at + self.grace_sec)
        return at

    def _focus_related(self, since: float, now: float) -> bool:
        if self.back_at is None:
            return False
        return now < self.back_at + self.grace_sec or (self.away_at is not None and since <= self.back_at)

    def update(self, active_ids: set[str], warn_ids: set[str], now: float, *, skip: set[str] = frozenset()):
        """한 틱. (확정 [(id, 안 보인 초)], 복귀 유예 취소 [(id, 안 보인 초)]). skip = 이미 경고 표시 중인 버프."""
        cancelled = []
        for bid in active_ids:
            since = self.absent_since.pop(bid, None)
            if since is not None and self._focus_related(since, now):
                cancelled.append((bid, now - since))
        for bid in self.present_prev - active_ids:
            if bid in warn_ids and bid not in skip:
                self.absent_since.setdefault(bid, now)
        if self.game_active and self._check_away:
            # 나갈 때 있었는데 돌아와 보니 없는 버프: 복귀 시각부터 없던 것으로(→ 복귀 5초에 확정)
            for bid in self.away_present - active_ids:
                if bid in warn_ids and bid not in skip:
                    self.absent_since.setdefault(bid, self.back_at)
            self.away_present = set()
            self._check_away = False
        self.present_prev = set(active_ids)
        for bid in [b for b in self.absent_since if b not in warn_ids]:
            del self.absent_since[bid]  # 경고를 끈 버프는 잊는다
        confirmed = []
        if self.game_active:
            for bid, since in list(self.absent_since.items()):
                if now >= self.due(since):
                    confirmed.append((bid, now - since))
                    del self.absent_since[bid]
        return confirmed, cancelled
