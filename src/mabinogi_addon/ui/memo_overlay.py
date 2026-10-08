"""메모 오버레이 (게임 위 상주 메모장).

흰 글씨·항상 위·포커스 안 뺏음. 마비노기가 포그라운드일 때만 보인다.
버프/디버프 오버레이와 같은 고정 규칙:
- 해제: 반투명 검은 박스(테두리·헤더 표시). 박스의 테두리/헤더를 끌면 박스 전체가
  커서를 따라 이동하고, 안쪽 본문을 클릭하면 입력. (별도 창/핸들 없음)
- 고정: 배경 투명 + 클릭 통과(표시 전용) — 흰 글씨만 남고 게임 클릭이 통과.

본문은 항상 헤더·테두리만큼 안쪽에 있어, 고정/해제해도 글자 위치가 그대로다.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

_EDIT_STYLE = """
QTextEdit {
    background: transparent;
    color: white;
    border: none;
    selection-background-color: rgba(0,209,167,120);
}
"""
_HEADER_H = 20  # 상단 헤더(이동 안내) 높이
_BORDER = 8  # 본문 둘레 여백(= 드래그 가능한 테두리)


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
        self._drag_offset = None

        layout = QVBoxLayout(self)
        # 본문은 테두리·헤더만큼 안쪽에(둘레는 드래그 영역, 고정해도 글자 위치 유지).
        layout.setContentsMargins(_BORDER, _HEADER_H, _BORDER, _BORDER)
        self._edit = QTextEdit()
        self._edit.setStyleSheet(_EDIT_STYLE)
        self._edit.setFrameShape(QTextEdit.Shape.NoFrame)
        self._edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._edit.setReadOnly(True)  # 표시 전용 — 입력은 '메모' 탭에서
        self._edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._edit.setPlaceholderText("메모는 '메모' 탭에서 입력하세요")
        # 마크다운 표/구분선이 흰 글씨 위에서도 보이게 기본 스타일 지정.
        self._edit.document().setDefaultStyleSheet(
            "table { border-collapse: collapse; }"
            "th, td { border: 1px solid rgba(255,255,255,0.55); padding: 2px 8px; }"
            "th { background: rgba(0,209,167,0.25); }"
            "h1,h2,h3 { color: #7CF0D6; }"
            "a { color: #7CF0D6; }"
        )
        self._markdown = ""
        layout.addWidget(self._edit)
        self.set_font_size(font_size)

    # ---- 내용/글꼴 ----
    def text(self) -> str:
        return self._markdown

    def set_markdown(self, md: str) -> None:
        self._markdown = md or ""
        self._edit.setMarkdown(self._markdown)
        self.autosize()

    # 하위호환: 기존 호출부가 set_text를 쓰면 마크다운으로 렌더.
    def set_text(self, text: str) -> None:
        self.set_markdown(text)

    def set_font_size(self, px: int) -> None:
        font = QFont()
        font.setPixelSize(max(8, int(px)))
        self._edit.setFont(font)
        self.autosize()

    def autosize(self) -> None:
        """드래그로 정한 '너비'는 유지하고, 높이는 내용에 맞춰 자동으로 늘린다
        (화면 아래 끝까지). → 박스보다 내용이 길어 잘리는 괴리를 없앤다."""
        from PySide6.QtGui import QGuiApplication

        doc = self._edit.document()
        inner_w = max(60, self.width() - _BORDER * 2)
        doc.setTextWidth(inner_w)
        h = int(doc.size().height()) + _HEADER_H + _BORDER * 2 + 6
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            max_h = max(60, screen.availableGeometry().bottom() - self.y() - 4)
            h = min(h, max_h)
        self.resize(self.width(), max(48, h))

    @property
    def locked(self) -> bool:
        return self._locked

    # ---- 고정(클릭 통과) ----
    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        # 본문은 항상 표시 전용(입력은 메모 탭). 고정은 클릭 통과/커서만 바꾼다.
        self.setCursor(
            Qt.CursorShape.ArrowCursor if locked else Qt.CursorShape.SizeAllCursor
        )
        from ..system.clickthrough import set_click_through

        set_click_through(self, locked)  # 고정 시 Windows에서 클릭 통과
        self.update()

    # ---- 드래그 이동(테두리·헤더에서 시작) ----
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

    # ---- 배경/헤더(해제 상태에서만) ----
    def paintEvent(self, _event) -> None:
        if self._locked:
            return  # 고정: 완전 투명(흰 글씨만)
        painter = QPainter(self)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(rect, QColor(0, 0, 0, 120))
        painter.setPen(QColor(0, 209, 167))
        painter.drawRect(rect)
        # 상단 헤더: 이동 안내
        painter.setPen(QColor(150, 200, 190))
        font = QFont()
        font.setPixelSize(11)
        painter.setFont(font)
        painter.drawText(
            QRect(_BORDER, 0, self.width() - _BORDER, _HEADER_H),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "⠿ 끌어서 이동 · 고정하면 숨김",
        )
        painter.end()
