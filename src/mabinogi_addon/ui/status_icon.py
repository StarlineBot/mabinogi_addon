"""버프·디버프 탭 상태 줄 아이콘(2026-10-27 사용자 결정 B안). 글자 기호(⏸·ℹ)는 Windows에서 이모지 글꼴로 바뀌어
파란 박스로 보여서, 글꼴과 무관하게 QPainter로 직접 그린 14px 모노톤 아이콘을 상태 색으로 칠한다.

영역 미지정 = 삼각형 ! · 추적 대기 = 모래시계 · 게임 비활성 = 원+일시정지 · 기준 버프 미검출 = 돋보기 · 추적 중 = 원+체크.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel

SIZE = 14
KINDS = ('region', 'waiting', 'inactive', 'anchor', 'ok')


def paint_icon(kind: str, color: str, size: int = SIZE, scale: float = 2.0) -> QPixmap:
    """kind 아이콘을 color로 그린 투명 배경 픽스맵(고해상도 화면용 scale배로 그려 devicePixelRatio 지정)."""
    pixmap = QPixmap(round(size * scale), round(size * scale))
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(scale)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    s = float(size)
    m = 1.5  # 테두리 여백
    if kind == 'region':  # 삼각형 + !
        path = QPainterPath(QPointF(s / 2, m))
        path.lineTo(s - m, s - m)
        path.lineTo(m, s - m)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(s / 2, s * 0.42), QPointF(s / 2, s * 0.64))
        p.drawPoint(QPointF(s / 2, s * 0.80))
    elif kind == 'waiting':  # 모래시계
        top, bottom = m, s - m
        p.drawLine(QPointF(s * 0.22, top), QPointF(s * 0.78, top))
        p.drawLine(QPointF(s * 0.22, bottom), QPointF(s * 0.78, bottom))
        path = QPainterPath(QPointF(s * 0.28, top))
        path.lineTo(s * 0.72, top)
        path.lineTo(s * 0.5, s / 2)
        path.lineTo(s * 0.72, bottom)
        path.lineTo(s * 0.28, bottom)
        path.lineTo(s * 0.5, s / 2)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == 'inactive':  # 원 + 일시정지
        p.drawEllipse(QRectF(m, m, s - 2 * m, s - 2 * m))
        p.drawLine(QPointF(s * 0.40, s * 0.33), QPointF(s * 0.40, s * 0.67))
        p.drawLine(QPointF(s * 0.60, s * 0.33), QPointF(s * 0.60, s * 0.67))
    elif kind == 'anchor':  # 돋보기
        p.drawEllipse(QRectF(m, m, s * 0.62, s * 0.62))
        p.drawLine(QPointF(s * 0.62, s * 0.62), QPointF(s - m, s - m))
    else:  # 'ok': 원 + 체크
        p.drawEllipse(QRectF(m, m, s - 2 * m, s - 2 * m))
        path = QPainterPath(QPointF(s * 0.30, s * 0.52))
        path.lineTo(s * 0.45, s * 0.66)
        path.lineTo(s * 0.71, s * 0.37)
        p.drawPath(path)
    p.end()
    return pixmap


class StatusIcon(QLabel):
    """상태 줄 앞 아이콘. 같은 종류·색이면 다시 그리지 않는다(메인 폴링이 0.7초마다 부름)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(SIZE, SIZE)
        self.kind = None
        self._key = None

    def set_kind(self, kind: str | None, color: str) -> None:
        self.kind = kind
        key = (kind, color)
        if key == self._key:
            return
        self._key = key
        if kind is None:
            self.clear()
            self.hide()
            return
        self.setPixmap(paint_icon(kind, color))
        self.show()


def status_row(label: QLabel) -> tuple[QHBoxLayout, StatusIcon]:
    """아이콘 + 기존 상태 문구 라벨을 한 줄 레이아웃으로 묶는다. 중간 위젯 없이 레이아웃만 끼워, 라벨이 탭의 직접 자식으로 남아
    문구 길이 변화(LayoutRequest)가 지금처럼 바로 탭에 전달되게 한다(제작자 잡담 바닥 배치 재판정)."""
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    icon = StatusIcon()
    # 첫 줄 글자 높이에 맞춰 세로 가운데(여러 줄로 접혀도 첫 줄 옆)
    icon.setFixedSize(SIZE, max(SIZE, label.fontMetrics().height()))
    icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon.hide()
    layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)  # 줄 높이가 남아도 글자는 아이콘과 같은 위에서
    layout.addWidget(label, 1)
    return layout, icon
