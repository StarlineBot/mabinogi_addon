"""호감도 2차 규칙(명세 3-2절 '하루 점수'·'구간 퀘스트'·'줄어들기'·'캐릭터 바꾸기', 사용자 11-25·11-26 게이지 배포 확정).

0~100, **하루 최대 10**(자정 = 이 PC 날짜 초기화). 오를 때 따로 표시하지 않음 — 동행 탭 숫자만 바뀌고 구간 오름만 연출.
① 같이 게임하기(게임 중 구석에서 함께) 30분마다 +1, 하루 최대 4.
② 행동(앱 켜기·클릭·쓰다듬기·말풍선 대사·그 캐릭터 목소리 알림)마다 확률 25%로 +1, 한 번 오르면 5분간 안 오름, 하루 최대 6.
③ 너무 자주 누르기(10초 안 5번)·오늘 쓰다듬기 3번을 채운 뒤 또 → −1 + 짜증 대사(1분에 한 번).

구간 퀘스트: 점수가 차도 퀘스트 전엔 구간 끝(24·49·74·99)에서 멈춤(퀘스트 진행은 미리 셈).
  25 = 세 개 다 — 2일 연속 쓰다듬기 · 2일 연속 찔러 보기(클릭) · 2일 연속 같이 게임하기(그날 30분 이상).
  50·75·100 퀘스트는 아직 없음(배포 순서 11-26) → 49에서 멈춤. 제작자가 직접 올린 값은 끌어내리지 않음.
구간(stage) = 깬 퀘스트 구간까지 중 값이 닿은 곳(25 퀘스트를 깨고 값이 25가 되는 순간 25 — 구간 대사·모션은 이 값으로 연다).
줄어들기: 앱을 3일 넘게 안 켜면 4일째부터 하루 −1. 캐릭터 바꾸기: `이 캐릭터로 적용`으로 떠나는 캐릭터 −3(하루 한 번).
바닥 = 퀘스트를 깬 구간(25 깼으면 25 아래로 안 내려감, 안 깼으면 0) — 바닥보다 이미 낮으면 그대로(올리지 않음).
숫자는 Rules(설정 값 config `character.rules`). 저장은 캐릭터마다 dict 하나(`character.affinity.<캐릭터>`, 동기화 대상).
"""
from __future__ import annotations

import datetime
import random
from collections import deque
from dataclasses import dataclass, field, fields

MAX_VALUE = 100
# 호감도 쌓기 스위치 — 11-26 게이지 배포로 켬(베타 동안은 False였음). False면 점수·퀘스트·줄어들기가 모두 멈춤.
GROWTH = True
STAGES = (0, 25, 50, 75, 100)
SEGMENT = 25
QUEST_KINDS = ("pet", "click", "game")     # 25 퀘스트 세 가지(2일 연속)
ACTIONS = ("launch", "click", "pet", "speech", "alert")   # 확률로 오르는 행동
AVAILABLE_QUESTS = 1                       # 지금 있는 구간 퀘스트 수(25만) — 그 위 구간은 준비 중


@dataclass(frozen=True)
class Rules:
    daily_cap: int = 10
    game_minutes: int = 30          # 같이 게임하기 이만큼마다 +1
    game_cap: int = 4
    action_chance: float = 0.25
    action_cooldown: float = 300.0  # 행동으로 오른 뒤 이 초 동안은 안 오름
    action_cap: int = 6
    quest_days: int = 2             # 25 퀘스트 — 연속 날 수
    quest_game_minutes: int = 30    # 같이 게임하기로 칠 그날 분
    pet_times: int = 3              # 쓰다듬기 하루 이만큼 넘으면 짜증
    repeat_clicks: int = 5          # 이 횟수 이상이면
    repeat_window: float = 10.0     # 이 초 안에
    penalty: int = 1
    penalty_gap: float = 60.0       # −1은 이 초에 한 번만
    decay_after_days: int = 3       # 이만큼 넘게 안 켜면 그다음 날부터 하루 −1
    leave_penalty: int = 3          # 캐릭터 바꾸기(떠나는 캐릭터)

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


QUEST_LABELS = {"pet": "쓰다듬기", "click": "찔러 보기", "game": "같이 게임하기"}
READINGS = {"Starline": "스타라인"}   # 영어 이름의 읽는 소리(조사 고르기용)


def _has_final(word: str) -> bool:
    """마지막 글자에 받침이 있는지(한글이 아니면 없음으로, 영어 이름은 READINGS의 읽는 소리로)."""
    word = READINGS.get(word, word)
    if not word:
        return False
    code = ord(word[-1]) - 0xAC00
    return 0 <= code <= 11171 and code % 28 != 0


def _int(value, default: int = 0) -> int:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else default


def _str(value) -> str:
    return value if isinstance(value, str) else ""


def _yesterday(day: str) -> str:
    try:
        return (datetime.date.fromisoformat(day) - datetime.timedelta(days=1)).isoformat()
    except ValueError:
        return ""


def days_between(earlier: str, later: str) -> int:
    """날짜 차(later − earlier). 모르면 0."""
    try:
        return (datetime.date.fromisoformat(later) - datetime.date.fromisoformat(earlier)).days
    except ValueError:
        return 0


@dataclass
class Affinity:
    rules: Rules = field(default_factory=Rules)
    value: int = 0
    cleared: int = 0                                  # 깬 구간 퀘스트 수(0~4)
    day: str = ""
    gained: int = 0                                   # 오늘 오른 양(하루 상한 비교)
    game_points: int = 0                              # 오늘 같이 게임하기로 오른 양
    action_points: int = 0                            # 오늘 행동으로 오른 양
    game_minutes: int = 0                             # 오늘 같이 게임한 분
    pets_today: int = 0                               # 오늘 쓰다듬기 횟수(3번 넘으면 짜증)
    quest: dict = field(default_factory=dict)         # 25 퀘스트: 종류 → {"last": 날짜, "run": 연속 날, "done": bool}
    left_day: str = ""                                # 떠나서 −3 깎인 날(하루 한 번)
    sulky: bool = False                               # 떠났다가 다시 돌아오면 서운함 한 줄
    last_action: float = -1e18                        # 행동으로 오른 때(이 실행 안에서만 — 5분 쿨다운)
    last_penalty: float = -1e18
    rng: random.Random = field(default_factory=random.Random)
    _clicks: deque = field(default_factory=deque)

    # ---- 저장 -------------------------------------------------------------------------------
    @classmethod
    def load(cls, raw, rules: Rules | None = None, rng: random.Random | None = None) -> Affinity:
        a = cls(rules or Rules())
        if rng is not None:
            a.rng = rng
        if isinstance(raw, dict):
            v = raw.get("value")
            a.value = max(0, min(MAX_VALUE, int(v))) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
            a.cleared = min(len(STAGES) - 1, _int(raw.get("cleared")))
            a.day = _str(raw.get("day"))
            a.left_day = _str(raw.get("leftDay"))
            a.sulky = raw.get("sulky") is True
            if raw.get("rules") == 2:   # 2차 규칙으로 저장된 오늘 값
                a.gained = _int(raw.get("gained"))
                a.game_points = _int(raw.get("gamePoints"))
                a.action_points = _int(raw.get("actionPoints"))
                a.game_minutes = _int(raw.get("gameMinutes"))
                a.pets_today = _int(raw.get("petsToday"))
                q = raw.get("quest")
                if isinstance(q, dict):
                    for kind in QUEST_KINDS:
                        item = q.get(kind)
                        if isinstance(item, dict):
                            a.quest[kind] = {"last": _str(item.get("last")), "run": _int(item.get("run")),
                                             "done": item.get("done") is True}
            else:   # 알파 규칙 저장 → 이전(점수 그대로, 25 이상이면 25 퀘스트 깬 것으로, 오늘 횟수는 새로)
                a.gained = 0
                a.day = ""
            if a.value >= SEGMENT:
                a.cleared = max(a.cleared, 1)
        return a

    def to_dict(self) -> dict:
        return {"rules": 2, "value": self.value, "cleared": self.cleared, "day": self.day, "gained": self.gained,
                "gamePoints": self.game_points, "actionPoints": self.action_points, "gameMinutes": self.game_minutes,
                "petsToday": self.pets_today, "quest": {k: dict(v) for k, v in self.quest.items()},
                "leftDay": self.left_day, "sulky": self.sulky}

    # ---- 구간·퀘스트 ---------------------------------------------------------------------------
    @property
    def stage(self) -> int:
        """열린 구간 — 깬 퀘스트 구간까지 중 값이 닿은 곳."""
        return SEGMENT * min(self.cleared, self.value // SEGMENT)

    def ceiling(self) -> int:
        """지금 멈추는 값 — 다음 구간 퀘스트를 깨기 전엔 그 구간 끝 바로 아래(24·49·74·99)."""
        if self.cleared >= len(STAGES) - 1:
            return MAX_VALUE
        return (self.cleared + 1) * SEGMENT - 1

    def floor(self) -> int:
        """줄어들기·바꾸기·반복 −1의 바닥 — 퀘스트를 깬 구간."""
        return SEGMENT * self.cleared

    def quest_run(self, kind: str) -> int:
        item = self.quest.get(kind) or {}
        return self.rules.quest_days if item.get("done") else int(item.get("run", 0))

    def quest_text(self, name: str | None = None) -> str:
        """동행 탭 카드 아래 한 줄 — 25 퀘스트 진행, 깬 뒤엔 다음 이야기 준비 중."""
        if self.cleared >= AVAILABLE_QUESTS:
            return "다음 이야기는 준비 중이에요"
        goal = self.rules.quest_days
        parts = [f"{QUEST_LABELS[k]} {min(goal, self.quest_run(k))}/{goal}" for k in QUEST_KINDS]
        return f"퀘스트: {goal}일 연속 — " + " · ".join(parts)

    def _mark(self, kind: str, today: str) -> None:
        """25 퀘스트 — 그날 그 종류를 함(연속 날 셈, 하루 건너뛰면 다시 1부터)."""
        item = self.quest.setdefault(kind, {"last": "", "run": 0, "done": False})
        if item["done"] or item["last"] == today:
            return
        item["run"] = item["run"] + 1 if item["last"] and item["last"] == _yesterday(today) else 1
        item["last"] = today
        if item["run"] >= self.rules.quest_days:
            item["done"] = True
        self._settle()

    def _settle(self) -> None:
        if self.cleared == 0 and all((self.quest.get(k) or {}).get("done") for k in QUEST_KINDS):
            self.cleared = 1

    def set_value(self, value: int) -> None:
        """제작자가 바로 바꿈 — 그 값까지의 구간 퀘스트는 깬 것으로(50 → 25·50 깸)."""
        self.value = max(0, min(MAX_VALUE, int(value)))
        self.cleared = min(len(STAGES) - 1, self.value // SEGMENT)

    # ---- 하루 ------------------------------------------------------------------------------
    def _roll(self, today: str) -> None:
        if today != self.day:   # 자정이 지났다 → 오늘 값 초기화(점수·퀘스트 연속은 그대로)
            self.day, self.gained, self.game_points, self.action_points = today, 0, 0, 0
            self.game_minutes, self.pets_today = 0, 0

    def _add(self, amount: int) -> int:
        """하루 상한·멈추는 값 안에서 올림 → 실제로 오른 양. 이미 멈추는 값보다 높으면(제작자 값) 안 오르고 안 내려감."""
        room = min(amount, self.rules.daily_cap - self.gained, self.ceiling() - self.value)
        if room <= 0:
            return 0
        self.value += room
        self.gained += room
        return room

    def _lower(self, amount: int) -> None:
        self.value = max(self.value - amount, min(self.value, self.floor()))

    # ---- 점수 ------------------------------------------------------------------------------
    def action(self, kind: str, now: float, today: str) -> int:
        """행동 하나 — 25% 확률로 +1(5분 쿨다운·하루 6)."""
        if kind not in ACTIONS:
            raise ValueError(kind)
        if not GROWTH:
            return 0
        self._roll(today)
        if self.action_points >= self.rules.action_cap or now - self.last_action < self.rules.action_cooldown:
            return 0
        if self.rng.random() >= self.rules.action_chance:
            return 0
        got = self._add(1)
        if got:
            self.action_points += got
            self.last_action = now
        return got

    def corner_minute(self, today: str) -> int:
        """게임 중 구석에서 함께 1분 — 30분마다 +1(하루 4), 그날 30분이면 25 퀘스트 '같이 게임하기'."""
        if not GROWTH:
            return 0
        self._roll(today)
        self.game_minutes += 1
        if self.game_minutes >= self.rules.quest_game_minutes:
            self._mark("game", today)
        got = 0
        if self.game_minutes % max(1, self.rules.game_minutes) == 0 and self.game_points < self.rules.game_cap:
            got = self._add(1)
            self.game_points += got
        return got

    def launched(self, now: float, today: str) -> int:
        return self.action("launch", now, today)

    def alerted(self, now: float, today: str) -> int:
        return self.action("alert", now, today)

    def spoke(self, now: float, today: str) -> int:
        """말풍선 대사가 나옴."""
        return self.action("speech", now, today)

    def poked(self, now: float, today: str) -> int:
        """캐릭터를 찔러 봄(클릭) — 25 퀘스트 '찔러 보기' + 행동 점수."""
        if not GROWTH:
            return 0
        self._roll(today)
        self._mark("click", today)
        return self.action("click", now, today)

    def decay(self, missed_days: int) -> int:
        """앱을 missed_days일 안 켬 → 3일 넘은 날마다 −1(바닥 아래 없음). 줄어든 양."""
        if not GROWTH:
            return 0
        before = self.value
        self._lower(max(0, missed_days - self.rules.decay_after_days))
        return before - self.value

    def leave(self, today: str) -> int:
        """`이 캐릭터로 적용`으로 이 캐릭터를 떠남 → −3(하루 한 번, 바닥 아래 없음). 다시 오면 서운함 한 줄."""
        if not GROWTH:
            return 0
        self.sulky = True
        if self.left_day == today:
            return 0
        self.left_day = today
        before = self.value
        self._lower(self.rules.leave_penalty)
        return before - self.value

    def take_sulk(self) -> bool:
        """돌아왔을 때 서운함 대사를 할 차례인지(한 번만)."""
        sulky, self.sulky = self.sulky, False
        return sulky

    def penalize(self, now: float) -> bool:
        """반복 행동 −1(1분에 한 번만, 바닥 아래 없음). 짜증 낼 차례면 True."""
        if now - self.last_penalty < self.rules.penalty_gap:
            return False
        self.last_penalty = now
        if GROWTH:
            self._lower(self.rules.penalty)
        return True   # 짜증 반응은 쌓기를 꺼도 그대로

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
        """쓰다듬기를 끝까지 함 → 'gain'(25 퀘스트·행동 점수) / 'annoyed'(오늘 3번 채운 뒤 또 → −1) / 'none'."""
        self._roll(today)
        if self.pets_today < self.rules.pet_times:
            self.pets_today += 1
            if GROWTH:
                self._mark("pet", today)
                self.action("pet", now, today)
            return "gain"
        return "annoyed" if self.penalize(now) else "none"
