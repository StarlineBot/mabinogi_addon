"""호감도(명세 3절 3번, 사용자 최종 규칙 11-24 c8797ef) — 0~100, 하루 최대 +10, 자정(이 PC 날짜) 초기화.

| 행동 | 오르는 양 | 하루 최대 |
| 그날 처음 앱 켜기 | +2 | 1번 |
| 쓰다듬기(끝까지) | +1 | 3번 |
| 그 캐릭터 목소리 알림 받기 | +1 | 3번 |
| 게임 중 구석에서 함께 30분 | +1 | 2번 |

구간 0/25/50/75/100: 구간 끝(25·50·75·100)에 닿으면 더 오르지 않고 멈춤 → 그 구간 퀘스트를 깨면 다음 구간으로(이어 쌓임).
퀘스트 진행은 미리 센다(끝에 닿기 전에 깨 두면 닿자마자 넘어감).
  0→25 처음 쓰다듬기 1번 / 25→50 게임 중 구석에서 함께 누적 60분 / 50→75 그 캐릭터 목소리 알림 누적 10번 / 75→100 7일 연속 앱 켜기
구간(stage)은 깬 퀘스트 수 × 25 — 구간 대사는 이 값으로 연다.
반복 행동(10초 안 클릭 5번 이상 / 오늘 쓰다듬기를 다 채운 뒤 또) → −1 + 짜증 대사, 1분에 한 번만, 0·지금 구간 시작점 아래로 안 내려감.
숫자·퀘스트 목표는 Rules(설정 값 config `character.rules`)로. 저장은 캐릭터마다 dict 하나(`character.affinity.<캐릭터>`, 동기화 대상).
"""
from __future__ import annotations

import datetime
from collections import deque
from dataclasses import dataclass, field, fields

MAX_VALUE = 100
STAGES = (0, 25, 50, 75, 100)
SEGMENT = 25


@dataclass(frozen=True)
class Rules:
    daily_cap: int = 10
    launch: int = 2
    launch_times: int = 1
    pet: int = 1
    pet_times: int = 3
    alert: int = 1
    alert_times: int = 3
    corner: int = 1
    corner_times: int = 2
    corner_minutes: int = 30
    quest_pets: int = 1             # 0→25 처음 쓰다듬기
    quest_corner_minutes: int = 60  # 25→50 구석에서 함께 누적
    quest_alerts: int = 10          # 50→75 목소리 알림 누적
    quest_streak_days: int = 7      # 75→100 연속 앱 켜기
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
TOTALS = ("pets", "corner_minutes", "alerts")
# 구간 퀘스트(깬 수 = 인덱스): (진행 값 이름, 목표 Rules 이름, 화면 글, 단위)
# 화면 글: (이름 없을 때, 이름 있을 때) — 고른 캐릭터 이름이 들어감(예: '아리아를 처음으로 쓰다듬어 주기')
QUESTS = (
    ("pets", "quest_pets", ("처음 쓰다듬기", "{name}{eul} 처음으로 쓰다듬어 주기"), "번"),
    ("corner_minutes", "quest_corner_minutes", ("구석에서 함께 {hours}", "구석에서 {name}{wa} 함께 {hours}"), "분"),
    ("alerts", "quest_alerts", ("목소리 알림 {n}번", "{name} 목소리로 알림 {n}번"), "번"),
    ("streak", "quest_streak_days", ("{n}일 연속 켜기", "{n}일 연속 켜기"), "일"),
)


READINGS = {"Starline": "스타라인"}   # 영어 이름의 읽는 소리(조사 을/를·과/와 고르기용)


def _has_final(word: str) -> bool:
    """마지막 글자에 받침이 있는지(한글이 아니면 없음으로, 영어 이름은 READINGS의 읽는 소리로)."""
    word = READINGS.get(word, word)
    if not word:
        return False
    code = ord(word[-1]) - 0xAC00
    return 0 <= code <= 11171 and code % 28 != 0


def _int(value, default: int = 0) -> int:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else default


@dataclass
class Affinity:
    rules: Rules = field(default_factory=Rules)
    value: int = 0
    cleared: int = 0                                  # 깬 구간 퀘스트 수(0~4)
    day: str = ""
    gained: int = 0                                   # 오늘 오른 양(상한 비교)
    counts: dict[str, int] = field(default_factory=dict)  # 오늘 행동별 횟수
    corner_today: int = 0                             # 오늘 구석에서 함께한 분(30분마다 +1)
    totals: dict[str, int] = field(default_factory=dict)  # 퀘스트 누적(쓰다듬기·구석 분·알림)
    streak: int = 0                                   # 연속 켠 날
    last_launch: str = ""
    last_penalty: float = -1e18
    _clicks: deque = field(default_factory=deque)

    # ---- 저장 -------------------------------------------------------------------------------
    @classmethod
    def load(cls, raw, rules: Rules | None = None) -> Affinity:
        a = cls(rules or Rules())
        if isinstance(raw, dict):
            v = raw.get("value")
            a.value = max(0, min(MAX_VALUE, int(v))) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
            a.cleared = min(len(QUESTS), _int(raw.get("cleared")))
            a.day = raw.get("day") if isinstance(raw.get("day"), str) else ""
            a.gained = _int(raw.get("gained"))
            a.corner_today = _int(raw.get("cornerToday"))
            c = raw.get("counts")
            if isinstance(c, dict):
                a.counts = {k: _int(n) for k, n in c.items() if k in ACTIONS and _int(n, -1) >= 0}
            t = raw.get("totals")
            if isinstance(t, dict):
                a.totals = {k: _int(n) for k, n in t.items() if k in TOTALS and _int(n, -1) >= 0}
            a.streak = _int(raw.get("streak"))
            a.last_launch = raw.get("lastLaunch") if isinstance(raw.get("lastLaunch"), str) else ""
            a._settle()
        return a

    def to_dict(self) -> dict:
        return {"value": self.value, "cleared": self.cleared, "day": self.day, "gained": self.gained,
                "counts": dict(self.counts), "cornerToday": self.corner_today, "totals": dict(self.totals),
                "streak": self.streak, "lastLaunch": self.last_launch}

    # ---- 구간·퀘스트 ---------------------------------------------------------------------------
    @property
    def stage(self) -> int:
        return STAGES[self.cleared]

    def ceiling(self) -> int:
        """지금 구간 끝 — 퀘스트를 깨기 전엔 여기서 멈춤."""
        return min(MAX_VALUE, (self.cleared + 1) * SEGMENT)

    def progress(self, index: int) -> int:
        key = QUESTS[index][0]
        return self.streak if key == "streak" else self.totals.get(key, 0)

    def quest_done(self, index: int) -> bool:
        return self.progress(index) >= getattr(self.rules, QUESTS[index][1])

    def quest_text(self, name: str | None = None) -> str:
        """카드 아래 한 줄 — 지금 구간 퀘스트와 진행(예: '퀘스트: 구석에서 다래와 함께 1시간 · 35/60분').
        name이 있으면 그 캐릭터 이름을 넣는다(없거나 '???'면 이름 없는 글)."""
        if self.cleared >= len(QUESTS):
            return "퀘스트: 모두 깼어요"
        key, goal_name, labels, unit = QUESTS[self.cleared]
        goal = getattr(self.rules, goal_name)
        hours = f"{goal // 60}시간" if goal % 60 == 0 else f"{goal}분"
        named = bool(name) and name != "???"
        final = _has_final(name or "")
        text = labels[1 if named else 0].format(n=goal, hours=hours, name=name or "",
                                                eul="을" if final else "를", wa="과" if final else "와")
        return f"퀘스트: {text} · {min(self.progress(self.cleared), goal)}/{goal}{unit}"

    def _settle(self) -> None:
        """구간 끝에 닿았고 그 구간 퀘스트를 깼으면 다음 구간으로(여러 개 미리 깼으면 이어서)."""
        while self.cleared < len(QUESTS) and self.value >= self.ceiling() and self.quest_done(self.cleared):
            self.cleared += 1
        self.value = min(self.value, self.ceiling())

    def set_value(self, value: int) -> None:
        """제작자가 바로 바꿈 — 그 값까지의 구간 퀘스트는 깬 것으로(50 → 0→25·25→50 깸). 오늘 횟수는 그대로."""
        self.value = max(0, min(MAX_VALUE, int(value)))
        self.cleared = min(len(QUESTS), self.value // SEGMENT)

    # ---- 하루 ------------------------------------------------------------------------------
    def _roll(self, today: str) -> None:
        if today != self.day:  # 자정이 지났다 → 오늘 횟수·오른 양 초기화(값·퀘스트 누적은 그대로)
            self.day, self.gained, self.counts, self.corner_today = today, 0, {}, 0

    def times_left(self, action: str, today: str) -> int:
        self._roll(today)
        return max(0, getattr(self.rules, f"{action}_times") - self.counts.get(action, 0))

    def gain(self, action: str, today: str) -> int:
        """행동 하나 → 실제로 오른 양(횟수·하루 상한·구간 끝에서 줄거나 0)."""
        if action not in ACTIONS:
            raise ValueError(action)
        if self.times_left(action, today) <= 0:
            return 0
        self.counts[action] = self.counts.get(action, 0) + 1
        self._settle()  # 이 행동으로 퀘스트를 막 깼으면 먼저 다음 구간으로
        left = max(0, min(getattr(self.rules, action), self.rules.daily_cap - self.gained))
        amount = 0
        while left > 0:  # 구간 끝에 닿아 미리 깬 퀘스트로 넘어가면 남은 양이 이어서 쌓임
            step = min(left, self.ceiling() - self.value)
            if step <= 0:
                break
            self.value += step
            amount += step
            left -= step
            self._settle()
        self.gained += amount
        return amount

    # ---- 행동 ------------------------------------------------------------------------------
    def launched(self, today: str) -> int:
        """앱 켜기 — 연속 켠 날을 세고 그날 처음이면 +2."""
        if self.last_launch != today:
            try:
                yesterday = (datetime.date.fromisoformat(today) - datetime.timedelta(days=1)).isoformat()
            except ValueError:
                yesterday = ""
            self.streak = self.streak + 1 if self.last_launch == yesterday else 1
            self.last_launch = today
        return self.gain("launch", today)

    def alerted(self, today: str) -> int:
        self.totals["alerts"] = self.totals.get("alerts", 0) + 1
        return self.gain("alert", today)

    def corner_minute(self, today: str) -> int:
        """게임 중 구석에서 함께 1분 — 퀘스트 누적, 오늘 30분마다 +1."""
        self._roll(today)
        self.totals["corner_minutes"] = self.totals.get("corner_minutes", 0) + 1
        self.corner_today += 1
        got = 0
        if self.corner_today % max(1, self.rules.corner_minutes) == 0:
            got = self.gain("corner", today)
        self._settle()
        return got

    def penalize(self, now: float) -> bool:
        """반복 행동 −1(1분에 한 번만, 0·지금 구간 시작점 아래 없음). 짜증 낼 차례면 True."""
        if now - self.last_penalty < self.rules.penalty_gap:
            return False
        self.last_penalty = now
        self.value = max(self.stage, self.value - self.rules.penalty)
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
        """쓰다듬기를 끝까지 함 → 'gain'(+1·퀘스트 누적) / 'annoyed'(오늘 다 채운 뒤 또 → −1) / 'none'."""
        if self.times_left("pet", today) > 0:
            self.totals["pets"] = self.totals.get("pets", 0) + 1
            self.gain("pet", today)
            return "gain"
        return "annoyed" if self.penalize(now) else "none"
