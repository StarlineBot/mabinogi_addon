"""환전비율 계산기 탭 (편의기능).

왼쪽 지역 목록(탈라가흐·브리레흐·글렌베르나·크롬바스)에서 하나 고르면, 그 지역의
구슬 교환 재료들을 경매장 현재 개당가로 조회해 '구슬당 골드' 효율 순위를 오른쪽에
보여준다. 조회는 백그라운드(UI 안 멈춤) + 지역별 짧은 캐시.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..market import auction, exchange
from .widgets import hint_label

_CACHE_TTL = 10 * 60  # 경매 데이터가 ~10분 지연이라 지역별 10분 캐시


class ExchangeTab(QWidget):
    _done = Signal(object)  # (region, rows) / _fail: (region, message)
    _fail = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._pending: str | None = None  # 마지막으로 요청한 지역(늦게 온 응답 무시용)

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.addWidget(
            hint_label(
                "던전 구슬로 어떤 재료를 바꿔 팔아야 이득인지, 지역을 고르면 경매장 "
                "현재가 기준 '구슬당 골드' 순위를 보여줘요."
            )
        )

        body = QHBoxLayout()
        self.region_list = QListWidget()
        self.region_list.addItems(exchange.REGION_NAMES)
        self.region_list.setFixedWidth(120)
        self.region_list.currentTextChanged.connect(self._on_region)
        body.addWidget(self.region_list)

        self.result = QLabel("왼쪽에서 지역을 선택하세요.")
        self.result.setWordWrap(True)
        self.result.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.result.setStyleSheet("font-size:13px;")
        body.addWidget(self.result, 1)
        v.addLayout(body, 1)

        self._done.connect(self._show)
        self._fail.connect(self._show_fail)

    def _on_region(self, region: str) -> None:
        if not region:
            return
        self._pending = region
        cached = self._cache.get(region)
        if cached and time.time() - cached[0] < _CACHE_TTL:
            self._render(region, cached[1])
            return
        self.result.setText(f"{region} 교환 재료 시세 확인 중…")
        threading.Thread(target=self._work, args=(region,), daemon=True).start()

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
            self.result.setText(message)

    def _render(self, region: str, rows: list[dict]) -> None:
        kg = auction.korean_gold
        best = next((r for r in rows if r["efficiency"] is not None), None)
        lines = [f"[{region}] 구슬당 골드 순위", ""]
        for r in rows:
            mark = "⭐ " if best and r["name"] == best["name"] else "• "
            if r["efficiency"] is None:
                lines.append(f"{mark}{r['name']} — 매물 없음 (구슬 {r['coin']})")
            else:
                lines.append(
                    f"{mark}{r['name']} — 구슬당 {kg(r['efficiency'])} "
                    f"(개당 {kg(r['per_unit'])} / 구슬 {r['coin']})"
                )
        if best:
            lines.append("")
            lines.append(
                f"🏆 추천: {best['name']} — 구슬당 {kg(best['efficiency'])} "
                f"({best['efficiency']:,}골드)"
            )
        self.result.setText("\n".join(lines))
