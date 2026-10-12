"""미러 오버레이 창 (커스텀 오버레이 / 기획서 3.6).

화면의 한 영역(소스)을 복제해 띄우는 투명·항상위 창. 공유 캡처가 매 틱 프레임을
넘겨주면 그걸 그린다. 해제 상태에서 드래그 이동, 고정 상태에서 클릭 통과(표시 전용).

읽기 전용 원칙 준수: 화면을 읽어 그리기만 하며 입력을 만들지 않는다.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

_log = logging.getLogger("mabinogi_addon.mirror")

_SCALE_MIN = 0.25
_SCALE_MAX = 4.0
_SCALE_STEP = 0.1


def _clamp_scale(s: float) -> float:
    return max(_SCALE_MIN, min(_SCALE_MAX, round(s, 2)))


class MirrorOverlay(QWidget):
    moved = Signal()  # 드래그로 위치 변경 → 저장

    def __init__(self, source: dict, thumbnail_mode: bool = False) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        # DWM 썸네일 모드: 컴포지터가 창 표면에 소스를 직접 합성하므로 창은 불투명이어야
        # 한다. per-pixel 투명(WA_TranslucentBackground)이면 레이어드 창이 돼 썸네일이
        # 안 보인다. mss 모드에서만 투명 배경을 쓴다.
        self._thumb_mode = thumbnail_mode
        if not thumbnail_mode:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # source: {x,y,w,h, name, posX?, posY?, locked?, scale?}
        self.source = dict(source)
        self._pix: QPixmap | None = None
        self._locked = False
        self._drag_offset = None
        self._thumb = None  # DWM 썸네일 핸들(썸네일 모드)
        self._src_rel: tuple[int, int, int, int] | None = None  # 게임창 상대 소스 영역

        self._base_w = max(1, int(source["w"]))
        self._base_h = max(1, int(source["h"]))
        self._scale = _clamp_scale(float(source.get("scale", 1.0)))
        self._apply_size()
        self.move(int(source.get("posX", source["x"])), int(source.get("posY", source["y"])))

    def _apply_size(self) -> None:
        self.resize(
            max(1, round(self._base_w * self._scale)),
            max(1, round(self._base_h * self._scale)),
        )
        self.refresh_thumbnail()  # 크기 변경 시 썸네일 목적지도 갱신(썸네일 모드만)

    @property
    def name(self) -> str:
        return str(self.source.get("name", ""))

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def dragging(self) -> bool:
        """드래그 이동 중인지. 매니저가 이때 캡처를 쉬어 드래그를 부드럽게 한다."""
        return self._drag_offset is not None

    def set_frame(self, image: QImage) -> None:
        self._pix = QPixmap.fromImage(image)
        self.update()

    # ---- DWM 썸네일 모드(CPU ~0% 미러) ----
    def attach_thumbnail(self, src_hwnd: int) -> bool:
        """게임 창(src_hwnd)의 소스 영역을 이 창에 실시간 미러. 성공 True.

        창이 떠 있어야 winId가 유효하다(매니저가 show 후 호출). 소스 영역을 게임 창
        '현재 위치 기준 상대 좌표'로 한 번 환산해 저장 → 게임 창이 움직여도 같은
        인게임 요소를 따라간다.
        """
        from ..system import dwm_thumbnail

        wr = dwm_thumbnail.window_rect(src_hwnd)
        if wr is None:
            return False
        wl, wt, _, _ = wr
        sx, sy = int(self.source["x"]), int(self.source["y"])
        sw, sh = int(self.source["w"]), int(self.source["h"])
        self._src_rel = (sx - wl, sy - wt, sx - wl + sw, sy - wt + sh)
        thumb = dwm_thumbnail.Thumbnail()
        if not thumb.register(int(self.winId()), int(src_hwnd)):
            _log.warning("DWM 썸네일 연결 실패: 게임창=%s 소스상대=%s", src_hwnd, self._src_rel)
            return False
        self._thumb = thumb
        updated = self.refresh_thumbnail()
        # 진단: 게임창 크기 vs 화면 크기(= 화면을 꽉 채우는 '테두리 없는 전체 창'이면
        # OS가 independent flip로 전환돼 DWM 썸네일이 검정/청록으로만 나올 수 있다).
        # update 결과(성공/실패)까지 남겨, '등록은 됐는데 안 그려지는' 경우를 식별한다.
        ww, wh = wr[2] - wr[0], wr[3] - wr[1]
        try:
            from PySide6.QtGui import QGuiApplication

            scr = QGuiApplication.primaryScreen()
            sg = scr.geometry() if scr else None
            screen = (sg.width(), sg.height()) if sg is not None else None
        except Exception:  # noqa: BLE001
            screen = None
        fullscreen_like = (
            screen is not None and ww >= screen[0] - 2 and wh >= screen[1] - 2
        )
        _log.info(
            "DWM 썸네일 연결: 게임창=%s rect=%s 창크기=%dx%d 화면=%s 전체창추정=%s "
            "소스상대=%s update성공=%s",
            src_hwnd, wr, ww, wh, screen, fullscreen_like, self._src_rel, updated,
        )
        return True

    def refresh_thumbnail(self) -> bool:
        """현재 크기·고정상태에 맞춰 썸네일 사각형 갱신(저비용: 비트맵 복사 없음).
        update 성공 여부를 돌려준다(진단용)."""
        if self._thumb is None or self._src_rel is None:
            return False
        inset = 0 if self._locked else 2  # 해제 땐 이동 테두리 보이게 살짝 안쪽
        w, h = self.width(), self.height()
        dest = (inset, inset, max(1, w - 2 * inset), max(1, h - 2 * inset))
        return self._thumb.update(self._src_rel, dest)

    def detach_thumbnail(self) -> None:
        if self._thumb is not None:
            self._thumb.unregister()
            self._thumb = None

    @property
    def thumbnail_active(self) -> bool:
        return self._thumb is not None

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.setCursor(
            Qt.CursorShape.ArrowCursor if locked else Qt.CursorShape.SizeAllCursor
        )
        # 다른 오버레이와 동일: Qt 레벨 마우스 투과도 함께 토글(해제=받음, 고정=통과).
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, locked)
        from ..system.clickthrough import set_click_through

        set_click_through(self, locked)  # Windows 클릭 통과
        self.refresh_thumbnail()  # 고정/해제에 따라 테두리 inset 반영
        self.update()

    def to_dict(self) -> dict:
        """프리셋/복원용 직렬화(소스 영역 + 띄운 위치 + 고정 상태)."""
        return {
            "x": int(self.source["x"]),
            "y": int(self.source["y"]),
            "w": int(self.source["w"]),
            "h": int(self.source["h"]),
            "posX": int(self.x()),
            "posY": int(self.y()),
            "locked": bool(self._locked),
            "scale": round(self._scale, 2),
            "name": self.name,
        }

    # ---- 배율(해제 상태에서 휠=크기조절, 더블클릭=100%) ----
    def wheelEvent(self, event) -> None:
        if self._locked:
            return
        step = _SCALE_STEP if event.angleDelta().y() > 0 else -_SCALE_STEP
        new = _clamp_scale(self._scale + step)
        if new != self._scale:
            self._scale = new
            self._apply_size()
            self.moved.emit()  # 크기 변경도 저장
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if not self._locked:
            self._scale = 1.0
            self._apply_size()
            self.moved.emit()
            event.accept()

    # ---- 드래그 이동(해제 상태에서만) ----
    def mousePressEvent(self, event) -> None:
        if not self._locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            from . import grid

            self._snap = grid.enabled()
            self._grid_size = grid.size() if self._snap else None
            if self._snap:
                grid.show_guide()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._locked and self._drag_offset is not None:
            target = event.globalPosition().toPoint() - self._drag_offset
            if getattr(self, "_snap", False):
                from . import grid

                target = grid.snap(target, getattr(self, "_grid_size", None))
            self.move(target)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            from . import grid

            grid.hide_guide()
            self.moved.emit()

    def closeEvent(self, event) -> None:
        self.detach_thumbnail()
        super().closeEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        if self._thumb_mode:
            # 썸네일 모드: DWM이 창 표면에 소스를 직접 합성한다. 해제 땐 inset(2px)만큼
            # 바깥이 드러나므로 배경을 강조색으로 칠해 이동 테두리로 보이게 한다.
            # 고정 땐 썸네일이 창을 꽉 채워 배경색은 가려진다.
            painter.fillRect(
                self.rect(),
                QColor(0, 209, 167) if not self._locked else QColor(0, 0, 0),
            )
            painter.end()
            return
        if self._pix is not None:
            painter.drawPixmap(self.rect(), self._pix)
        else:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        if not self._locked:
            # 해제 상태: 이동 가능 표시 테두리
            painter.setPen(QPen(QColor(0, 209, 167), 2))
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()
