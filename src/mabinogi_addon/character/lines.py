"""말풍선 대사 데이터(docs/characters/다래_대사.md) — 상황별 무작위, 같은 줄 연속 금지.

데이터 파일 형식(제작자 잡담처럼 앱 배포 없이 늘릴 수 있게 — 내장본 + 원격 갱신본):
    {"schemaVersion": 1, "character": "다래",
     "lines": {"click_stand": ["…", {"text": "…", "mood": "explain"}, …], …},  # 상황 → 줄 목록(분위기는 선택)
     "alerts": {"비바체 연장.mp3": "…", …}}        # 알림 녹음 파일 → 같은 뜻의 말풍선
알림 값은 글 하나 또는 글 목록(레나 — 둘 중 무작위, 사용자 11-24). 예전 글 하나 형식도 그대로 읽는다.
한 줄은 말풍선 두 줄(약 30자) 안 — 넘으면 그 줄만 버린다. 모르는 상황 이름도 받아 둔다(앞으로 늘릴 자리).
분위기(사용자 11-24 말하기): normal(보통 — 입 3단계)·explain(설명 — 손짓·가리키기)·think(생각 — 턱에 손)·happy(기쁨 — 웃음).
없거나 모르는 값이면 normal.
schemaVersion 2(호감도 구간 대사, 사용자 11-24): 줄 객체에 선택 키 `stage`(0/25/50/75/100, 없거나 잘못되면 0)와
`voice`(팩 폴더 기준 상대 경로 예 "대사/구간_25.mp3" — 지금은 보관만, 재생은 녹음 뒤). 1도 그대로 읽는다.
고르기: 지금 구간 이하 stage 줄만 후보, 지금 구간과 같은 stage(>0) 줄은 2배 자주. 구간이 오르는 순간은 `stage_up`.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

MAX_BYTES = 128 * 1024
MAX_CHARS = 30
MOODS = ("normal", "explain", "think", "happy")
STAGES = (0, 25, 50, 75, 100)
SCHEMAS = (1, 2)
SITUATIONS = (
    "click_stand", "click_sit", "click_sleep", "pet_start", "pet_during", "pet_end", "drag", "dropped",
    "game_enter", "game_exit", "long_hunt", "hello", "hello_long", "night", "morning", "idle",
    "annoyed_click", "annoyed_pet",
    "came_back",   # 다른 캐릭터로 바꿨다가 돌아옴(호감도 2차 '캐릭터 바꾸기', 11-26)
)


def _ok(text) -> bool:
    return (isinstance(text, str) and 0 < len(text) <= MAX_CHARS
            and not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in text))


@dataclass(frozen=True)
class Line:
    text: str
    mood: str = "normal"
    stage: int = 0              # 이 구간부터 나옴
    voice: str | None = None    # 목소리 파일(팩 폴더 기준) — 보관만


def _voice(value) -> str | None:
    """팩 폴더 안 상대 경로만(절대 경로·'..'·제어 문자 없음, .mp3)."""
    if not isinstance(value, str) or not 0 < len(value) <= 80 or not value.endswith(".mp3"):
        return None
    parts = value.replace("\\", "/").split("/")
    if value.startswith(("/", "\\")) or ":" in value or any(p in ("", ".", "..") for p in parts):
        return None
    if any(ord(c) < 32 for c in value):
        return None
    return "/".join(parts)


@dataclass
class Lines:
    character: str
    lines: dict[str, tuple[Line, ...]]
    alerts: dict[str, tuple[str, ...]]


def _line(item) -> Line | None:
    stage, voice = 0, None
    if isinstance(item, dict):
        text, mood = item.get("text"), item.get("mood", "normal")
        raw = item.get("stage", 0)
        stage = raw if type(raw) is int and raw in STAGES else 0
        voice = _voice(item.get("voice"))
    else:
        text, mood = item, "normal"
    if not _ok(text):
        return None
    return Line(text, mood if mood in MOODS else "normal", stage, voice)


def parse(data: bytes) -> Lines:
    if len(data) > MAX_BYTES:
        raise ValueError("lines data too large")
    try:
        raw = json.loads(data)
    except RecursionError as exc:
        raise ValueError("lines data too deeply nested") from exc
    if not isinstance(raw, dict) or type(raw.get("schemaVersion")) is not int or raw["schemaVersion"] not in SCHEMAS:
        raise ValueError("unsupported lines format")
    name, lines, alerts = raw.get("character"), raw.get("lines"), raw.get("alerts", {})
    if not isinstance(name, str) or not isinstance(lines, dict) or not isinstance(alerts, dict):
        raise ValueError("invalid lines data")
    out: dict[str, tuple[Line, ...]] = {}
    for key, items in lines.items():
        if isinstance(key, str) and isinstance(items, list):
            kept = tuple(line for line in map(_line, items[:64]) if line is not None)
            if kept:
                out[key] = kept
    if not out:
        raise ValueError("no usable lines")
    return Lines(name, out, {k: v for k, v in ((k, _alert(v)) for k, v in alerts.items() if isinstance(k, str)) if v})


def _alert(value) -> tuple[str, ...]:
    """알림 값 — 글 하나 또는 글 목록(맞지 않는 글은 버림)."""
    items = value[:8] if isinstance(value, list) else [value]
    return tuple(text for text in items if _ok(text))


def read(path: Path) -> Lines:
    with path.open("rb") as file:
        return parse(file.read(MAX_BYTES + 1))


@dataclass
class Picker:
    """상황별 무작위 고르기. 같은 상황에서 바로 앞 줄은 다시 안 고른다(줄이 둘 이상일 때)."""
    data: Lines
    rng: random.Random = field(default_factory=random.Random)
    _last: dict[str, Line] = field(default_factory=dict)

    def pick(self, situation: str, stage: int = 0) -> Line | None:
        """지금 구간(stage) 이하 줄 중 무작위 — 지금 구간과 같은 구간(>0) 줄은 2배. 바로 앞 줄은 다시 안 고름."""
        items = [line for line in self.data.lines.get(situation, ()) if line.stage <= stage]
        if not items:
            return None
        choices = [line for line in items if line != self._last.get(situation)] or items
        weights = [2 if stage > 0 and line.stage == stage else 1 for line in choices]
        line = self.rng.choices(choices, weights=weights)[0]
        self._last[situation] = line
        return line

    def stage_up(self, stage: int) -> Line | None:
        """구간이 오르는 순간 한 번 — 그 구간의 stage_up 줄(없으면 None)."""
        items = [line for line in self.data.lines.get("stage_up", ()) if line.stage == stage]
        return self.rng.choice(items) if items else None

    def alert(self, sound_file: str) -> Line | None:
        """알림 녹음 파일 이름 → 같은 뜻의 말풍선(보통 분위기, 없으면 None — 말풍선 없이 알아챔만)."""
        texts = self.data.alerts.get(sound_file)
        if not texts and sound_file.endswith("2.mp3"):  # 추가 알림 줄이 아직 없으면 1차 말풍선으로
            texts = self.data.alerts.get(sound_file[:-5] + ".mp3")
        return Line(self.rng.choice(texts)) if texts else None
