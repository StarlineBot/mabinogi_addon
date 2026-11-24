"""말풍선 대사 데이터(docs/characters/다래_대사.md) — 상황별 무작위, 같은 줄 연속 금지.

데이터 파일 형식(제작자 잡담처럼 앱 배포 없이 늘릴 수 있게 — 내장본 + 원격 갱신본):
    {"schemaVersion": 1, "character": "다래",
     "lines": {"click_stand": ["…", …], …},        # 상황 → 줄 목록
     "alerts": {"비바체 연장.mp3": "…", …}}        # 알림 녹음 파일 → 같은 뜻의 말풍선
한 줄은 말풍선 두 줄(약 30자) 안 — 넘으면 그 줄만 버린다. 모르는 상황 이름도 받아 둔다(앞으로 늘릴 자리).
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

MAX_BYTES = 128 * 1024
MAX_CHARS = 30
SITUATIONS = (
    "click_stand", "click_sit", "click_sleep", "pet_start", "pet_during", "pet_end", "drag", "dropped",
    "game_enter", "game_exit", "long_hunt", "hello", "hello_long", "night", "morning", "idle",
    "annoyed_click", "annoyed_pet",
)


def _ok(text) -> bool:
    return (isinstance(text, str) and 0 < len(text) <= MAX_CHARS
            and not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in text))


@dataclass
class Lines:
    character: str
    lines: dict[str, tuple[str, ...]]
    alerts: dict[str, str]


def parse(data: bytes) -> Lines:
    if len(data) > MAX_BYTES:
        raise ValueError("lines data too large")
    try:
        raw = json.loads(data)
    except RecursionError as exc:
        raise ValueError("lines data too deeply nested") from exc
    if not isinstance(raw, dict) or raw.get("schemaVersion") != 1 or type(raw.get("schemaVersion")) is not int:
        raise ValueError("unsupported lines format")
    name, lines, alerts = raw.get("character"), raw.get("lines"), raw.get("alerts", {})
    if not isinstance(name, str) or not isinstance(lines, dict) or not isinstance(alerts, dict):
        raise ValueError("invalid lines data")
    out: dict[str, tuple[str, ...]] = {}
    for key, items in lines.items():
        if isinstance(key, str) and isinstance(items, list):
            kept = tuple(s for s in items[:64] if _ok(s))
            if kept:
                out[key] = kept
    if not out:
        raise ValueError("no usable lines")
    return Lines(name, out, {k: v for k, v in alerts.items() if isinstance(k, str) and _ok(v)})


def read(path: Path) -> Lines:
    with path.open("rb") as file:
        return parse(file.read(MAX_BYTES + 1))


@dataclass
class Picker:
    """상황별 무작위 고르기. 같은 상황에서 바로 앞 줄은 다시 안 고른다(줄이 둘 이상일 때)."""
    data: Lines
    rng: random.Random = field(default_factory=random.Random)
    _last: dict[str, str] = field(default_factory=dict)

    def pick(self, situation: str) -> str | None:
        items = self.data.lines.get(situation, ())
        if not items:
            return None
        choices = [s for s in items if s != self._last.get(situation)] or list(items)
        text = self.rng.choice(choices)
        self._last[situation] = text
        return text

    def alert(self, sound_file: str) -> str | None:
        """알림 녹음 파일 이름 → 같은 뜻의 말풍선(없으면 None — 말풍선 없이 알아챔만)."""
        return self.data.alerts.get(sound_file)
