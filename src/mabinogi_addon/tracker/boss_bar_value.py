"""보스바 오버레이에 그릴 값(보스바 오버레이 명세 1·3절) — 화면과 무관한 순수 로직.

- 직전보다 RISE_LIMIT(5%p) 넘게 오르는 값은 **같은 값이 2번 연속**일 때만 반영(오독 한 번은 무시).
- 직전보다 DROP_LIMIT(10%p) 넘게 떨어지는 값도 **한 번 더** 비슷한 값(그 값 + 5%p 이하)이 읽혀야 반영 — 47→4(46.96 오독)→45에서
  4가 바로 반영돼 45가 '급상승'으로 막히던 고착을 막는다(11-05 수집). 실제로 크게 깎인 경우는 한 틱(0.3초) 늦게 반영된다.
  작은 하락(10%p 이하)은 바로.
- 못 읽은 판독(None)은 마지막 값을 '흐림'으로 두고, GONE_SECONDS(1.8초) 넘게 못 읽으면 숨김.
- 보스가 바뀌면(이름 키가 다르면) 처음부터 — 새 보스의 첫 값은 바로 쓴다(판독 신뢰도 하한은 판독기가 이미 거름).
"""
from __future__ import annotations

from dataclasses import dataclass

RISE_LIMIT = 5
DROP_LIMIT = 10
GONE_SECONDS = 1.8


@dataclass(frozen=True)
class Shown:
    value: int | None   # None이면 숨김
    boss: str | None    # 이름 키(등록 보스 id 또는 None=미등록)
    stale: bool         # 흐림(지금은 못 읽는 중)


class BossBarValue:
    def __init__(self, gone: float = GONE_SECONDS) -> None:
        self.gone = gone
        self.reset()

    def reset(self) -> None:
        self.value: int | None = None
        self.boss: str | None = None
        self.stale = False
        self._last_ok = None
        self._pending: int | None = None
        self._drop: int | None = None  # 확인 대기 중인 큰 하락 값
        self.rule: str | None = None  # 이번 update에서 시작된 방어 규칙(수집 태그): "unread" | "jump"

    def update(self, value: int | None, boss: str | None, now: float) -> Shown:
        self.rule = None
        if value is not None and not 0 <= value <= 100:
            value = None
        if value is None:
            self._pending = self._drop = None
            if self.value is not None:
                if not self.stale:
                    self.rule = "unread"  # 못 읽음 시작
                self.stale = True
                if self._last_ok is None or now - self._last_ok > self.gone:
                    rule = self.rule
                    self.reset()
                    self.rule = rule
            return self.shown()
        if boss is None and self.value is not None:
            boss = self.boss  # 이름 식별이 한 번 깜빡여도(미등록 경로로 읽힘) 같은 보스로 — 이름·패턴 선 유지
        if self.value is None or boss != self.boss:  # 첫 값·다른 보스
            self.value, self.boss, self._pending, self._drop = value, boss, None, None
        elif self.value - value > DROP_LIMIT:
            if self._drop is not None and value <= self._drop + RISE_LIMIT:  # 두 번째로 크게 낮은 값 → 반영
                self.value, self._pending, self._drop = value, None, None
            else:
                self._drop, self._pending = value, None
                self.rule = "drop"  # 급하락 보류
                self.stale = False
                self._last_ok = now
                return self.shown()
        elif value - self.value > RISE_LIMIT:
            if self._pending == value:  # 같은 값 2번 연속 → 반영
                self.value, self._pending = value, None
            else:
                self._pending, self._drop = value, None
                self.rule = "jump"  # 급상승 보류
                self.stale = False
                self._last_ok = now
                return self.shown()
        else:
            self.value, self._pending, self._drop = value, None, None
        self.stale = False
        self._last_ok = now
        return self.shown()

    def tick(self, now: float) -> Shown:
        """판독 없이 시간만 흐를 때(보스 탭 틱이 멈춤 등) 숨김 시각만 확인."""
        if self.value is not None and self._last_ok is not None and now - self._last_ok > self.gone:
            self.reset()
        return self.shown()

    def shown(self) -> Shown:
        return Shown(self.value, self.boss, self.stale)
