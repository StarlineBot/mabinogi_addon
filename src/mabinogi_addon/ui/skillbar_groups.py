"""단축바 탭 '묶음' 구역(0.49.0, 사용자 결정 11-14) — 커스텀 오버레이처럼 탭에서 12묶음을 관리.

- 묶음마다 ☑ 표시(chunks.<key>.show) · ☑ 잠금(locked) · 칸 4개(지금 단축바 아이콘, 누르면 숨김 ↔ 보임 = chunks.<key>.cells).
- 오버레이 우클릭 숨기기와 같은 값이라 서로 바로 맞춰진다(탭 → `toggle_cell`, 오버레이 → 탭 `refresh`).
- 오버레이에서 숨긴 칸은 잠금 상태면 완전 투명이라 클릭이 게임으로 지나간다 → 여기서 되살린다.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget  # noqa: F401

from .palette import color
from .skillbar_mirror import BLOCK_NAMES, CELLS, ROW_NAMES
from .widgets import checkbox, hint_label

CELL_PX = 30


class CellButton(QAbstractButton):
    """칸 하나: 아이콘(영역 지정 전이면 빈 칸). 숨긴 칸은 흐리게 + 사선."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(CELL_PX, CELL_PX)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pixmap: QPixmap | None = None
        self.hidden_cell = False
        self._tip()

    def sizeHint(self) -> QSize:
        return QSize(CELL_PX, CELL_PX)

    def set_state(self, pixmap: QPixmap | None, hidden: bool) -> None:
        changed = hidden != self.hidden_cell or (pixmap is not None) != (self.pixmap is not None) or pixmap is not self.pixmap
        self.pixmap, self.hidden_cell = pixmap, hidden
        if changed:
            self._tip()
            self.update()

    def _tip(self) -> None:
        self.setToolTip("숨긴 칸이에요. 누르면 다시 보여요." if self.hidden_cell else "누르면 이 칸을 숨겨요.")

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        r = QRect(0, 0, self.width() - 1, self.height() - 1)
        if self.pixmap is not None:
            p.setOpacity(0.3 if self.hidden_cell else 1.0)
            p.drawPixmap(r.adjusted(1, 1, 0, 0), self.pixmap)
            p.setOpacity(1.0)
        p.setPen(QPen(QColor(color("muted")), 1, Qt.PenStyle.SolidLine if self.pixmap is not None else Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)
        if self.hidden_cell:
            p.setPen(QPen(QColor(color("danger")), 2))
            p.drawLine(4, 4, self.width() - 5, self.height() - 5)
        p.end()


class SkillbarGroupsSection(QGroupBox):
    toggle_cell = Signal(str, int)  # (묶음 키, 칸)
    toggle_show = Signal(str, bool)
    toggle_lock = Signal(str, bool)

    def __init__(self, defs: dict, parent=None) -> None:
        super().__init__("묶음", parent)
        self._defs = defs
        self.rows: dict[str, tuple] = {}
        v = QVBoxLayout(self)
        v.addWidget(hint_label("묶음마다 보이기·위치 잠금, 칸을 누르면 숨김 ↔ 보임이에요. 오버레이에서 우클릭으로 숨긴 칸도 여기서 다시 켤 수 있어요."))
        columns = []
        for block in range(2):
            column = QWidget()
            col = QVBoxLayout(column)
            col.setContentsMargins(0, 0, 0, 0)
            col.addWidget(QLabel(f"{BLOCK_NAMES[block]} 블록"))
            grid = QGridLayout()
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(6)
            r = 0
            for key, g in defs.items():
                if g.block != block:
                    continue
                first = g.col * CELLS + 1
                name = QLabel(f"{ROW_NAMES[g.row]} {first}~{first + CELLS - 1}")
                show = checkbox("표시")
                show.toggled.connect(lambda on, k=key: self.toggle_show.emit(k, bool(on)))
                lock = checkbox("잠금")
                lock.toggled.connect(lambda on, k=key: self.toggle_lock.emit(k, bool(on)))
                cells = QWidget()
                ch = QHBoxLayout(cells)
                ch.setContentsMargins(0, 0, 0, 0)
                ch.setSpacing(3)
                buttons = []
                for i in range(CELLS):
                    b = CellButton()
                    b.clicked.connect(lambda _=False, k=key, i=i: self.toggle_cell.emit(k, i))
                    ch.addWidget(b)
                    buttons.append(b)
                grid.addWidget(name, r, 0)
                grid.addWidget(show, r, 1)
                grid.addWidget(lock, r, 2)
                grid.addWidget(cells, r, 3)
                self.rows[key] = (name, show, lock, buttons)
                r += 1
            col.addLayout(grid)
            col.addStretch(1)
            columns.append(column)
        # 넓으면 왼쪽 | 오른쪽 블록 두 열, 좁거나 글자가 크면 오른쪽 블록이 아래로(가로 넘침 없음)
        from .widgets import WrapRow
        v.addWidget(WrapRow(*columns, spacing=24))

    def refresh(self, chunks_cfg: dict, thumbs: dict) -> None:
        """설정(표시·잠금·칸)과 지금 아이콘을 목록에 반영(신호는 내보내지 않음)."""
        for key, (name, show, lock, buttons) in self.rows.items():
            c = chunks_cfg.get(key, {})
            for box, value in ((show, c.get("show", True)), (lock, c.get("locked", False))):
                if box.isChecked() != bool(value):
                    box.blockSignals(True)
                    box.setChecked(bool(value))
                    box.blockSignals(False)
            name.setStyleSheet("" if c.get("show", True) else f"color:{color('muted')};")
            cells = c.get("cells", [True] * CELLS)
            pms = thumbs.get(key) or [None] * CELLS
            for i, b in enumerate(buttons):
                b.set_state(pms[i] if i < len(pms) else None, not cells[i])
