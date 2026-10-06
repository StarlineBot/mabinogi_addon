"""파티 탭 (기획서 3.5).

넥슨 거뿔 API에서 읽은 파티모집현황을 리스트로 나열하고, 키워드를 등록한다.
지금은 레이아웃 확정용 껍데기 — 실제 API 폴링·토스트는 다음 단계.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .widgets import hint_label

# 현황판 미리보기용 샘플. (채널, 파티장, 제목, 인원, 완료)
_SAMPLE_PARTIES = [
    ("14", "글렌해방", "글렌베르나 레이드 같이가요 딜러 구함", "1/4", False),
    ("7", "아스라이", "브리레흐 8인 모집 힐러 우대", "5/8", False),
    ("22", "초코케이크", "탈라가흐 실숙 고고", "3/4", False),
    ("3", "달빛소녀", "크롬바스 심연 마무리 한 자리", "3/4", False),
    ("31", "별빛나그네", "믿음의 균열 풀파티", "8/8", True),
]
_SAMPLE_KEYWORDS = ["글렌", "글라스"]


class PartyTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)
        v.addWidget(self._build_board(), 1)
        v.addWidget(self._build_keywords())

    def _build_board(self) -> QGroupBox:
        box = QGroupBox("파티모집현황 (하프 서버)")
        v = QVBoxLayout(box)

        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["채널", "파티장", "제목", "인원"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        dim = QBrush(QColor("#9aa0a6"))
        for ch, leader, title, count, done in _SAMPLE_PARTIES:
            row = table.rowCount()
            table.insertRow(row)

            ch_item = QTableWidgetItem(f"채널 {ch}")
            leader_item = QTableWidgetItem(leader)
            title_item = QTableWidgetItem(("✅ " if done else "") + title)
            count_item = QTableWidgetItem(count)
            count_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

            items = [ch_item, leader_item, title_item, count_item]
            for col, item in enumerate(items):
                if done:
                    item.setForeground(dim)
                table.setItem(row, col, item)

        v.addWidget(table)
        v.addWidget(hint_label("10초마다 자동 갱신 · 사람당 최신 1건 · 상위 5개"))
        return box

    def _build_keywords(self) -> QGroupBox:
        box = QGroupBox("키워드 알림")
        v = QVBoxLayout(box)

        add_row = QHBoxLayout()
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("제목에 포함될 단어 (예: 글렌, 글라스)")
        add_row.addWidget(self.keyword_input, 1)
        add_row.addWidget(QPushButton("등록"))
        v.addLayout(add_row)

        self.keyword_list = QListWidget()
        self.keyword_list.setMaximumHeight(96)
        for keyword in _SAMPLE_KEYWORDS:
            QListWidgetItem(keyword, self.keyword_list)
        v.addWidget(self.keyword_list)

        btn_row = QHBoxLayout()
        btn_row.addWidget(QPushButton("선택 삭제"))
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        v.addWidget(
            hint_label("등록한 키워드가 뜨면 화면 우측 하단에 토스트 알림 (3초 후 사라짐)")
        )
        return box
