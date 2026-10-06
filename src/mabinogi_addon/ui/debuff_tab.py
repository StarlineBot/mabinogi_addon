"""디버프 탭 (기획서 5.1 하단 주석).

버프 탭과 구조는 같지만 폼이 단순하다: 이름, 매칭 아이콘(영역에서 가져오기),
보여줄 아이콘만. 지속시간·알림·앵커 없음.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .widgets import hint_label, icon_slot, section_label

_SAMPLE_DEBUFFS = [
    ("▣", "방어력 감소"),
    ("▣", "화상"),
    ("⚠", "새 디버프 (아이콘 없음)"),
]


class DebuffTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(14)
        outer.addWidget(self._build_list_panel(), 1)
        outer.addWidget(self._build_form_panel(), 1)

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)

        v.addWidget(QPushButton("디버프 줄 영역 지정"))
        region = hint_label("영역: 795,945  410×30  ✔")
        region.setStyleSheet("color:#2ecc71;")
        v.addWidget(region)

        self.debuff_list = QListWidget()
        for marker, name in _SAMPLE_DEBUFFS:
            QListWidgetItem(f"{marker}  {name}", self.debuff_list)
        self.debuff_list.setCurrentRow(0)
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
        v.addWidget(QLineEdit("방어력 감소"))

        v.addWidget(section_label("매칭 아이콘"))
        match_row = QHBoxLayout()
        match_row.addWidget(icon_slot())
        match_row.addWidget(QPushButton("영역에서 가져오기"))
        match_row.addStretch(1)
        v.addLayout(match_row)

        v.addWidget(section_label("보여줄 아이콘"))
        show_row = QHBoxLayout()
        show_row.addWidget(icon_slot("—"))
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
