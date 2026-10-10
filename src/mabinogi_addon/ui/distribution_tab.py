"""분배 계산기 탭 (편의기능).

판매가(만 단위)·분배 인원·수수료율(멤버십 4% / 기본 5%)을 넣으면, 경매장에서 수수료
할인 쿠폰 현재가를 조회해 쿠폰별 1인당 분배금을 보여주고 가장 이득인 쿠폰을 추천한다.
조회는 백그라운드 스레드(UI 안 멈춤), 키 없으면 '쿠폰 없음' 기준만 계산.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..market import auction, fee
from .widgets import hint_label


def _field(label_text: str, widget: QWidget) -> QWidget:
    """라벨(왼쪽정렬) 위 + 입력 아래의 세로 묶음. 가로로 나열하면 화면이 균등 분할된다."""
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(3)
    lbl = QLabel(label_text)
    lbl.setStyleSheet("color:#9aa0aa; font-size:12px;")
    lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
    v.addWidget(lbl)
    v.addWidget(widget)
    return box


class DistributionTab(QWidget):
    _done = Signal(object)  # (result, sale, headcount, membership, note)

    def __init__(self) -> None:
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.addWidget(
            hint_label(
                "경매장 판매가와 분배 인원을 넣으면 수수료·할인쿠폰까지 따져 1인당 "
                "분배금을 계산해요. 판매가는 만 단위(예: 8890 = 8,890만, 20000 = 2억)."
            )
        )

        # 상단 컨트롤: 수수료 / 판매가 / 인원 / 계산 — 가로로 균등하게.
        row = QHBoxLayout()
        row.setSpacing(10)

        rate_box = QWidget()
        rv = QVBoxLayout(rate_box)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(3)
        rlbl = QLabel("수수료")
        rlbl.setStyleSheet("color:#9aa0aa; font-size:12px;")
        rv.addWidget(rlbl)
        rate_row = QHBoxLayout()
        rate_row.setContentsMargins(0, 0, 0, 0)
        self.rate_membership = QRadioButton("4%(멤버십)")
        self.rate_base = QRadioButton("5%")
        self.rate_membership.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.rate_membership)
        grp.addButton(self.rate_base)
        rate_row.addWidget(self.rate_membership)
        rate_row.addWidget(self.rate_base)
        rv.addLayout(rate_row)
        row.addWidget(rate_box, 2)

        self.price_spin = QSpinBox()
        self.price_spin.setRange(1, 99_999_999)
        self.price_spin.setSuffix(" 만")
        self.price_spin.setGroupSeparatorShown(True)
        self.price_spin.setValue(10000)
        row.addWidget(_field("분배금", self.price_spin), 2)

        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 10)
        self.count_spin.setValue(4)
        row.addWidget(_field("분배 인원", self.count_spin), 1)

        self.calc_btn = QPushButton("계산")
        self.calc_btn.clicked.connect(self._on_calc)
        row.addWidget(_field(" ", self.calc_btn), 1)

        v.addLayout(row)

        self.result = QLabel("판매가·인원을 넣고 [계산]을 눌러요.")
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.result.setStyleSheet("font-size:13px;")
        self.result.setAlignment(Qt.AlignmentFlag.AlignTop)
        v.addWidget(self.result, 1)

        self._done.connect(self._show)

    def _on_calc(self) -> None:
        sale = self.price_spin.value() * 10000
        headcount = self.count_spin.value()
        membership = self.rate_membership.isChecked()
        self.result.setText("경매장에서 수수료 쿠폰 가격 확인 중…")
        threading.Thread(
            target=self._work, args=(sale, headcount, membership), daemon=True
        ).start()

    def _work(self, sale: int, headcount: int, membership: bool) -> None:
        key = config.get_nexon_api_key()
        prices: dict[str, int | None] = {}
        note = ""
        if not key:
            note = "넥슨 API 키가 없어 쿠폰 시세는 못 불러왔어요('쿠폰 없음' 기준만)."
        else:
            try:
                prices = auction.fetch_min_prices(fee.COUPON_NAMES, key)
            except Exception as exc:  # noqa: BLE001 — 조회 실패해도 기본 계산은 보여줌
                note = f"쿠폰 시세 조회 실패: {exc}"
        result = fee.calc_distribution(sale, headcount, membership, prices)
        self._done.emit((result, sale, headcount, membership, note))

    def _show(self, payload) -> None:
        result, sale, headcount, membership, note = payload
        kg = auction.korean_gold
        rate_txt = "멤버십 4%" if membership else "기본 5%"
        lines = [
            f"판매가 {sale:,} ({kg(sale)}) · {headcount}명 · {rate_txt}",
            "",
        ]
        best = result["best"]
        for r in result["rows"]:
            mark = "⭐ " if best and r["label"] == best["label"] else "• "
            if not r["available"]:
                lines.append(f"{mark}{r['label']} — 쿠폰 가격 조회 안됨")
                continue
            if r["pct"] == 0:
                fee_part = f"수수료 {r['fee_after']:,}"
            else:
                fee_part = f"수수료 {r['fee_after']:,} + 쿠폰 {(r['coupon_price'] or 0):,}"
            lines.append(
                f"{mark}{r['label']} — 1인당 {r['per_person']:,} ({kg(r['per_person'])}) · {fee_part}"
            )
        if best:
            lines.append("")
            lines.append(
                f"🏆 추천: {best['label']} → 1인당 {best['per_person']:,}숲 "
                f"({kg(best['per_person'])})"
            )
        if note:
            lines.append("")
            lines.append(f"※ {note}")
        self.result.setText("\n".join(lines))
