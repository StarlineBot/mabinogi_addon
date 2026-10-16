"""제한된 선택형 대사 데이터와 실행별 추첨 상태. Qt/장치와 독립적이다."""

from __future__ import annotations

from collections import deque
import json
import random
from pathlib import Path

MAX_BYTES = 128 * 1024
MAX_CHARS = 60
RAW_URL = "https://raw.githubusercontent.com/StarlineBot/mabinogi_addon-releases/refs/heads/main/data/dialogues.json"


def parse(data: bytes) -> tuple:
    if len(data) > MAX_BYTES:
        raise ValueError("dialogue data too large")
    try:
        raw = json.loads(data)
    except RecursionError as exc:
        raise ValueError("dialogue data too deeply nested") from exc
    if (not isinstance(raw, dict) or type(raw.get("schemaVersion")) is not int
            or raw["schemaVersion"] != 1 or raw.get("language") != "ko-KR"
            or raw.get("format") != "choice-parts-v1"):
        raise ValueError("unsupported dialogue format")
    entries = raw.get("entries")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 512:
        raise ValueError("invalid entries")
    seen, result = set(), []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("invalid entry")
        ident, parts = entry.get("id"), entry.get("parts")
        if not isinstance(ident, str) or not 1 <= len(ident) <= 100 or ident in seen:
            raise ValueError("invalid entry id")
        seen.add(ident)
        if not isinstance(parts, list) or not 1 <= len(parts) <= 32:
            raise ValueError("invalid parts")
        normalized = []
        for part in parts:
            choices = [part] if isinstance(part, str) else part
            if not isinstance(choices, list) or not 1 <= len(choices) <= 64:
                raise ValueError("invalid choices")
            if any(not isinstance(s, str) or not s or len(s) > MAX_CHARS
                   or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in s) for s in choices):
                raise ValueError("invalid text")
            normalized.append(tuple(choices))
        if sum(max(map(len, choices)) for choices in normalized) > MAX_CHARS:
            raise ValueError("dialogue too long")
        result.append(tuple(normalized))
    return tuple(result)


def read(path: Path) -> tuple:
    with path.open("rb") as file:
        return parse(file.read(MAX_BYTES + 1))


class DialogueSession:
    def __init__(self, entries: tuple, rng=None):
        self.entries = entries
        self.rng = rng or random.Random()
        self.last_text = None
        self.last_draw = None
        self.shown = deque()

    def draw(self, now: float) -> bool:
        if self.last_draw is not None and now < self.last_draw + 120:
            return False
        self.last_draw = now
        while self.shown and self.shown[0] <= now - 600:
            self.shown.popleft()
        return self.rng.random() < (0.2 if len(self.shown) >= 3 else 0.4)

    def choose(self, fits=lambda text: True, *, fallback=None) -> str | None:
        if not self.entries:
            return None
        for _ in range(32):
            parts = self.rng.choice(self.entries)
            text = "".join(self.rng.choice(choices) for choices in parts)
            if text != self.last_text and text.strip() and fits(text):
                return text
        if fallback is not None:
            for parts in self.entries:
                text = fallback(parts)
                if text != self.last_text and text.strip() and fits(text):
                    return text
        return None

    def displayed(self, text: str, now: float, *, automatic: bool):
        self.last_text = text
        if automatic:
            self.shown.append(now)
