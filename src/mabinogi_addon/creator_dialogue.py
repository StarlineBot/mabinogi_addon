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


# ---- 기능 추천·디스코드 권유(잡담 명세 17절, 0.47.0) ----------------------------------------------
# 추천할 수 있는 기능 키(17.3·17.5). 모르는 키는 tips에서 건너뛴다.
TIP_FEATURES = ("buff", "debuff", "boss", "halo", "stat_bars", "dorcha", "tuarim", "custom", "skillbar",
                "memo", "opt", "fps", "cursor", "blackbox", "keywords", "calc", "sketch", "harp")
TOOL_FEATURES = ("memo", "calc", "sketch", "harp")  # 켜고 끄는 값이 없는 도구 = 화면을 연 적 있는지로 판정
TIP_CHANCE = 0.25  # 대사를 띄우기로 정해졌을 때 약 4번에 1번꼴
MAX_BUTTON = 8
DEFAULT_BUTTON = "보러 가기"
INVITE_URL = "https://discord.gg/VTbJ29HPma"
INVITE_TEXT = "섯다라인 디스코드에서 새 기능 소식 먼저 보실래요? 아이디어도 받아요"
INVITE_DECLINE_DAYS = 45
INVITE_REPEAT_DAYS = 30


class Tip(tuple):
    """(id, feature, parts, button) — parts는 entries와 같은 조합 모양(tuple of tuple)."""
    __slots__ = ()

    def __new__(cls, ident, feature, parts, button):
        return super().__new__(cls, (ident, feature, parts, button))

    ident = property(lambda self: self[0])
    feature = property(lambda self: self[1])
    parts = property(lambda self: self[2])
    button = property(lambda self: self[3])


def _parts(parts):
    if not isinstance(parts, list) or not 1 <= len(parts) <= 32:
        return None
    normalized = []
    for part in parts:
        choices = [part] if isinstance(part, str) else part
        if not isinstance(choices, list) or not 1 <= len(choices) <= 64:
            return None
        if any(not isinstance(s, str) or not s or len(s) > MAX_CHARS
               or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in s) for s in choices):
            return None
        normalized.append(tuple(choices))
    if sum(max(map(len, choices)) for choices in normalized) > MAX_CHARS:
        return None
    return tuple(normalized)


def parse_tips(data: bytes):
    """dialogues.json 맨 위 `tips` 칸(17.4). `tips` 칸이 없으면 None(내장 추천 유지), 칸이 잘못되면 ()
    (기능 추천만 끔 — entries는 parse가 따로 읽어 그대로 쓴다). 항목 하나가 잘못되면 그 항목만 건너뛴다."""
    if len(data) > MAX_BYTES:
        return ()
    try:
        raw = json.loads(data)
    except (ValueError, RecursionError):
        return ()
    if not isinstance(raw, dict) or "tips" not in raw:
        return None
    tips = raw["tips"]
    if not isinstance(tips, list) or len(tips) > 256:
        return ()
    seen, result = set(), []
    for tip in tips:
        if not isinstance(tip, dict):
            continue
        ident, feature, button = tip.get("id"), tip.get("feature"), tip.get("button", DEFAULT_BUTTON)
        if (not isinstance(ident, str) or not 1 <= len(ident) <= 100 or ident in seen
                or feature not in TIP_FEATURES
                or not isinstance(button, str) or not 1 <= len(button) <= MAX_BUTTON or not button.strip()):
            continue
        parts = _parts(tip.get("parts"))
        if parts is None:
            continue
        seen.add(ident)
        result.append(Tip(ident, feature, parts, button))
    return tuple(result)


def read_tips(path: Path):
    with path.open("rb") as file:
        return parse_tips(file.read(MAX_BYTES + 1))


def invite_due(state: dict, now: float) -> bool:
    """디스코드 권유를 띄울 때인지(17.2): 참가하기 누른 적 있으면 다시 안 함, 괜찮아요는 45일 뒤, 그 밖엔 30일에 한 번."""
    state = state if isinstance(state, dict) else {}
    if state.get("joined") is True:
        return False
    declined, shown = state.get("declinedAt"), state.get("shownAt")
    if isinstance(declined, (int, float)) and now < declined + INVITE_DECLINE_DAYS * 86400:
        return False
    if isinstance(shown, (int, float)) and now < shown + INVITE_REPEAT_DAYS * 86400:
        return False
    return True


class TipPicker:
    """대사를 띄우기로 정해졌을 때 일반 대사 대신 무엇을 보일지(17.1·17.2). 순수 로직."""

    def __init__(self, tips=(), rng=None):
        self.tips = tuple(tips)
        self.rng = rng or random.Random()
        self.last_feature = None

    def pick(self, unused, *, invite_ok: bool, tip_ok: bool = True):
        """('invite', None) / ('tip', Tip) / None(일반 대사). 25% 차례에서 권유가 먼저, 직전 추천 기능만 뺀다."""
        if self.rng.random() >= TIP_CHANCE:
            return None
        if invite_ok:
            return ("invite", None)
        if not tip_ok:
            return None
        candidates = [t for t in self.tips if t.feature in unused and t.feature != self.last_feature]
        if not candidates:
            return None
        tip = self.rng.choice(candidates)
        return ("tip", tip)

    def shown(self, tip) -> None:
        self.last_feature = tip.feature
