"""영역 지정 오버레이 (기획서 5.2).

전체화면 반투명 위에서 드래그로 사각형을 그려 영역(실제 화면 픽셀)을 고른다.
ESC로 취소. 선택 완료 시 selected(x, y, w, h) 시그널.

커서 옆에 돋보기(확대경)를 띄워 현재 포인터 주변을 크게 보여준다 → 얇은 디버프 줄 등
픽셀 단위로 정밀하게 집을 수 있다. 확대경 원본은 '선택창을 띄우기 전' 화면 스냅샷.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

_LOUPE = 150  # 돋보기 박스 변(px)
_ZOOM = 6  # 확대 배율
_OFFSET = 28  # 커서에서 돋보기까지 거리


class RegionSelector(QWidget):
    """전체화면 드래그로 영역을 고른다(돋보기 포함).

    기본은 '좌표만' 돌려주는 영역 지정(selected). save_path를 주면 '크롭 모드'가 되어
    고른 영역을 스냅샷에서 잘라 PNG로 저장하고 captured(저장 성공 여부)를 방출한다 →
    그림판 없이 상태창에서 바로 매칭 아이콘을 집을 때 쓴다.
    """

    selected = Signal(int, int, int, int)  # 화면 픽셀 x, y, w, h
    cancelled = Signal()
    captured = Signal(bool)  # 크롭 모드: 저장 성공=True, 취소/너무 작음=False

    def __init__(
        self, save_path: Path | None = None, fixed_size: tuple[int, int] | None = None
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._save_path = save_path
        # fixed_size가 있으면 '고정 크기 박스를 커서에 붙여 클릭 한 번으로 배치' 모드.
        self._fixed = fixed_size
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)  # 버튼 안 눌러도 이동 이벤트 받기(돋보기용)
        # 주 화면 전체 덮기(위젯 로컬 좌표 = 화면 좌표 + screen.topLeft())
        self._screen_geo = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(self._screen_geo)

        self._origin: QPoint | None = None
        self._rect = QRect()
        self._cursor: QPoint | None = None
        self._shot = QPixmap()  # 선택창 띄우기 전 화면 스냅샷(돋보기 원본)

    def start(self) -> None:
        self._origin = None
        self._rect = QRect()
        self._cursor = None
        # 오버레이를 덮기 전에 현재 화면을 캡처(돋보기 원본). 띄운 뒤 캡처하면 오버레이가 찍힌다.
        screen = QGuiApplication.primaryScreen()
        self._shot = screen.grabWindow(0) if screen else QPixmap()
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._fixed is not None:
            # 고정 크기 모드: 클릭 지점에 중심을 둔 박스를 확정.
            rect = self._fixed_rect(event.position().toPoint())
            self.close()
            self.selected.emit(
                self._screen_geo.x() + rect.x(),
                self._screen_geo.y() + rect.y(),
                rect.width(),
                rect.height(),
            )
            return
        self._origin = event.position().toPoint()
        self._rect = QRect(self._origin, self._origin)
        self.update()

    def _fixed_rect(self, center: QPoint) -> QRect:
        w, h = self._fixed
        return QRect(center.x() - w // 2, center.y() - h // 2, w, h)

    def wheelEvent(self, event) -> None:
        # 고정 박스 모드: 마우스 휠로 박스 크기를 조절(숫자에 딱 맞추기). 비율 유지.
        if self._fixed is None:
            return
        w, h = self._fixed
        step = 1.1 if event.angleDelta().y() > 0 else 1 / 1.1
        self._fixed = (
            max(12, min(400, round(w * step))),
            max(8, min(300, round(h * step))),
        )
        if self._cursor is not None:
            self._rect = self._fixed_rect(self._cursor)
        self.update()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        self._cursor = event.position().toPoint()
        if self._fixed is not None:
            self._rect = self._fixed_rect(self._cursor)  # 커서 따라 박스 이동
        elif self._origin is not None:
            self._rect = QRect(self._origin, self._cursor).normalized()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._origin is None:
            return
        rect = self._rect
        self.close()
        big_enough = rect.width() >= 4 and rect.height() >= 4
        if self._save_path is not None:
            # 크롭 모드: 좌표가 아니라 잘라낸 이미지를 저장.
            self.captured.emit(big_enough and self._save_crop(rect))
            return
        if big_enough:
            self.selected.emit(
                self._screen_geo.x() + rect.x(),
                self._screen_geo.y() + rect.y(),
                rect.width(),
                rect.height(),
            )
        else:
            self.cancelled.emit()

    def _save_crop(self, rect: QRect) -> bool:
        """스냅샷에서 고른 영역을 물리 픽셀 기준으로 잘라 PNG로 저장."""
        if self._shot.isNull() or self._save_path is None:
            return False
        dpr = self._shot.devicePixelRatio()  # HiDPI(배율>100%)에서도 실제 픽셀로
        shot = self._shot
        shot.setDevicePixelRatio(1.0)
        crop = shot.copy(
            round(rect.x() * dpr),
            round(rect.y() * dpr),
            round(rect.width() * dpr),
            round(rect.height() * dpr),
        )
        if crop.isNull() or crop.width() < 2 or crop.height() < 2:
            return False
        return crop.save(str(self._save_path), "PNG")

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self.cancelled.emit()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))  # 전체 어둡게
        if not self._rect.isNull():
            if self._fixed is not None:
                # 고정 박스: 완전 투명(Clear)으로 비우면 레이어드 창 per-pixel 히트테스트
                # 때문에 그 위 클릭이 창을 '통과'해 배치가 안 된다(커서가 늘 박스 안이라
                # 모든 클릭이 통과). 옅은 틴트(alpha>0)를 깔아 클릭을 받게 한다.
                painter.fillRect(self._rect, QColor(0, 209, 167, 36))
            else:
                # 드래그 선택: 영역을 비워 원래 화면이 보이게(드래그 중 마우스 grab 유지라
                # 통과 문제가 없다).
                painter.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_Clear
                )
                painter.fillRect(self._rect, Qt.GlobalColor.transparent)
                painter.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_SourceOver
                )
            painter.setPen(QPen(QColor(0, 209, 167), 2))
            painter.drawRect(self._rect)
            label = f"{self._rect.width()} × {self._rect.height()}"
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(self._rect.adjusted(4, 4, 0, 0), 0, label)
        if self._fixed is not None:
            # 고정 박스 모드: 조작 안내 + '박스가 실제로 잡는 영역' 미리보기(커서 돋보기 X).
            self._draw_hint(
                painter, "마우스 휠: 박스 크기 조절   ·   클릭: 배치   ·   ESC: 취소"
            )
            if not self._rect.isNull() and not self._shot.isNull():
                self._draw_box_preview(painter, self._rect)
        elif self._cursor is not None and not self._shot.isNull():
            self._draw_loupe(painter, self._cursor)

    def _draw_hint(self, painter: QPainter, text: str) -> None:
        """화면 상단 중앙에 조작 안내 알약(pill)을 그린다."""
        painter.setOpacity(1.0)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(text)
        pad = 14
        w = tw + pad * 2
        h = fm.height() + 12
        x = (self.width() - w) // 2
        y = 24
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.drawRoundedRect(x, y, w, h, h // 2, h // 2)
        painter.setPen(QColor(235, 238, 244))
        painter.drawText(
            QRect(x, y, w, h),
            Qt.AlignmentFlag.AlignCenter,
            text,
        )

    def _draw_box_preview(self, painter: QPainter, rect: QRect) -> None:
        """고정 박스가 실제로 캡처할 영역을 확대해 보여준다(지정이 숫자에 맞는지 확인)."""
        crop = self._shot.copy(rect)
        crop.setDevicePixelRatio(1.0)
        pw = 180
        ph = max(1, round(pw * rect.height() / max(1, rect.width())))
        zoomed = crop.scaled(
            pw, ph,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        # 박스 아래에 패널 배치, 화면 밖이면 위로/안쪽으로 접기
        px = rect.x()
        py = rect.bottom() + 14
        if py + ph + 6 > self.height():
            py = rect.y() - ph - 24
        px = max(8, min(px, self.width() - pw - 8))
        py = max(24, py)

        painter.setOpacity(1.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 190))
        painter.drawRoundedRect(px - 6, py - 22, pw + 12, ph + 30, 8, 8)
        painter.setPen(QColor(235, 238, 244))
        painter.drawText(px, py - 7, f"박스 미리보기  {rect.width()}×{rect.height()}")
        painter.drawPixmap(px, py, zoomed)
        painter.setPen(QPen(QColor(0, 209, 167), 2))
        painter.drawRect(px, py, zoomed.width(), zoomed.height())

    def _draw_loupe(self, painter: QPainter, pos: QPoint) -> None:
        """커서 주변을 _ZOOM배로 확대해 커서 옆 박스에 그린다(중앙 십자선)."""
        src = max(4, _LOUPE // _ZOOM)
        half = src // 2
        sx0, sy0 = pos.x() - half, pos.y() - half
        # 화면 가장자리에서도 커서가 항상 '중앙'에 오도록, src×src 검정 캔버스에 화면 안
        # 유효 영역만 제자리에 붙인다(바로 copy하면 음수 좌표라 크롭이 밀려 깨진다).
        canvas = QPixmap(src, src)
        canvas.fill(Qt.GlobalColor.black)
        sw, sh = self._shot.width(), self._shot.height()
        vx0, vy0 = max(0, sx0), max(0, sy0)
        vx1, vy1 = min(sw, sx0 + src), min(sh, sy0 + src)
        if vx1 > vx0 and vy1 > vy0:
            part = self._shot.copy(vx0, vy0, vx1 - vx0, vy1 - vy0)
            part.setDevicePixelRatio(1.0)
            cp = QPainter(canvas)
            cp.drawPixmap(vx0 - sx0, vy0 - sy0, part)
            cp.end()
        zoomed = canvas.scaled(
            _LOUPE, _LOUPE,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,  # Nearest → 픽셀 또렷
        )
        # 돋보기 위치: 커서 우하단, 화면 밖이면 반대쪽으로 뒤집기
        lx = pos.x() + _OFFSET
        ly = pos.y() + _OFFSET
        if lx + _LOUPE > self.width():
            lx = pos.x() - _OFFSET - _LOUPE
        if ly + _LOUPE > self.height():
            ly = pos.y() - _OFFSET - _LOUPE

        painter.setOpacity(1.0)
        painter.drawPixmap(lx, ly, zoomed)
        painter.setPen(QPen(QColor(0, 209, 167), 2))
        painter.drawRect(lx, ly, _LOUPE, _LOUPE)
        # 중앙 십자선(현재 포인터 지점)
        cx, cy = lx + _LOUPE // 2, ly + _LOUPE // 2
        painter.setPen(QPen(QColor(255, 60, 60), 1))
        painter.drawLine(cx - 10, cy, cx + 10, cy)
        painter.drawLine(cx, cy - 10, cx, cy + 10)
        # 화면 좌표 표시
        sx = self._screen_geo.x() + pos.x()
        sy = self._screen_geo.y() + pos.y()
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(lx + 4, ly + _LOUPE - 6, f"{sx}, {sy}")
