"""영역 지정 오버레이 (기획서 5.2).

전체화면 반투명 위에서 드래그로 사각형을 그려 영역(실제 화면 픽셀)을 고른다.
ESC로 취소. 선택 완료 시 selected(x, y, w, h) 시그널.

커서 옆에 돋보기(확대경)를 띄워 현재 포인터 주변을 크게 보여준다 → 얇은 디버프 줄 등
픽셀 단위로 정밀하게 집을 수 있다. 확대경 원본은 '선택창을 띄우기 전' 화면 스냅샷.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
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
        self,
        save_path: Path | None = None,
        fixed_size: tuple[int, int] | None = None,
        window_hwnd: int | None = None,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._save_path = save_path
        # fixed_size가 있으면 '고정 크기 박스를 커서에 붙여 클릭 한 번으로 배치' 모드.
        self._fixed = fixed_size
        self._fixed_base = fixed_size  # 휠 배율 % 표시용 기준(처음 크기=100%)
        # window_hwnd가 있으면 그 창(게임) 내용을 스냅샷 위에 합성 → 작업표시줄 등에
        # 가린 부분도 돋보기에 게임 그대로 보인다(커스텀 오버레이 미러 영역 지정용).
        self._window_hwnd = window_hwnd
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
        self._dpr = 1.0  # 스냅샷 배율(물리픽셀=논리×dpr). start()에서 실제값으로 채움

    def start(self) -> None:
        self._origin = None
        self._rect = QRect()
        self._cursor = None
        # 오버레이를 덮기 전에 현재 화면을 캡처(돋보기 원본). 띄운 뒤 캡처하면 오버레이가 찍힌다.
        screen = QGuiApplication.primaryScreen()
        self._shot = screen.grabWindow(0) if screen else QPixmap()
        # 스냅샷을 '물리픽셀 그대로'로 다룬다: dpr을 1로 떼고 배율은 self._dpr에 보관.
        # 150% 등에서 논리좌표(rect/pos)에 self._dpr을 곱해 물리픽셀로 인덱싱해야
        # 돋보기·박스 미리보기가 엉뚱한 자리를 확대하지 않는다(안 그러면 '이상한 화면').
        if not self._shot.isNull():
            self._dpr = float(self._shot.devicePixelRatio() or 1.0)
            self._shot.setDevicePixelRatio(1.0)
            if self._window_hwnd:
                self._composite_window(self._window_hwnd)
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def _composite_window(self, hwnd: int) -> None:
        """게임 창 그림을 PrintWindow로 읽어 스냅샷(물리픽셀) 위에 덮는다.

        작업표시줄 등에 가린 부분도 게임 내용으로 보이게 한다. 캡처 실패나 거의
        검게 나오면(하드웨어 가속 게임) 아무것도 안 하고 화면 스냅샷을 그대로 둔다.
        """
        from ..system.window_capture import capture_window_bgra

        cap = capture_window_bgra(hwnd)
        if cap is None:
            return
        bgra, left, top, w, h = cap
        img = QImage(bgra, w, h, QImage.Format.Format_RGB32).copy()  # bytes 수명 분리
        if img.isNull() or self._mostly_black(img):
            return  # D3D 등으로 검게 나옴 → 화면 스냅샷 유지(폴백)
        # 창의 화면(물리) 좌표를 주 화면 스냅샷 기준으로 옮겨 그린다.
        ox = round(self._screen_geo.x() * self._dpr)
        oy = round(self._screen_geo.y() * self._dpr)
        painter = QPainter(self._shot)
        painter.drawImage(left - ox, top - oy, img)
        painter.end()

    @staticmethod
    def _mostly_black(img: QImage) -> bool:
        """샘플 픽셀이 거의 다 검으면 True(PrintWindow가 내용을 못 가져온 경우)."""
        w, h = img.width(), img.height()
        if w < 2 or h < 2:
            return True
        steps = 8
        lit = total = 0
        for i in range(1, steps):
            for j in range(1, steps):
                c = img.pixelColor(w * i // steps, h * j // steps)
                total += 1
                if c.red() + c.green() + c.blue() > 24:  # 거의 검정이 아님
                    lit += 1
        return total == 0 or lit <= total * 0.02  # 2% 이하만 밝으면 '검은 화면'

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
        # 5%씩(비율 유지) — 10%는 간격이 커 필요한 크기가 두 단계 사이에 걸려 딱 안 맞을
        # 수 있어 더 잘게. Shift와 함께 돌리면 더 크게(빠르게).
        base = 1.15 if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else 1.05
        step = base if event.angleDelta().y() > 0 else 1 / base
        # 최대 크기는 넉넉히 — 4K·고배율 화면에선 바가 크게 렌더돼 작은 캡(400)에 막혀
        # 바에 못 맞추던 문제 방지. (작은 화면은 줄이는 방향이라 영향 없음.)
        self._fixed = (
            max(12, min(600, round(w * step))),
            max(8, min(400, round(h * step))),
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
        dpr = self._dpr  # 스냅샷은 start()에서 이미 dpr=1로 떼어 뒀다(물리픽셀 그대로)
        crop = self._shot.copy(
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
        if self._fixed is None:
            # 드래그 선택 모드 안내(고정 박스 모드는 아래에서 별도 안내).
            self._draw_hint(
                painter, "드래그해서 영역을 지정하세요   ·   ESC: 취소"
            )
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
        """고정 박스가 잡는 영역을 '여백 포함'으로 크게 확대해 보여준다.

        박스만 딱 잘라 보여주면 박스가 바에 꽉 맞았는지(여백이 있는지) 알 수 없다. 그래서
        박스 주변까지 여유 있게 잘라 더 크게 확대하고, 그 안에 **박스 외곽선(민트)**을 함께
        그려, 바가 외곽선 안에 딱 맞는지(여백/잘림 없음) 눈으로 확인하게 한다.
        """
        dpr = self._dpr  # 논리 → 물리픽셀(150% 보정)
        # 박스 주변 여유(논리 px): 박스 변의 ~45%(최소 12)만큼 상하좌우로 더 보여준다.
        m = max(12, round(max(rect.width(), rect.height()) * 0.45))
        ew, eh = rect.width() + 2 * m, rect.height() + 2 * m
        # 확대 영역을 물리픽셀로 잘라 검정 캔버스에 붙인다(화면 밖이어도 안 깨지게).
        sx0, sy0 = round((rect.x() - m) * dpr), round((rect.y() - m) * dpr)
        cw, ch = round(ew * dpr), round(eh * dpr)
        canvas = QPixmap(max(1, cw), max(1, ch))
        canvas.fill(Qt.GlobalColor.black)
        sw, sh = self._shot.width(), self._shot.height()
        vx0, vy0 = max(0, sx0), max(0, sy0)
        vx1, vy1 = min(sw, sx0 + cw), min(sh, sy0 + ch)
        if vx1 > vx0 and vy1 > vy0:
            part = self._shot.copy(vx0, vy0, vx1 - vx0, vy1 - vy0)
            cp = QPainter(canvas)
            cp.drawPixmap(vx0 - sx0, vy0 - sy0, part)
            cp.end()
        # 더 크게: 패널 폭을 키우고(≈340) 그만큼 확대. 세로가 과하면 높이로 제한.
        panel_w, panel_h_max = 340, 260
        scale = min(panel_w / max(1, cw), panel_h_max / max(1, ch))
        zw, zh = max(1, round(cw * scale)), max(1, round(ch * scale))
        zoomed = canvas.scaled(
            zw, zh,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,  # Nearest → 픽셀 또렷
        )
        # 헤더가 이미지 '위'로 차지하는 높이. 2줄(조절 전)이면 한 줄 더 띄워 박스
        # 라벨("104×32")과 안 겹치게 한다.
        fm = painter.fontMetrics()
        lh = fm.height()
        show_tip = self._fixed is not None and self._fixed == self._fixed_base
        head_h = 24 + (lh if show_tip else 0)
        # 패널 배치(박스 아래, 화면 밖이면 위로). 헤더 높이만큼 박스에서 더 띄운다.
        px = max(8, min(rect.x(), self.width() - zw - 8))
        py = rect.bottom() + 12 + head_h
        if py + zh + 6 > self.height():
            py = rect.y() - zh - 18 - head_h
        py = max(8 + head_h, py)

        # 헤더: 1줄=제목+배율%, (아직 조절 전이면) 2줄=휠 안내. 헤더는 이미지 '위'라
        # 체력바를 안 가린다. 조절 시작하면(배율≠100%) 안내 줄이 사라져 1줄로 준다.
        painter.setOpacity(1.0)
        header_top = py - head_h
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 200))
        painter.drawRoundedRect(
            px - 6, header_top, zw + 12, (py + zh + 8) - header_top, 8, 8
        )
        zoom_txt = ""
        if self._fixed is not None and self._fixed_base and self._fixed_base[0]:
            zoom_txt = f"  ·  배율 {round(self._fixed[0] / self._fixed_base[0] * 100)}%"
        title = f"박스 미리보기(여백 포함)  {rect.width()}×{rect.height()}{zoom_txt}"
        painter.setPen(QColor(235, 238, 244))
        if show_tip:
            painter.drawText(px, py - 8 - lh, title)
            painter.setPen(QColor(93, 232, 193))
            painter.drawText(px, py - 8, "휠로 크기를 조절하세요 (Shift 빠르게)")
        else:
            painter.drawText(px, py - 8, title)
        painter.drawPixmap(px, py, zoomed)
        # 미리보기 안에 '실제 박스' 외곽선(민트) — 바가 이 선 안에 딱 맞는지 확인.
        bx = px + round(m * dpr * scale)
        by = py + round(m * dpr * scale)
        bw = round(rect.width() * dpr * scale)
        bh = round(rect.height() * dpr * scale)
        painter.setPen(QPen(QColor(0, 209, 167), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(bx, by, bw, bh)
        # 패널 바깥 테두리(옅게)
        painter.setPen(QPen(QColor(120, 130, 140), 1))
        painter.drawRect(px, py, zw, zh)

    def _draw_loupe(self, painter: QPainter, pos: QPoint) -> None:
        """커서 주변을 _ZOOM배로 확대해 커서 옆 박스에 그린다(중앙 십자선)."""
        src = max(4, _LOUPE // _ZOOM)
        half = src // 2
        # 커서(논리좌표)를 물리픽셀로 환산해 스냅샷(물리픽셀)을 인덱싱한다(150% 보정).
        cx, cy = round(pos.x() * self._dpr), round(pos.y() * self._dpr)
        sx0, sy0 = cx - half, cy - half
        # 화면 가장자리에서도 커서가 항상 '중앙'에 오도록, src×src 검정 캔버스에 화면 안
        # 유효 영역만 제자리에 붙인다(바로 copy하면 음수 좌표라 크롭이 밀려 깨진다).
        canvas = QPixmap(src, src)
        canvas.fill(Qt.GlobalColor.black)
        sw, sh = self._shot.width(), self._shot.height()
        vx0, vy0 = max(0, sx0), max(0, sy0)
        vx1, vy1 = min(sw, sx0 + src), min(sh, sy0 + src)
        if vx1 > vx0 and vy1 > vy0:
            part = self._shot.copy(vx0, vy0, vx1 - vx0, vy1 - vy0)
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
