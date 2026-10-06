"""파티 탭 (기획서 3.5).

넥슨 거뿔 API를 폴링해 파티모집현황을 리스트로 보여주고, 키워드 매칭 시 토스트.
키워드·파티장 제외 목록은 config.local.json에 저장된다.
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

from .. import config
from ..party.models import Recruit
from ..party.service import humanize_age
from ..party.worker import PartyWorker
from .toast import show_toast
from .widgets import hint_label

_DIM = QColor("#9aa0a6")


class PartyTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._keywords, self._excludes = config.load_party_lists()
        self._worker: PartyWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        root.addWidget(self._build_board(), 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        bottom.addWidget(self._build_keywords())
        bottom.addWidget(self._build_excludes())
        root.addLayout(bottom)

    # ---- 현황판 ----
    def _build_board(self) -> QGroupBox:
        box = QGroupBox("파티모집현황 (하프 서버)")
        v = QVBoxLayout(box)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["채널", "파티장", "제목", "인원", "시간"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self.table)

        self.status_label = hint_label("대기 중 · 탐지 시작 시 10초마다 갱신")
        v.addWidget(self.status_label)
        return box

    def _populate(self, recruits: list[Recruit]) -> None:
        self.table.setRowCount(0)
        for recruit in recruits:
            row = self.table.rowCount()
            self.table.insertRow(row)

            channel = QTableWidgetItem(f"채널 {recruit.channel}")
            leader = QTableWidgetItem(recruit.character_name)
            title = QTableWidgetItem(("✅ " if recruit.done else "") + recruit.content)
            count = QTableWidgetItem(recruit.headcount)
            count.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            age = QTableWidgetItem(humanize_age(recruit.date_send))
            age.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            age.setForeground(QBrush(_DIM))  # 시각은 항상 흐리게(보조 정보)

            items = [channel, leader, title, count, age]
            for col, item in enumerate(items):
                if recruit.done and col != 4:
                    item.setForeground(QBrush(_DIM))
                self.table.setItem(row, col, item)

    # ---- 키워드 ----
    def _build_keywords(self) -> QGroupBox:
        box = QGroupBox("키워드 알림")
        v = QVBoxLayout(box)

        add_row = QHBoxLayout()
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("제목에 포함될 단어 (예: 글렌, 글라스)")
        self.keyword_input.returnPressed.connect(self._add_keyword)
        add_button = QPushButton("등록")
        add_button.clicked.connect(self._add_keyword)
        add_row.addWidget(self.keyword_input, 1)
        add_row.addWidget(add_button)
        v.addLayout(add_row)

        self.keyword_list = QListWidget()
        self.keyword_list.setMaximumHeight(96)
        self.keyword_list.addItems(self._keywords)
        v.addWidget(self.keyword_list)

        remove_button = QPushButton("선택 삭제")
        remove_button.clicked.connect(self._remove_keyword)
        btn_row = QHBoxLayout()
        btn_row.addWidget(remove_button)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        v.addWidget(
            hint_label("등록한 키워드가 뜨면 화면 우측 하단에 토스트 알림 (3초 후 사라짐)")
        )
        return box

    def _add_keyword(self) -> None:
        text = self.keyword_input.text().strip()
        if not text or text in self._keywords:
            self.keyword_input.clear()
            return
        self._keywords.append(text)
        self.keyword_list.addItem(text)
        self.keyword_input.clear()
        self._save()

    def _remove_keyword(self) -> None:
        for item in self.keyword_list.selectedItems():
            self._keywords.remove(item.text())
            self.keyword_list.takeItem(self.keyword_list.row(item))
        self._save()

    # ---- 파티장 제외 ----
    def _build_excludes(self) -> QGroupBox:
        box = QGroupBox("파티장 제외")
        v = QVBoxLayout(box)

        add_row = QHBoxLayout()
        self.exclude_input = QLineEdit()
        self.exclude_input.setPlaceholderText("제외할 파티장 캐릭터명")
        self.exclude_input.returnPressed.connect(self._add_exclude)
        add_button = QPushButton("등록")
        add_button.clicked.connect(self._add_exclude)
        add_row.addWidget(self.exclude_input, 1)
        add_row.addWidget(add_button)
        v.addLayout(add_row)

        self.exclude_list = QListWidget()
        self.exclude_list.setMaximumHeight(96)
        self.exclude_list.addItems(self._excludes)
        v.addWidget(self.exclude_list)

        remove_button = QPushButton("선택 삭제")
        remove_button.clicked.connect(self._remove_exclude)
        btn_row = QHBoxLayout()
        btn_row.addWidget(remove_button)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        v.addWidget(hint_label("이 파티장의 모집은 현황·알림에서 숨깁니다"))
        return box

    def _add_exclude(self) -> None:
        text = self.exclude_input.text().strip()
        if not text or text in self._excludes:
            self.exclude_input.clear()
            return
        self._excludes.append(text)
        self.exclude_list.addItem(text)
        self.exclude_input.clear()
        self._save()

    def _remove_exclude(self) -> None:
        for item in self.exclude_list.selectedItems():
            self._excludes.remove(item.text())
            self.exclude_list.takeItem(self.exclude_list.row(item))
        self._save()

    def _save(self) -> None:
        config.save_party_lists(self._keywords, self._excludes)

    # ---- 폴링 ----
    def start_polling(self) -> None:
        if self._worker is not None:
            return
        self._worker = PartyWorker(
            get_api_key=config.get_nexon_api_key,
            get_keywords=lambda: list(self._keywords),
            get_excludes=lambda: list(self._excludes),
        )
        self._worker.updated.connect(self._populate)
        self._worker.alerted.connect(self._on_alert)
        self._worker.status.connect(self._on_status)
        self._worker.start()

    def stop_polling(self) -> None:
        if self._worker is None:
            return
        self._worker.stop()
        self._worker.wait(2000)
        self._worker = None

    def _on_alert(self, keyword: str, recruit: Recruit) -> None:
        meta = " · ".join(
            part
            for part in (
                recruit.character_name,
                f"채널 {recruit.channel}",
                recruit.headcount,
                humanize_age(recruit.date_send),
            )
            if part
        )
        show_toast(f"🔔 파티모집 · '{keyword}'", f"{recruit.content}\n{meta}")

    def _on_status(self, text: str) -> None:
        self.status_label.setText(text or "실행 중 · 10초마다 갱신")
