"""메모 오버레이 (아이디어: 게임 위 상주 메모장).

흰 글씨·항상 위·포커스 안 뺏음. 마비노기가 포그라운드일 때만 보인다.
버프/디버프 오버레이와 같은 고정 규칙:
- 해제: 반투명 검은 배경 + 상단 드래그 핸들 → 위치 이동, 본문 클릭해 입력 가능.
- 고정: 배경 투명 + 클릭 통과(표시 전용) — 흰 글씨만 남고 게임 클릭이 통과.

위치는 드래그로 옮기거나 '메모 영역 지정'으로 정한다(크기는 영역 지정으로).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget

_EDIT_STYLE = """
QTextEdit {
    background: transparent;
    color: white;
    border: none;
    selection-background-color: rgba(0,209,167,120);
}
"""
_BAR_STYLE = "background: rgba(0,0,0,150); color:#cfd3da; padding:2px 6px;"
_BAR_H = 22  # 상단 드래그 핸들 높이(항상 이만큼 자리 확보 → 고정해도 글자 위치 그대로)


class _DragBar(QLabel):
    """해제 상태에서 보이는 상단 드래그 핸들. 누르고 끌면 오버레이가 따라 이동."""

    def __init__(self, overlay: "MemoOverlay") -> None:
        super().__init__("⠿  드래그해서 이동 · 고정하면 숨김")
        self._overlay = overlay
        self._offset = None
        self.setStyleSheet(_BAR_STYLE)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._offset = (
                event.globalPosition().toPoint()
                - self._overlay.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._offset is not None:
            self._overlay.move(event.globalPosition().toPoint() - self._offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._offset is not None:
            self._offset = None
            self._overlay.moved.emit()


class MemoOverlay(QWidget):
    moved = Signal()  # 드래그로 위치가 바뀜 → main이 저장

    def __init__(self, font_size: int = 16) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._locked = False
        # 본문은 상단 핸들 높이만큼 항상 띄워 배치(핸들 숨겨도 글자 위치 고정).
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, _BAR_H, 0, 0)
        layout.setSpacing(0)
        self._edit = QTextEdit()
        self._edit.setStyleSheet(_EDIT_STYLE)
        self._edit.setFrameShape(QTextEdit.Shape.NoFrame)
        self._edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._edit.setPlaceholderText("메모 (해제 상태에서 클릭해 입력)")
        layout.addWidget(self._edit, 1)
        # 드래그 핸들은 레이아웃 밖 상단에 떠 있게(숨겨도 레이아웃이 안 바뀜).
        self._bar = _DragBar(self)
        self._bar.raise_()
        self.set_font_size(font_size)

    def resizeEvent(self, _event) -> None:  # noqa: N802
        self._bar.setGeometry(0, 0, self.width(), _BAR_H)

    # ---- 내용/글꼴 ----
    def text(self) -> str:
        return self._edit.toPlainText()

    def set_text(self, text: str) -> None:
        self._edit.setPlainText(text)

    def set_font_size(self, px: int) -> None:
        font = QFont()
        font.setPixelSize(max(8, int(px)))
        self._edit.setFont(font)

    @property
    def locked(self) -> bool:
        return self._locked

    # ---- 고정(클릭 통과) ----
    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self._bar.setVisible(not locked)  # 해제 때만 드래그 핸들 노출
        self._edit.setReadOnly(locked)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, locked)
        self._edit.setFocusPolicy(
            Qt.FocusPolicy.NoFocus if locked else Qt.FocusPolicy.StrongFocus
        )
        from ..system.clickthrough import set_click_through

        set_click_through(self, locked)
        self.update()

    # ---- 배경(해제 상태에서만 반투명 검게) ----
    def paintEvent(self, _event) -> None:  # noqa: N802
        if self._locked:
            return  # 고정: 완전 투명(흰 글씨만)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))
        painter.setPen(QColor(0, 209, 167))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()
