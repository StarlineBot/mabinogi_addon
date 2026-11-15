"""제작 재료 계산기(docs/craft-material-calculator-spec.md, 0.50.0 모든 사용자).

왼쪽 시리즈 목록 · 무기 드롭다운 · 제작 방법 · 남은 재료 합계 · 표(재료 | 필요 | 보유 | 남음 | 개당 최저가 | 남은 가격).
- 무기·재료 이름은 데이터 파일(assets/craft/*.json)에서만 온다.
- 보유 개수는 재료 이름별 저장(config craftOwned, 무기끼리 공유). 입력하면 바로 다시 계산하되 줄은 움직이지 않는다
  (남은 재료 위·다 모은 재료 아래 정렬은 무기를 바꿀 때·탭에 다시 들어올 때만).
- 시세는 작업 스레드(던전 입장 계산기와 같은 _fetch·_receive 구조 — 작업 스레드는 Qt 객체를 건드리지 않음), 재료별 10분 세션 캐시.
"""
from __future__ import annotations

import queue
import threading
import time
import urllib.request

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import config
from ..market import auction, craft
from .calculator_sidebar import calculator_sidebar, refresh_button
from .palette import color
from .widgets import FeatureHeader

TITLE = "제작 재료 계산기"
DESCRIPTION = "무기별 필요 재료를 보고, 가진 개수를 적어 두면 남은 재료와 경매장 가격 합계를 보여 줘요."
REFRESH_TIP = "최저가 기준이에요. 많이 사면 실제 비용은 더 들 수 있어요."
OWNED_NOTE = "보유 개수는 재료별로 저장돼 다른 무기에도 같이 적용돼요."
NO_KEY = "넥슨 API 키가 없어 시세를 조회할 수 없어요."
LOADING = "시세 조회 중…"
FAILED_ALL = "시세 조회에 실패했어요. 다시 시도해 주세요."
COLUMNS = ["재료", "필요", "보유", "남음", "개당 최저가", "남은 가격"]
_OWNED_COL = 2


def _fetch(result, names, key, cancelled):
    """작업 스레드: 재료 시세 → result 큐에 {재료: 최저가|None(매물 없음)|FAILED}. Qt 객체를 건드리지 않는다."""
    try:
        deadline = time.monotonic() + 30

        def open_page(request, timeout):
            remaining = deadline - time.monotonic()
            if cancelled.is_set() or remaining <= 0:
                raise TimeoutError("market request cancelled or expired")
            return urllib.request.urlopen(request, timeout=min(timeout, remaining))

        prices = auction.fetch_min_prices(names, key, urlopen=open_page, failed=craft.FAILED)
        for name, price in prices.items():
            if price is not None and price != craft.FAILED and (type(price) is not int or price <= 0):
                prices[name] = craft.FAILED
        result.put(prices)
    except Exception:  # noqa: BLE001
        result.put({name: craft.FAILED for name in names})


class CraftTab(QWidget):
    def __init__(self, series: list[craft.Series] | None = None, *, clock=time.monotonic):
        super().__init__()
        self._series = craft.load_series() if series is None else list(series)
        self._cache = craft.PriceCache(clock=clock)
        self._stamp: dict[str, str] = {}  # 재료 → 조회 HH:MM
        self._failed: set[str] = set()  # 이번 세션에 조회 실패한 재료(캐시 안 함)
        self._status_override: str | None = None  # 키 없음·조회 중·전부 실패
        self._pending = None
        self._pending_names: list[str] = []
        self._cancelled = threading.Event()
        self._order: list[str] = []  # 지금 표의 재료 순서(입력 중에는 그대로)
        self._spins: dict[str, QSpinBox] = {}
        self._poll = QTimer(self)
        self._poll.setInterval(100)
        self._poll.timeout.connect(self._receive)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.addWidget(FeatureHeader(TITLE, DESCRIPTION))
        layout = QHBoxLayout()
        root.addLayout(layout, 1)
        self.series_list = calculator_sidebar([s.name for s in self._series])
        layout.addWidget(self.series_list)
        right = QVBoxLayout()
        right.setSpacing(10)
        layout.addLayout(right, 1)

        head = QHBoxLayout()
        weapon = QLabel("무기")
        weapon.setStyleSheet("font-size:15px;font-weight:800;")
        head.addWidget(weapon)
        self.weapon = QComboBox()
        self.weapon.setMinimumContentsLength(8)  # 글자가 커도 가로 넘침 없게(넓으면 늘어남)
        self.weapon.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.weapon.setMaximumWidth(360)
        head.addWidget(self.weapon, 1)
        head.addStretch(0)
        self.refresh = refresh_button(REFRESH_TIP)
        self.refresh.clicked.connect(lambda: self._request(force=True))
        head.addWidget(self.refresh)
        right.addLayout(head)

        skill_row = QHBoxLayout()
        skill_label = QLabel("제작 방법")
        skill_label.setStyleSheet(f"color:{color('muted')};")
        skill_row.addWidget(skill_label)
        self.skill = QLabel()
        self.skill.setStyleSheet("font-size:17px;font-weight:800;")  # 일반 글자색(민트는 합계만)
        skill_row.addWidget(self.skill)
        skill_row.addStretch(1)
        right.addLayout(skill_row)

        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        right.addWidget(self.summary)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{color('muted')};")
        right.addWidget(self.status)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumWidth(0)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(COLUMNS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        right.addWidget(self.table, 1)

        foot = QHBoxLayout()
        self.hide_done = QCheckBox("다 모은 재료 숨기기")
        self.hide_done.setChecked(config.load_craft_hide_done())
        self.hide_done.toggled.connect(self._on_hide_done)
        foot.addWidget(self.hide_done, 0, Qt.AlignmentFlag.AlignTop)
        note = QLabel(OWNED_NOTE)
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        note.setStyleSheet(f"color:{color('muted')};")
        foot.addWidget(note, 1)
        right.addLayout(foot)

        self.series_list.currentRowChanged.connect(self._on_series)
        self.weapon.currentIndexChanged.connect(self._on_weapon)
        if self._series:
            self.series_list.setCurrentRow(0)

    # ---- 선택 ----
    def current_series(self) -> craft.Series | None:
        row = self.series_list.currentRow()
        return self._series[row] if 0 <= row < len(self._series) else None

    def current_item(self) -> craft.Item | None:
        series = self.current_series()
        i = self.weapon.currentIndex()
        return series.items[i] if series is not None and 0 <= i < len(series.items) else None

    def _on_series(self, _row: int) -> None:
        series = self.current_series()
        self.weapon.blockSignals(True)
        self.weapon.clear()
        if series is not None:
            self.weapon.addItems([item.name for item in series.items])
        self.weapon.blockSignals(False)
        self._on_weapon()

    def _on_weapon(self, *_):
        item = self.current_item()
        if item is None:
            return
        self.skill.setText(item.skill)
        self._resort()
        names = [m for m, _ in item.materials]
        if self._cache.missing(names):
            self._request(force=False)
        else:
            self._status_override = None
            self._update()

    def showEvent(self, event):  # 탭에 다시 들어오면 남은 재료 위로 다시 정렬
        super().showEvent(event)
        if self.current_item() is not None:
            self._resort()

    def _on_hide_done(self, on: bool) -> None:
        config.set_craft_hide_done(on)
        self._resort()

    # ---- 계산·표 ----
    def _prices(self, item: craft.Item) -> dict:
        out = {}
        for material, _ in item.materials:
            hit, value = self._cache.get(material)
            if hit:
                out[material] = value
            elif material in self._failed:
                out[material] = craft.FAILED
        return out

    def summary_now(self) -> craft.Summary | None:
        item = self.current_item()
        return None if item is None else craft.compute(item, config.load_craft_owned(), self._prices(item))

    def _resort(self) -> None:
        """남은 재료 위·다 모은 재료 아래로 다시 늘어놓고 표를 새로 만든다(무기 변경·탭 진입·숨기기 토글 때만)."""
        summary = self.summary_now()
        if summary is None:
            return
        rows = [r for r in summary.rows if not (self.hide_done.isChecked() and r.done)]
        self._order = [r.material for r in rows]
        self._spins = {}
        for spin in self.table.findChildren(QSpinBox):  # 예전 칸 위젯이 자리에 남지 않게 모두 지우고 새로
            spin.hide()
            spin.deleteLater()
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for col in range(len(COLUMNS)):
                if col == _OWNED_COL:
                    spin = QSpinBox()
                    spin.setRange(0, craft.OWNED_MAX)
                    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
                    spin.setAlignment(Qt.AlignmentFlag.AlignRight)
                    spin.setValue(row.owned)
                    spin.valueChanged.connect(lambda value, m=row.material: self._on_owned(m, value))
                    self.table.setCellWidget(i, col, spin)
                    self._spins[row.material] = spin
                else:
                    cell = QTableWidgetItem()
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignVCenter |
                                          (Qt.AlignmentFlag.AlignLeft if col == 0 else Qt.AlignmentFlag.AlignRight))
                    self.table.setItem(i, col, cell)
        self._update()

    def _on_owned(self, material: str, value: int) -> None:
        config.set_craft_owned(material, value)
        self._update()  # 줄 순서는 그대로

    def _update(self) -> None:
        """표 글자·합계·상태만 다시(줄 순서는 _order 그대로)."""
        summary = self.summary_now()
        if summary is None:
            return
        by_name = {r.material: r for r in summary.rows}
        muted, accent, warn = QColor(color("muted")), QColor(color("accent")), QColor(color("warn"))
        default = self.table.palette().text().color()
        for i, material in enumerate(self._order):
            r = by_name.get(material)
            if r is None:
                continue
            if r.done:
                price_text, cost_text, price_color = "—", "", muted
            elif r.price is None:
                price_text, cost_text, price_color = "매물 없음", "—", warn
            elif r.price == craft.FAILED:
                price_text, cost_text, price_color = "조회 실패", "—", warn
            elif r.price == "":
                price_text, cost_text, price_color = "—", "—", default
            else:
                price_text, cost_text, price_color = f"{r.price:,}", auction.korean_gold(r.cost), default
            texts = [r.material, str(r.need), None, "✓" if r.done else str(r.left), price_text, cost_text]
            for col, text in enumerate(texts):
                if text is None:
                    continue
                cell = self.table.item(i, col)
                cell.setText(text)
                if r.done:
                    cell.setForeground(muted)
                elif col == 4:
                    cell.setForeground(price_color)
                elif col == 5 and r.cost is not None:
                    cell.setForeground(accent)
                else:
                    cell.setForeground(default)
        total = auction.korean_gold(summary.total) if summary.total or self._known(summary) else "—"
        self.summary.setText(
            f"남은 재료 {summary.left_kinds}종 · 경매장 최저가 합계 "
            f"<span style='color:{color('accent')};font-size:17px;font-weight:800;'>{total}</span> 골드")
        self.status.setText(self._status_text(summary))
        self.refresh.setEnabled(self._pending is None)

    @staticmethod
    def _known(summary: craft.Summary) -> bool:
        return any(r.cost is not None for r in summary.rows if not r.done)

    def _status_text(self, summary: craft.Summary) -> str:
        if self._status_override:
            return self._status_override
        item = self.current_item()
        stamps = sorted(self._stamp[m] for m, _ in item.materials if m in self._stamp)
        if not stamps:
            return ""
        text = f"조회 {stamps[0]} · 경매 시세는 약 10분 지연돼요."
        if summary.no_listing:
            text += f" 매물 없는 재료 {summary.no_listing}종은 합계에서 빠졌어요."
        if summary.failed:
            text += f" 조회에 실패한 재료 {summary.failed}종은 합계에서 빠졌어요."
        return text

    # ---- 시세 ----
    def _request(self, *, force: bool) -> None:
        if self._cancelled.is_set():
            return
        item = self.current_item()
        if item is None:
            return
        if self._pending is not None:  # 조회 중: 끝나면 _receive가 지금 무기에 빠진 것을 다시 조회
            self._status_override = LOADING
            self._update()
            return
        names = [m for m, _ in item.materials]
        if force:
            self._cache.drop(names)
        else:
            names = self._cache.missing(names)
        key = config.get_nexon_api_key()
        if not key:
            self._status_override = NO_KEY
            self._update()
            return
        self._failed.difference_update(names)
        self._status_override = LOADING
        self._pending = queue.Queue(maxsize=1)
        self._pending_names = names
        threading.Thread(target=_fetch, args=(self._pending, names, key, self._cancelled), daemon=True).start()
        self._poll.start()
        self._update()

    def _receive(self) -> None:
        if self._cancelled.is_set() or self._pending is None:
            return
        try:
            prices = self._pending.get_nowait()
        except queue.Empty:
            return
        self._pending = None
        self._poll.stop()
        stamp = time.strftime("%H:%M")
        for name in self._pending_names:
            value = prices.get(name, craft.FAILED)
            if value == craft.FAILED:
                self._failed.add(name)
                continue
            self._cache.put(name, value)
            self._stamp[name] = stamp
        all_failed = bool(self._pending_names) and all(prices.get(n, craft.FAILED) == craft.FAILED for n in self._pending_names)
        self._status_override = FAILED_ALL if all_failed else None
        item = self.current_item()
        if item is not None and self._cache.missing(m for m, _ in item.materials if m not in self._failed):
            self._request(force=False)  # 조회 중에 무기를 바꿨으면 그 무기 재료를 이어서
            return
        self._update()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        self._cancelled.set()
        self._poll.stop()
        self._pending = None
