"""마우스 커서 효과 그리기(오버레이 창과 탭 미리보기가 같이 쓴다). 선과 점으로만 그린다(명세 3절)."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from ..cursor_fx import SPARKLE_LIMIT, smooth, sparkle_offsets


def _color(hex_color: str, alpha: float) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def paint_ring(p: QPainter, center: QPointF, size: float, color: str, opacity: float) -> None:
    """원: 반투명 채움 + 굵은 테두리."""
    r = size / 2
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(_color(color, 0.22 * opacity))
    p.setPen(QPen(_color(color, opacity), max(2.0, size / 14)))
    p.drawEllipse(center, r, r)


def paint_scope(p: QPainter, center: QPointF, size: float, color: str, opacity: float) -> None:
    """스코프(짧은 십자): 가운데가 빈 십자 + 얇은 원."""
    r = size / 2
    gap = size * 0.18
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(_color(color, opacity), 1.5))
    p.drawEllipse(center, r * 0.7, r * 0.7)
    p.setPen(QPen(_color(color, opacity), 2.0))
    cx, cy = center.x(), center.y()
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        p.drawLine(QPointF(cx + dx * gap, cy + dy * gap), QPointF(cx + dx * r, cy + dy * r))


def paint_tail(p: QPainter, points, kind: str, color: str, size: float, opacity: float,
               offset: QPointF = QPointF(0, 0), multicolor: bool = False) -> None:
    """꼬리. points: cursor_fx.TailPoint(오래된 것부터), offset: 창 왼쪽 위의 화면 좌표(빼서 창 안 좌표로).
    multicolor: 반짝이를 여러 색으로(색을 직접 고르기 전 기본). 선·무지개 선·점은 곡선으로 메운 점을 쓴다."""
    if len(points) < 2 or kind == "none":
        return
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if kind in ("line", "rainbow", "dots"):
        points = smooth(points)
    pts = [(QPointF(pt.x - offset.x(), pt.y - offset.y()), 1.0 - pt.age) for pt in points]
    base = max(3.0, size * 0.16)
    if kind == "dots":
        p.setPen(Qt.PenStyle.NoPen)
        gap = base * 3.0  # 점 사이 거리(px) — 최근 점부터 이 간격마다 하나씩(촘촘하지 않게)
        last = None
        for q, life in reversed(pts):
            if last is not None and math.hypot(q.x() - last.x(), q.y() - last.y()) < gap:
                continue
            last = q
            p.setBrush(_color(color, opacity * life))
            r = base * (0.35 + 0.65 * life)
            p.drawEllipse(q, r, r)
    elif kind in ("line", "rainbow"):
        # 가운데 조각은 평평한 끝(FlatCap) — 짧은 조각마다 둥근 끝이면 반투명 겹침이 구슬처럼 보인다.
        # 머리(가장 최근) 끝만 둥근 점으로 마무리한다.
        # 점 몇 개씩 한 경로(같은 굵기·색)로 그어 이음매를 줄인다 — 조각마다 끊으면 반투명 겹침이 구슬처럼 보임.
        n = len(pts)
        group = 3  # 묶음이 길면 색·굵기 단계가 보인다(0.36.1 세분 축소 뒤 3)
        for start in range(0, n - 1, group):
            chunk = pts[start:min(n, start + group + 1)]  # 다음 묶음과 끝점 하나를 같이 써서 끊김 없이
            mid = start + len(chunk) / 2
            life = sum(l for _, l in chunk) / len(chunk)
            c = QColor.fromHsvF((mid / n * 0.8) % 1.0, 0.9, 1.0) if kind == "rainbow" else QColor(color)
            c.setAlphaF(max(0.0, min(1.0, opacity * life)))
            pen = QPen(c, max(1.0, base * 1.2 * life))
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline([q for q, _ in chunk])
        head, life = pts[-1]
        c = QColor.fromHsvF(0.8 * (n - 1) / n % 1.0, 0.9, 1.0) if kind == "rainbow" else QColor(color)
        c.setAlphaF(max(0.0, min(1.0, opacity * life)))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        r = max(1.0, base * 1.2 * life) / 2
        p.drawEllipse(head, r, r)
    elif kind == "sparkle":
        step = max(1, len(pts) // SPARKLE_LIMIT)
        for i, (q, life) in enumerate(pts[::step][-SPARKLE_LIMIT:]):
            dx, dy = sparkle_offsets(i, size)
            c = sparkle_color(i, multicolor, color)
            c.setAlphaF(max(0.0, min(1.0, opacity * life)))
            width, extra = sparkle_stroke(i)
            p.setPen(QPen(c, width))
            arm = 2 + 3 * life + extra
            x, y = q.x() + dx * (1 - life), q.y() + dy * (1 - life)
            p.drawLine(QPointF(x - arm, y), QPointF(x + arm, y))
            p.drawLine(QPointF(x, y - arm), QPointF(x, y + arm))


SPARKLE_SATURATION = 0.85  # 0.38.1: 0.45 → 0.85(인게임에서 잘 안 보임 — 사용자 렌더 비교 후 선택)
SPARKLE_THIN, SPARKLE_BOLD, SPARKLE_BOLD_ARM = 1.5, 2.6, 0.8


def sparkle_color(index: int, multicolor: bool, color: str) -> QColor:
    """여러 색: 조각 번호마다 색상환을 돌며 채도 0.85. 고른 색이면 그 색 그대로."""
    return QColor.fromHsvF((index * 0.13) % 1.0, SPARKLE_SATURATION, 1.0) if multicolor else QColor(color)


def sparkle_stroke(index: int) -> tuple[float, float]:
    """0.38.1 굵기 섞기(사용자 선택 '섞기'): 조각 3개 중 1개만 굵게(2.6px, + 팔 +0.8px), 나머지 1.5px."""
    return (SPARKLE_BOLD, SPARKLE_BOLD_ARM) if index % 3 == 0 else (SPARKLE_THIN, 0.0)


def paint_particles(p: QPainter, particles, kind: str, color: str, opacity: float,
                    offset: QPointF = QPointF(0, 0), multicolor: bool = False) -> None:
    """0.37.0 조각 꼬리. sparkle: 위아래로 튀는 + 모양(깜빡임·나이에 따라 흐려지고 작아짐),
    fire: 둥근 불티(나이에 따라 흰→노랑→주황→빨강, 가산 혼합). 색 규칙: 안 고름 = 여러 색/기본 불꽃색, 고름 = 그 색."""
    from ..cursor_fx import fire_alpha, fire_color, fire_stops

    if not particles:
        return
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    ox, oy = offset.x(), offset.y()
    if kind == "sparkle":
        for q in particles:
            life = 1.0 - q.age
            twinkle = 0.55 + 0.45 * math.cos(q.age * 18.0 + q.index * 1.7)
            c = sparkle_color(q.index, multicolor, color)
            c.setAlphaF(max(0.0, min(1.0, opacity * life * twinkle)))
            width, extra = sparkle_stroke(q.index)
            p.setPen(QPen(c, width))
            arm = q.radius * (0.4 + 0.6 * life) + 1 + extra
            x, y = q.x - ox, q.y - oy
            p.drawLine(QPointF(x - arm, y), QPointF(x + arm, y))
            p.drawLine(QPointF(x, y - arm), QPointF(x, y + arm))
    elif kind == "fire":
        stops = fire_stops(None if multicolor else color)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        p.setPen(Qt.PenStyle.NoPen)
        for q in particles:
            r, g, b = fire_color(q.age, stops)
            c = QColor(r, g, b)
            c.setAlphaF(max(0.0, min(1.0, fire_alpha(q.age) * opacity)))
            p.setBrush(c)
            rad = q.radius * (1.0 - 0.6 * q.age)  # 나이에 따라 40%까지
            p.drawEllipse(QPointF(q.x - ox, q.y - oy), rad, rad)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
