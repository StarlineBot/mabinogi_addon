"""호감도(명세 3절 3번, 사용자 결정 11-24) — 0~100, 하루 최대 +20, 자정(이 PC 날짜) 초기화.

| 행동 | 오르는 양 | 하루 최대 |
| 그날 처음 앱 켜기 | +3 | 1번 |
| 쓰다듬기(끝까지) | +2 | 3번 |
| 그 캐릭터 목소리 알림 받기 | +1 | 7번 |
| 게임 중 구석에서 함께 30분 | +1 | 4번 |
반복 행동(10초 안 클릭 5번 이상 / 오늘 쓰다듬기를 다 채운 뒤 또) → −1 + 짜증 대사, 1분에 한 번만, 0 아래 없음.
숫자는 Rules(설정 값)로 — 나중에 조정. 저장은 캐릭터마다 dict 하나(config `character.affinity.<캐릭터>`, 동기화 대상).
구간 0/25/50/75/100은 값에서 계산만 한다(알파는 0구간 대사만 씀).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, fields

MAX_VALUE = 100
STAGES = (0, 25, 50, 75, 100)


@dataclass(frozen=True)
class Rules:
    daily_cap: int = 20
    launch: int = 3
    launch_times: int = 1
    pet: int = 2
    pet_times: int = 3
    alert: int = 1
    alert_times: int = 7
    corner: int = 1
    corner_times: int = 4
    corner_minutes: int = 30
    repeat_clicks: int = 5          # 이 횟수 이상이면
    repeat_window: float = 10.0     # 이 초 안에
    penalty: int = 1
    penalty_gap: float = 60.0       # −1은 이 초에 한 번만

    @classmethod
    def from_dict(cls, raw) -> Rules:
        """설정 값으로 덮어쓰기(모르는 키·잘못된 값은 무시)."""
        if not isinstance(raw, dict):
            return cls()
        kinds = {f.name: f.type for f in fields(cls)}
        out = {}
        for key, value in raw.items():
            if key in kinds and isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                out[key] = float(value) if kinds[key] in ("float", float) else int(value)
        return cls(**out)


ACTIONS = ("launch", "pet", "alert", "corner")


@dataclass
class Affinity:
    rules: Rules = field(default_factory=Rules)
    value: int = 0
    day: str = ""
    gained: int = 0                                   # 오늘 오른 양(상한 비교)
    counts: dict[str, int] = field(default_factory=dict)  # 오늘 행동별 횟수
    last_penalty: float = -1e18
    _clicks: deque = field(default_factory=deque)

    @classmethod
    def load(cls, raw, rules: Rules | None = None) -> Affinity:
        a = cls(rules or Rules())
        if isinstance(raw, dict):
            v = raw.get("value")
            a.value = max(0, min(MAX_VALUE, int(v))) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
            a.day = raw.get("day") if isinstance(raw.get("day"), str) else ""
            g = raw.get("gained")
            a.gained = int(g) if isinstance(g, int) and not isinstance(g, bool) and g >= 0 else 0
            c = raw.get("counts")
            if isinstance(c, dict):
                a.counts = {k: int(n) for k, n in c.items()
                            if k in ACTIONS and isinstance(n, int) and not isinstance(n, bool) and n >= 0}
        return a

    def to_dict(self) -> dict:
        return {"value": self.value, "day": self.day, "gained": self.gained, "counts": dict(self.counts)}

    def _roll(self, today: str) -> None:
        if today != self.day:  # 자정이 지났다 → 오늘 횟수·오른 양 초기화(값은 그대로)
            self.day, self.gained, self.counts = today, 0, {}

    def times_left(self, action: str, today: str) -> int:
        self._roll(today)
        return max(0, getattr(self.rules, f"{action}_times") - self.counts.get(action, 0))

    def gain(self, action: str, today: str) -> int:
        """행동 하나 → 실제로 오른 양(횟수·하루 상한·100 넘으면 그만큼 줄거나 0)."""
        if action not in ACTIONS:
            raise ValueError(action)
        if self.times_left(action, today) <= 0:
            return 0
        self.counts[action] = self.counts.get(action, 0) + 1
        amount = min(getattr(self.rules, action), self.rules.daily_cap - self.gained, MAX_VALUE - self.value)
        amount = max(0, amount)
        self.value += amount
        self.gained += amount
        return amount

    def penalize(self, now: float) -> bool:
        """반복 행동 −1(1분에 한 번만, 0 아래 없음). 내렸으면(또는 0이라 못 내렸어도 짜증은 냄) True."""
        if now - self.last_penalty < self.rules.penalty_gap:
            return False
        self.last_penalty = now
        self.value = max(0, self.value - self.rules.penalty)
        return True

    def click(self, now: float) -> bool:
        """클릭 하나 기록. 10초 안 5번 이상이면 −1(짜증) → True."""
        window = self.rules.repeat_window
        self._clicks.append(now)
        while self._clicks and now - self._clicks[0] > window:
            self._clicks.popleft()
        if len(self._clicks) >= self.rules.repeat_clicks:
            self._clicks.clear()
            return self.penalize(now)
        return False

    def petted(self, now: float, today: str) -> str:
        """쓰다듬기를 끝까지 함 → 'gain'(+2) / 'annoyed'(오늘 다 채운 뒤 또 → −1) / 'none'(−1을 1분 안에 이미 함)."""
        if self.times_left("pet", today) > 0:
            self.gain("pet", today)
            return "gain"
        return "annoyed" if self.penalize(now) else "none"

    @property
    def stage(self) -> int:
        return max(s for s in STAGES if self.value >= s)
