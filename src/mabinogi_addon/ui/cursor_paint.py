"""마우스 커서 효과 그리기(오버레이 창과 탭 미리보기가 같이 쓴다). 선과 점으로만 그린다(명세 3절)."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from ..cursor_fx import SPARKLE_LIMIT, sparkle_offsets


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
               offset: QPointF = QPointF(0, 0)) -> None:
    """꼬리. points: cursor_fx.TailPoint(오래된 것부터), offset: 창 왼쪽 위의 화면 좌표(빼서 창 안 좌표로)."""
    if len(points) < 2 or kind == "none":
        return
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
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
        n = len(pts)
        for i in range(1, n):
            (a, _), (b, life) = pts[i - 1], pts[i]
            c = QColor.fromHsvF((i / n * 0.8) % 1.0, 0.9, 1.0) if kind == "rainbow" else QColor(color)
            c.setAlphaF(max(0.0, min(1.0, opacity * life)))
            pen = QPen(c, max(1.0, base * 1.2 * life))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(a, b)
    elif kind == "sparkle":
        step = max(1, len(pts) // SPARKLE_LIMIT)
        for i, (q, life) in enumerate(pts[::step][-SPARKLE_LIMIT:]):
            dx, dy = sparkle_offsets(i, size)
            c = QColor.fromHsvF((i * 0.13) % 1.0, 0.45, 1.0) if color.upper() == "#FFFFFF" else QColor(color)
            c.setAlphaF(max(0.0, min(1.0, opacity * life)))
            p.setPen(QPen(c, 1.5))
            arm = 2 + 3 * life
            x, y = q.x() + dx * (1 - life), q.y() + dy * (1 - life)
            p.drawLine(QPointF(x - arm, y), QPointF(x + arm, y))
            p.drawLine(QPointF(x, y - arm), QPointF(x, y + arm))
