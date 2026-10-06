"""버프 탭 (기획서 5.1 상단).

왼쪽: 영역 지정 + 등록 버프 목록 + 순서 버튼
오른쪽: 선택한 버프의 상세 편집 폼
"""

from __future__ import annotations

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

from .widgets import hint_label, icon_slot, section_label

# 목록 미리보기용 샘플. 실제로는 설정 파일(buffTracker.buffs)에서 읽어온다.
_SAMPLE_BUFFS = [
    ("⚓", "프리미엄 배틀 멤버십 (앵커)"),
    ("▣", "마법 대미지 증가"),
    ("▣", "골렘의 의지"),
    ("⚠", "새 버프 (아이콘 없음)"),
]


class BuffTab(QWidget):
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

        v.addWidget(QPushButton("버프 영역 지정"))
        region = hint_label("영역: 1770,400  220×550  ✔")
        region.setStyleSheet("color:#2ecc71;")
        v.addWidget(region)

        self.buff_list = QListWidget()
        for marker, name in _SAMPLE_BUFFS:
            QListWidgetItem(f"{marker}  {name}", self.buff_list)
        self.buff_list.setCurrentRow(1)
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
        v.addWidget(QLineEdit("마법 대미지 증가"))

        v.addWidget(section_label("매칭 아이콘"))
        match_row = QHBoxLayout()
        match_row.addWidget(icon_slot())
        match_row.addWidget(QPushButton("상태창에서 가져오기"))
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
