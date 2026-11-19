"""오버레이 격자 맞춤(스냅) 공용 유틸.

설정(general.gridSnap)이 켜져 있으면 모든 오버레이(버프·디버프·메모·미러)를 드래그로
옮길 때 좌표를 16px 격자에 맞춰 이동한다. 격자 선은 **드래그하는 동안에만** 전체 화면에
표시(클릭 통과)되고, 떼면 사라진다.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

_DEFAULT_SIZE = 32  # 격자 한 칸(px) 기본값. 설정에서 조절 가능.


def enabled() -> bool:
    from .. import config

    return config.load_general_flag("gridSnap", False)


def size() -> int:
    from .. import config

    return config.load_grid_size()


def _screen_center() -> tuple[int, int]:
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return 960, 540
    c = screen.geometry().center()
    return c.x(), c.y()


def snap(point: QPoint, grid_size: int | None = None) -> QPoint:
    """좌표를 **화면 정중앙 기준** 격자에 맞춰 반올림.

    0,0이 아니라 화면 중앙을 원점으로 삼아, 격자선(가이드)과 스냅이 항상 중앙을
    지나도록 일치시킨다 → 중앙 기준선에 맞춰 오버레이를 정렬하기 쉽다.
    """
    s = grid_size or _DEFAULT_SIZE
    cx, cy = _screen_center()
    return QPoint(
        cx + round((point.x() - cx) / s) * s,
        cy + round((point.y() - cy) / s) * s,
    )


class _GridGuide(QWidget):
    """드래그 중에만 뜨는 전체 화면 격자 선(표시 전용, 클릭 통과)."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        from . import overlay_capture
        overlay_capture.watch(self)  # 0.37.1: 뜰 때마다 판독 캡처에서 빼기(이 창에만 필터)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._size = _DEFAULT_SIZE
        self.owner = None
        # 11-05: 각 오버레이의 mouseRelease에서만 숨기다 보니 뗌 이벤트를 못 받으면(드래그 중 숨김·고정·포커스 이동 등)
        # 안내선이 한동안 남았다. 보이는 동안 100ms마다 스스로 확인해 정리한다(원인과 무관하게).
        self._watch = QTimer(self)
        self._watch.setInterval(WATCH_MS)
        self._watch.timeout.connect(self.check)

    def check(self) -> None:
        """마우스 버튼이 안 눌려 있거나, 끌던 오버레이가 사라졌거나 고정됐으면 숨긴다."""
        if not self.isVisible():
            self._watch.stop()
            return
        if QGuiApplication.mouseButtons() == Qt.MouseButton.NoButton or _owner_gone(self.owner):
            hide_guide()

    def hideEvent(self, event) -> None:
        self._watch.stop()
        super().hideEvent(event)
    def show_guide(self, grid_size: int) -> None:
        self._size = max(2, int(grid_size))
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        self.setGeometry(screen.geometry())
        self.show()
        self.raise_()
        self._watch.start()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        w, h = self.width(), self.height()
        s = max(2, self._size)
        cx, cy = w // 2, h // 2
        # 일반 격자선 — 중앙을 지나도록 위상을 맞춘다(중앙 대칭).
        painter.setPen(QPen(QColor(0, 209, 167, 70), 1))
        x = cx % s
        while x < w:
            painter.drawLine(x, 0, x, h)
            x += s
        y = cy % s
        while y < h:
            painter.drawLine(0, y, w, y)
            y += s
        # 중앙 기준선(십자) — 더 밝고 두껍게.
        painter.setPen(QPen(QColor(255, 213, 74, 180), 2))
        painter.drawLine(cx, 0, cx, h)
        painter.drawLine(0, cy, w, cy)
        painter.end()


_guide: _GridGuide | None = None
WATCH_MS = 100


def _owner_gone(owner) -> bool:
    if owner is None:
        return False
    from shiboken6 import isValid
    if not isValid(owner) or not owner.isVisible():
        return True
    return bool(getattr(owner, "_locked", False) or getattr(owner, "locked", False) is True)


class _OwnerFilter(QObject):
    """끌던 오버레이가 숨거나(Hide)·닫히면 바로 안내선을 숨긴다(오버레이마다 따로 처리하지 않게 — 공용)."""

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Hide, QEvent.Type.Close) and _alive() is not None and watched is _guide.owner:
            hide_guide()
        return False


_filter: _OwnerFilter | None = None


def _alive() -> _GridGuide | None:
    """안내선 창(Qt 객체가 지워졌으면 None — 다시 만든다)."""
    global _guide
    if _guide is not None:
        from shiboken6 import isValid
        if not isValid(_guide):
            _guide = None
    return _guide


def show_guide(owner=None) -> None:
    """owner = 지금 끄는 오버레이(숨김·닫힘·고정 때 안내선을 함께 정리)."""
    global _guide, _filter
    if _alive() is None:
        _guide = _GridGuide()
    if _filter is None:
        _filter = _OwnerFilter()
    if owner is not None and owner is not _guide.owner:
        owner.installEventFilter(_filter)
    _guide.owner = owner
    _guide.show_guide(size())


def hide_guide() -> None:
    if _alive() is not None:
        if _guide.owner is not None and _filter is not None:
            from shiboken6 import isValid
            if isValid(_guide.owner):
                _guide.owner.removeEventFilter(_filter)
        _guide.owner = None
        _guide.hide()


def guide_visible() -> bool:
    return _alive() is not None and _guide.isVisible()


def owner_locked(owner) -> None:
    """오버레이 고정(set_locked) 때 부른다 — 그 오버레이를 끄는 중이었으면 안내선을 바로 숨긴다."""
    if _alive() is not None and _guide.owner is owner:
        hide_guide()
