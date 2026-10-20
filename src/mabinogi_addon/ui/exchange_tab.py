"""환전비율 계산기 탭 (편의기능).

왼쪽 지역 목록(탈라가흐·브리레흐·글렌베르나·크롬바스)에서 하나 고르면, 오른쪽에 그
지역 이름(제목) + 재료 테이블(재료명·상품가격·구슬개수·구슬당 가격)을 '구슬당 가격'
내림차순으로 보여준다. 최고 효율 행은 ⭐+볼드 강조. 조회는 백그라운드(UI 안 멈춤) +
지역별 짧은 캐시.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..market import auction, exchange
from .calculator_sidebar import calculator_sidebar, refresh_button
from .widgets import FeatureHeader, hint_label

_CACHE_TTL = 10 * 60  # 경매 데이터가 ~10분 지연이라 던전별 10분 캐시
_ACCENT = QColor("#00C9A2")
_GRAY = "color:#9aa0aa; font-size:12px;"


class ExchangeTab(QWidget):
    _done = Signal(object)  # (region, rows)
    _fail = Signal(object)  # (region, message)

    def __init__(self) -> None:
        super().__init__()
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._pending: str | None = None  # 마지막 요청 지역(늦게 온 응답 무시용)

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.addWidget(
            FeatureHeader("환전비율 계산기",
                "던전을 선택하면 구슬당 판매금액이 높은 재료부터 보여줍니다."
            )
        )

        body = QHBoxLayout()
        self.region_list = calculator_sidebar(exchange.REGION_NAMES)
        self.region_list.currentTextChanged.connect(self._on_region)
        body.addWidget(self.region_list)

        right = QVBoxLayout()
        title_row = QHBoxLayout()
        self.title = QLabel("던전을 선택하세요")
        self.title.setStyleSheet("font-size:15px; font-weight:800;")
        title_row.addWidget(self.title)
        title_row.addStretch(1)
        self.refresh_btn = refresh_button("경매 시세를 지금 다시 불러와요")
        self.refresh_btn.clicked.connect(self._on_refresh)
        self.refresh_btn.setEnabled(False)
        title_row.addWidget(self.refresh_btn)
        right.addLayout(title_row)
        self.asof = QLabel("경매 시세는 넥슨 API 특성상 10분가량 지연돼요.")
        self.asof.setStyleSheet(_GRAY)
        right.addWidget(self.asof)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["재료명", "상품가격", "구슬개수", "구슬당 가격"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        right.addWidget(self.table, 1)
        body.addLayout(right, 1)
        v.addLayout(body, 1)

        self._done.connect(self._show)
        self._fail.connect(self._show_fail)

    def _on_region(self, region: str, force: bool = False) -> None:
        if not region:
            return
        self._pending = region
        self.refresh_btn.setEnabled(True)
        cached = self._cache.get(region)
        if not force and cached and time.time() - cached[0] < _CACHE_TTL:
            self._render(region, cached[1])
            return
        self.title.setText(region)
        self.asof.setText("시세 확인 중…")
        self.table.setRowCount(0)
        threading.Thread(target=self._work, args=(region,), daemon=True).start()

    def _on_refresh(self) -> None:
        region = self.region_list.currentItem().text() if self.region_list.currentItem() else ""
        if region:
            self._on_region(region, force=True)

    def _work(self, region: str) -> None:
        key = config.get_nexon_api_key()
        if not key:
            self._fail.emit((region, "넥슨 API 키가 없어 시세를 불러올 수 없어요."))
            return
        mats = exchange.REGIONS.get(region, [])
        try:
            prices = auction.fetch_min_prices([m["name"] for m in mats], key)
        except Exception as exc:  # noqa: BLE001
            self._fail.emit((region, f"시세 조회 실패: {exc}"))
            return
        rows = exchange.calc_region(region, lambda name: prices.get(name))
        self._done.emit((region, rows or []))

    def _show(self, payload) -> None:
        region, rows = payload
        self._cache[region] = (time.time(), rows)
        if region == self._pending:  # 늦게 도착한 이전 지역 응답은 무시
            self._render(region, rows)

    def _show_fail(self, payload) -> None:
        region, message = payload
        if region == self._pending:
            self.title.setText(region)
            self.asof.setText("시세 조회 실패")
            self.table.setRowCount(0)
            self.table.setRowCount(1)
            cell = QTableWidgetItem(message)
            self.table.setItem(0, 0, cell)
            self.table.setSpan(0, 0, 1, 4)

    def _cell(self, text: str, *, align_right: bool, best: bool) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if align_right:
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
        if best:
            f = item.font()
            f.setBold(True)
            item.setFont(f)
            item.setForeground(QBrush(_ACCENT))
        return item

    def _render(self, region: str, rows: list[dict]) -> None:
        kg = auction.korean_gold
        self.title.setText(region)
        at = self._cache.get(region, (time.time(), None))[0]
        hhmm = time.strftime("%H:%M", time.localtime(at))
        self.asof.setText(f"조회 시각 {hhmm} · 경매 시세는 약 10분 지연됩니다.")
        best = next((r for r in rows if r["efficiency"] is not None), None)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            is_best = best is not None and r["name"] == best["name"]
            name = ("⭐ " if is_best else "") + r["name"]
            if r["efficiency"] is None:
                price_txt, eff_txt = "매물 없음", "-"
            else:
                price_txt, eff_txt = kg(r["per_unit"]), kg(r["efficiency"])
            self.table.setItem(i, 0, self._cell(name, align_right=False, best=is_best))
            self.table.setItem(i, 1, self._cell(price_txt, align_right=True, best=is_best))
            self.table.setItem(i, 2, self._cell(str(r["coin"]), align_right=True, best=is_best))
            self.table.setItem(i, 3, self._cell(eff_txt, align_right=True, best=is_best))
