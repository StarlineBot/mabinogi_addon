"""Entry cost calculator; market workers never access Qt objects."""

import queue
import threading
import time
import urllib.request

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import config
from ..market import auction, dungeon_cost as calc
from .calculator_sidebar import calculator_sidebar, refresh_button
from .widgets import FeatureHeader


def _fetch(result, key, cancelled):
    try:
        deadline = time.monotonic() + 30

        def open_page(request, timeout):
            remaining = deadline - time.monotonic()
            if cancelled.is_set() or remaining <= 0:
                raise TimeoutError("market request cancelled or expired")
            return urllib.request.urlopen(request, timeout=min(timeout, remaining))

        items = auction.fetch_items_by_name(calc.MATERIAL, key, urlopen=open_page)
        price = auction.min_unit_price(items, calc.MATERIAL)
        if price is not None and (type(price) is not int or price <= 0):
            raise ValueError("invalid price")
        result.put((price, ""))
    except Exception:
        result.put((None, "시세 조회에 실패했습니다. 다시 시도해 주세요."))


class DungeonCostTab(QWidget):
    def __init__(self):
        super().__init__()
        self._price = None
        self._clock = time.monotonic
        self._cache = None  # (monotonic receipt time, price or normal empty result, status)
        self._status = "믿음의 균열을 선택하면 편린 시세를 조회합니다."
        self._pending = None
        self._cancelled = threading.Event()
        self._poll = QTimer(self)
        self._poll.setInterval(100)
        self._poll.timeout.connect(self._receive)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.addWidget(FeatureHeader("던전 입장 계산기", "던전별 입장 비용과 누적 이익을 비교합니다. 믿음의 균열을 선택하면 편린 시세를 조회합니다."))
        layout = QHBoxLayout()
        root.addLayout(layout, 1)
        self.dungeons = calculator_sidebar(calc.NAMES)
        layout.addWidget(self.dungeons)
        right = QVBoxLayout()
        right.setSpacing(12)
        layout.addLayout(right, 1)
        head = QHBoxLayout()
        self.title = QLabel()
        self.title.setStyleSheet("font-size:15px;font-weight:800;")
        head.addWidget(self.title)
        head.addStretch()
        self.refresh = refresh_button("편린 시세 새로고침")
        self.refresh.clicked.connect(self._request)
        head.addWidget(self.refresh)
        right.addLayout(head)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        right.addWidget(self.summary)
        self.status = QLabel()
        self.status.setWordWrap(True)
        right.addWidget(self.status)
        self.table = QTableWidget()
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setAlternatingRowColors(True)
        right.addWidget(self.table, 1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        right.addWidget(self.note)
        self.dungeons.currentTextChanged.connect(self._select)
        self.dungeons.itemClicked.connect(self._select)
        self.dungeons.setCurrentRow(0)

    def _select(self, *_):
        if self._cancelled.is_set() or self.dungeons.currentItem() is None:
            return
        if self.dungeons.currentItem().text() != calc.NAMES[2]:
            self._render()
            return
        if self._pending is not None:
            self._render()
            return
        if self._cache is not None and self._clock() - self._cache[0] < 600:
            _, self._price, self._status = self._cache
            self._render()
            return
        self._request()

    def _render(self, *_):
        name = self.dungeons.currentItem().text()
        market = name == calc.NAMES[2]
        self.title.setText(name)
        self.refresh.setVisible(market)
        self.refresh.setEnabled(self._pending is None)
        if market:
            self.summary.setText("균열의 편린 · 최저 개당가 " +
                                 (f"{self._price:,}" if self._price is not None else "—"))
            self.status.setText(self._status)
            self.status.setStyleSheet("")
            columns = ["차수", "소모 개수", "해당 차수 비용", "누적 비용"]
            rows = calc.rift_rows(self._price)
            best = first_loss = None
        else:
            rows = calc.ticket_rows(name)
            best = max(rows, key=lambda r: r[2])[0]
            first_loss = next(r[0] for r in rows if r[2] < 0)
            self.summary.setText(f"매회 클리어 보상 {calc.REWARDS[name]:,} 골드")
            self.status.setText(f"최대 이익 {best}차 {rows[best-1][2]:+,} / 최초 누적 적자 {first_loss}차")
            self.status.setStyleSheet("color:#00C9A2;")
            columns = ["차수", "통행증 구매가", "누적 순이익"]
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                text = "—" if value is None else f"{value:,}"
                if j == 0:
                    text = f"{value}차"
                    if value == best:
                        text += " 최대"
                    if value == first_loss:
                        text += " 적자 시작"
                elif not market and j == 2:
                    text = f"{value:+,}"
                cell = QTableWidgetItem(text)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignVCenter |
                    (Qt.AlignmentFlag.AlignLeft if j == 0 else Qt.AlignmentFlag.AlignRight))
                if not market and (row[0] == best or (j == 2 and value < 0)):
                    cell.setForeground(QColor("#00C9A2" if row[0] == best else "#ef8585"))
                self.table.setItem(i, j, cell)
        detail = ("입장 비용만 계산하며 클리어 보상은 포함하지 않습니다." if market else
                  "누적 순이익 = 누적 보상 − 누적 구매 비용\n11차 이후 통행증은 매회 50,000,000 골드입니다.\n무료입장·보유 통행증·추가 드랍·소모품은 제외합니다.")
        self.note.setText("표시: 1~11차 · 실제 입장 가능 횟수를 의미하지 않습니다.\n" + detail)

    def _request(self):
        if self._pending is not None or self._cancelled.is_set():
            return
        self._price = None
        self._cache = None  # A forced refresh must not revive an earlier success on error.
        key = config.get_nexon_api_key()
        if not key:
            self._status = "넥슨 API 키가 없어 시세를 조회할 수 없습니다."
            self._render()
            return
        self._status = "시세 조회 중…"
        self._pending = queue.Queue(maxsize=1)
        threading.Thread(target=_fetch, args=(self._pending, key, self._cancelled), daemon=True).start()
        self._poll.start()
        self._render()

    def _receive(self):
        if self._cancelled.is_set() or self._pending is None:
            return
        try:
            price, error = self._pending.get_nowait()
        except queue.Empty:
            return
        self._pending = None
        self._poll.stop()
        self._price = price
        self._status = error or ("매물이 없습니다." if price is None else
            f"조회 {time.strftime('%H:%M')} · 경매 시세는 약 10분 지연됩니다.")
        if not error:
            self._cache = (self._clock(), self._price, self._status)
        self._render()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self):
        self._cancelled.set()
        self._poll.stop()
        self._pending = None
