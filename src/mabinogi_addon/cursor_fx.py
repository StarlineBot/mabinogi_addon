"""마우스 커서 표시(마우스 커서 명세) — Qt와 무관한 순수 계산.

- 설정 기본값·정리(저장값이 이상해도 안전한 값으로)
- 꼬리: 최근 커서 위치(시각 포함)에서 꼬리 길이(초) 안의 점만 남기고, 점마다 나이(0=방금 ~ 1=곧 사라짐)를 준다.
  커서가 멈추면 새 점이 생기지 않고, 남은 점이 다 사라지면 더 그릴 것이 없다(멈추면 다시 그리지 않음 — 명세 4절).
- 흔들어 찾기: 짧은 시간 안에 좌우 방향이 여러 번 바뀌고 충분히 움직였으면 흔든 것으로 본다.

커서 위치는 읽기만 한다. 입력을 만들거나 바꾸지 않는다.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

SHAPES = ("none", "ring", "scope", "lines")
TAILS = ("none", "dots", "line", "rainbow", "sparkle")
TAIL_SECONDS = {"short": 0.2, "normal": 0.3, "long": 0.45}
PRESET_COLORS = ("#1DD3B0", "#FFD43B", "#FF5A5F", "#FFFFFF", "#A78BFA")  # 민트·노랑·빨강·흰색·보라
DEFAULTS = {"enabled": False, "shape": "ring", "tail": "none", "shake": True, "color": "#FFD43B",
            "size": 40, "tailLength": "normal", "opacity": 100}
SIZE_RANGE = (20, 120)
OPACITY_RANGE = (20, 100)
SHAKE_SECONDS = 1.0  # 흔들면 원이 커졌다 돌아오는 시간
SHAKE_SCALE = 3.0  # 가장 클 때 배율
SPARKLE_LIMIT = 40  # 반짝이 조각 수 제한(CPU)


def clean_settings(raw) -> dict:
    """저장값을 안전한 설정으로. 모르는 값·범위 밖은 기본값/가장자리로."""
    raw = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULTS)
    if isinstance(raw.get("enabled"), bool):
        out["enabled"] = raw["enabled"]
    if isinstance(raw.get("shake"), bool):
        out["shake"] = raw["shake"]
    if raw.get("shape") in SHAPES:
        out["shape"] = raw["shape"]
    if raw.get("tail") in TAILS:
        out["tail"] = raw["tail"]
    if raw.get("tailLength") in TAIL_SECONDS:
        out["tailLength"] = raw["tailLength"]
    color = raw.get("color")
    if isinstance(color, str) and len(color) == 7 and color.startswith("#"):
        try:
            int(color[1:], 16)
            out["color"] = color.upper()
        except ValueError:
            pass
    for key, (low, high) in (("size", SIZE_RANGE), ("opacity", OPACITY_RANGE)):
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = int(min(high, max(low, round(value))))
    out["opacity"] = int(round(out["opacity"] / 10) * 10)  # 10%씩
    return out


@dataclass(frozen=True)
class TailPoint:
    x: float
    y: float
    age: float  # 0 = 방금, 1 = 곧 사라짐


class Trail:
    """최근 커서 위치. 같은 자리(1px 미만 이동)는 점을 늘리지 않는다."""

    def __init__(self, max_points: int = 120) -> None:
        self._points: deque[tuple[float, float, float]] = deque(maxlen=max_points)

    def clear(self) -> None:
        self._points.clear()

    def add(self, t: float, x: float, y: float) -> bool:
        """새 위치. 움직였으면 True."""
        if self._points:
            _, lx, ly = self._points[-1]
            if abs(x - lx) < 1 and abs(y - ly) < 1:
                return False
        self._points.append((t, float(x), float(y)))
        return True

    def points(self, now: float, seconds: float) -> list[TailPoint]:
        """꼬리 길이(초) 안의 점(오래된 것부터). 오래된 점은 버린다."""
        while self._points and now - self._points[0][0] > seconds:
            self._points.popleft()
        if seconds <= 0:
            return []
        return [TailPoint(x, y, min(1.0, max(0.0, (now - t) / seconds))) for t, x, y in self._points]

    def active(self, now: float, seconds: float) -> bool:
        """아직 그릴 꼬리가 남았는지(멈춘 뒤 다 사라지면 False → 다시 그리지 않음)."""
        return any(now - t <= seconds for t, _, _ in self._points) and len(self._points) > 1


def bounds(points, pad: float) -> tuple[int, int, int, int] | None:
    """점들을 덮는 최소 상자(x, y, w, h) + 여백. 화면 전체 창을 쓰지 않으려고 꼬리 범위만큼만."""
    if not points:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    x0, y0 = math.floor(min(xs) - pad), math.floor(min(ys) - pad)
    x1, y1 = math.ceil(max(xs) + pad), math.ceil(max(ys) + pad)
    return x0, y0, max(1, x1 - x0), max(1, y1 - y0)


class ShakeDetector:
    """흔들어 찾기 판정: window초 안에 좌우 방향이 turns번 이상 바뀌고, 가로 이동 합이 distance 이상이면 흔든 것.
    한 번 판정하면 cooldown초 동안 다시 판정하지 않는다. 작은 떨림(step px 미만)은 방향 바뀜으로 세지 않는다."""

    def __init__(self, window: float = 0.5, turns: int = 3, distance: float = 400.0, step: float = 6.0,
                 cooldown: float = SHAKE_SECONDS) -> None:
        self.window, self.turns, self.distance, self.step, self.cooldown = window, turns, distance, step, cooldown
        self._samples: deque[tuple[float, float]] = deque()
        self._until = -1e9

    def add(self, t: float, x: float) -> bool:
        self._samples.append((t, float(x)))
        while self._samples and t - self._samples[0][0] > self.window:
            self._samples.popleft()
        if t < self._until or len(self._samples) < 3:
            return False
        turns, travel, direction, anchor = 0, 0.0, 0, self._samples[0][1]
        prev = anchor
        for _, x in list(self._samples)[1:]:
            travel += abs(x - prev)
            prev = x
            delta = x - anchor
            if abs(delta) < self.step:
                continue
            sign = 1 if delta > 0 else -1
            if direction and sign != direction:
                turns += 1
            direction, anchor = sign, x
        if turns >= self.turns and travel >= self.distance:
            self._samples.clear()
            self._until = t + self.cooldown
            return True
        return False


def shake_scale(elapsed: float) -> float:
    """흔든 뒤 elapsed초의 원 배율: 1 → SHAKE_SCALE → 1(SHAKE_SECONDS 동안), 그 밖은 1."""
    if elapsed < 0 or elapsed >= SHAKE_SECONDS:
        return 1.0
    return 1.0 + (SHAKE_SCALE - 1.0) * math.sin(math.pi * elapsed / SHAKE_SECONDS)


def sparkle_offsets(index: int, size: float) -> tuple[float, float]:
    """반짝이 조각의 흩어짐(점 번호로 정해지는 값 — 다시 그려도 떨리지 않게)."""
    a = (index * 2654435761) % 1000 / 1000 * 2 * math.pi
    r = ((index * 40503) % 1000 / 1000) * size * 0.35
    return math.cos(a) * r, math.sin(a) * r
