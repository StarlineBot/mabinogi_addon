"""디버프 탭 (기획서 5.1 하단 주석).

버프 탭과 구조는 같지만 폼이 단순하다: 이름, 매칭 아이콘(영역에서 가져오기),
보여줄 아이콘만. 지속시간·알림·앵커 없음. 목록은 debuff 카탈로그로 채운다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..catalog import BuffDef, load_debuff_catalog
from .buff_tab import _pixmap
from .widgets import hint_label, icon_slot, section_label


class DebuffTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._catalog: list[BuffDef] = load_debuff_catalog()

        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(14)
        outer.addWidget(self._build_list_panel(), 1)
        outer.addWidget(self._build_form_panel(), 1)

        if self._catalog:
            self.debuff_list.setCurrentRow(0)

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)

        v.addWidget(QPushButton("디버프 줄 영역 지정"))
        v.addWidget(hint_label("영역 미지정 — 버튼으로 디버프 줄 영역을 지정하세요"))

        self.debuff_list = QListWidget()
        self.debuff_list.setIconSize(QSize(28, 28))
        for debuff in self._catalog:
            item = QListWidgetItem(debuff.name)
            pm = _pixmap(debuff.match_icon, 28)
            if pm is not None:
                item.setIcon(QIcon(pm))
            self.debuff_list.addItem(item)
        self.debuff_list.currentRowChanged.connect(self._on_select)
        v.addWidget(self.debuff_list, 1)

        order = QHBoxLayout()
        for text, tip in (
            ("＋", "맨 끝에 추가"),
            ("－", "삭제"),
            ("▲", "위로"),
            ("▼", "아래로"),
        ):
            btn = QPushButton(text)
            btn.setFixedWidth(46)
            btn.setToolTip(tip)
            order.addWidget(btn)
        order.addStretch(1)
        v.addLayout(order)
        return panel

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        v.addWidget(section_label("이름"))
        self.name_edit = QLineEdit()
        v.addWidget(self.name_edit)

        v.addWidget(section_label("매칭 아이콘"))
        match_row = QHBoxLayout()
        self.match_slot = icon_slot()
        match_row.addWidget(self.match_slot)
        match_row.addWidget(QPushButton("영역에서 가져오기"))
        match_row.addStretch(1)
        v.addLayout(match_row)

        v.addWidget(section_label("보여줄 아이콘"))
        show_row = QHBoxLayout()
        self.display_slot = icon_slot("—")
        show_row.addWidget(self.display_slot)
        show_row.addWidget(QPushButton("파일 선택"))
        show_row.addWidget(QPushButton("초기화"))
        show_row.addStretch(1)
        v.addLayout(show_row)
        v.addWidget(hint_label("└ 비워두면 매칭 아이콘 사용"))

        v.addSpacing(6)
        v.addWidget(
            hint_label("디버프는 '아직 걸리지 않은 것'만 오버레이에 나열됩니다.")
        )
        v.addStretch(1)
        return panel

    def _on_select(self, row: int) -> None:
        if not (0 <= row < len(self._catalog)):
            return
        debuff = self._catalog[row]
        self.name_edit.setText(debuff.name)
        pm = _pixmap(debuff.match_icon, 40)
        if pm is not None:
            self.match_slot.setPixmap(pm)
        self.display_slot.setText("—")  # 디버프는 표시이미지 없음(매칭 아이콘 사용)
