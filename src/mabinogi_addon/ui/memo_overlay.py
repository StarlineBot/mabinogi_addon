"""메모 오버레이 (아이디어: 게임 위 상주 메모장).

배경 투명·흰 글씨·항상 위·포커스 안 뺏음. 마비노기가 포그라운드일 때만 보인다.
위치·크기는 '메모 영역 지정'으로 정하고(텍스트 입력과 드래그 충돌 방지),
고정(lock) 토글로 버프/디버프 오버레이와 같은 규칙을 쓴다:
- 해제: 입력 가능(클릭해서 타이핑).
- 고정: 클릭 통과(표시 전용) — 게임 클릭이 그대로 통과.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

_STYLE = """
QTextEdit {
    background: transparent;
    color: white;
    border: none;
    selection-background-color: rgba(0,209,167,120);
}
"""


class MemoOverlay(QWidget):
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self._edit = QTextEdit()
        self._edit.setStyleSheet(_STYLE)
        self._edit.setFrameShape(QTextEdit.Shape.NoFrame)
        self._edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._edit.setPlaceholderText("메모 (해제 상태에서 클릭해 입력)")
        layout.addWidget(self._edit)
        self.set_font_size(font_size)

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
        self._edit.setReadOnly(locked)
        # 고정: 클릭 통과(표시만) / 해제: 입력 가능
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, locked)
        self._edit.setFocusPolicy(
            Qt.FocusPolicy.NoFocus if locked else Qt.FocusPolicy.StrongFocus
        )
        from ..system.clickthrough import set_click_through

        set_click_through(self, locked)
