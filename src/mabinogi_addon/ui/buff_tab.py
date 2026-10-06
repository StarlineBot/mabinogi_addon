"""버프 탭 (기획서 5.1 상단).

왼쪽: 영역 지정 + 버프 목록(카탈로그) + 순서 버튼
오른쪽: 선택한 버프의 상세 편집 폼
목록은 catalog.load_catalog()로 채운다(매칭용 아이콘 + 표시용 이미지).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..catalog import BuffDef, load_catalog
from .widgets import hint_label, icon_slot, section_label


def _pixmap(path: Path | None, size: int) -> QPixmap | None:
    if path is None:
        return None
    pm = QPixmap(str(path))
    if pm.isNull():
        return None
    return pm.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation,  # Nearest (픽셀 아이콘 선명)
    )


class BuffTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._catalog: list[BuffDef] = load_catalog()

        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(14)
        outer.addWidget(self._build_list_panel(), 1)
        outer.addWidget(self._build_form_panel(), 1)

        if self._catalog:
            self.buff_list.setCurrentRow(0)

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)

        v.addWidget(QPushButton("버프 영역 지정"))
        region = hint_label("영역 미지정 — 버튼으로 상태창 영역을 지정하세요")
        v.addWidget(region)

        self.buff_list = QListWidget()
        self.buff_list.setIconSize(QSize(32, 32))
        for buff in self._catalog:
            item = QListWidgetItem(buff.name)
            # 표시이미지 우선, 없으면 매칭 아이콘
            pm = _pixmap(buff.display_image or buff.match_icon, 32)
            if pm is not None:
                item.setIcon(QIcon(pm))
            self.buff_list.addItem(item)
        self.buff_list.currentRowChanged.connect(self._on_select)
        v.addWidget(self.buff_list, 1)

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
        match_row.addWidget(QPushButton("상태창에서 가져오기"))
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
        show_duration = QCheckBox("지속시간 표시")
        show_duration.setChecked(True)
        v.addWidget(show_duration)

        alert_row = QHBoxLayout()
        alert = QCheckBox("종료 알림")
        alert.setChecked(True)
        before = QSpinBox()
        before.setRange(1, 300)
        before.setValue(30)
        before.setSuffix(" 초 전")
        blink = QCheckBox("점멸")
        blink.setChecked(True)
        sound = QCheckBox("소리")
        sound.setChecked(True)
        alert_row.addWidget(alert)
        alert_row.addWidget(before)
        alert_row.addWidget(blink)
        alert_row.addWidget(sound)
        alert_row.addStretch(1)
        v.addLayout(alert_row)

        v.addWidget(QCheckBox("앵커로 사용 (항상 있는 버프)"))
        v.addStretch(1)
        return panel

    def _on_select(self, row: int) -> None:
        if not (0 <= row < len(self._catalog)):
            return
        buff = self._catalog[row]
        self.name_edit.setText(buff.name)
        self._set_slot(self.match_slot, buff.match_icon, "▣")
        self._set_slot(self.display_slot, buff.display_image, "—")

    def _set_slot(self, slot, path: Path | None, placeholder: str) -> None:
        pm = _pixmap(path, 40)
        if pm is not None:
            slot.setPixmap(pm)
        else:
            slot.setText(placeholder)
