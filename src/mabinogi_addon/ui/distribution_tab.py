"""분배 계산기 탭 (편의기능).

판매가(만 단위)·분배 인원·수수료율(멤버십 4% / 기본 5%)을 넣으면, 경매장에서 수수료
할인 쿠폰 현재가를 조회해 쿠폰별 1인당 분배금을 2열 카드로 보여준다. 가장 이득인
쿠폰 카드는 ⭐+볼드로 강조(별도 추천 줄 없음). 조회는 백그라운드(UI 안 멈춤),
키 없으면 '쿠폰 없음' 기준만 계산.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
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
from .widgets import SuffixSpinBox, hint_label

_GRAY = "color:#9aa0aa; font-size:12px;"


class DistributionTab(QWidget):
    _done = Signal(object)  # (result, sale, headcount, membership, note)

    def __init__(self) -> None:
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        v.addWidget(
            hint_label(
                "경매장 판매가와 분배 인원을 넣으면 수수료·할인쿠폰까지 따져 "
                "1인당 분배금을 계산해요.\n판매가는 만 단위예요 "
                "(예: 8890 = 8,890만, 20000 = 2억)."
            )
        )

        # 1줄: 수수료
        r1 = QHBoxLayout()
        lbl = QLabel("수수료")
        lbl.setStyleSheet(_GRAY)
        r1.addWidget(lbl)
        self.rate_membership = QRadioButton("4%(멤버십)")
        self.rate_base = QRadioButton("5%")
        self.rate_membership.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.rate_membership)
        grp.addButton(self.rate_base)
        r1.addWidget(self.rate_membership)
        r1.addWidget(self.rate_base)
        r1.addStretch(1)
        v.addLayout(r1)

        # 2줄: 분배금 [입력]  인원 [입력] (라벨 왼쪽정렬)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("분배금"))
        self.price_spin = SuffixSpinBox()
        self.price_spin.setRange(0, 99_999_999)
        self.price_spin.setSuffix(" 만")
        self.price_spin.setGroupSeparatorShown(True)
        self.price_spin.setValue(0)
        self.price_spin.setMinimumWidth(140)
        self.price_spin.lineEdit().returnPressed.connect(self._on_calc)  # 엔터로 계산
        r2.addWidget(self.price_spin)
        r2.addSpacing(18)
        r2.addWidget(QLabel("인원"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 10)
        self.count_spin.setValue(1)
        self.count_spin.lineEdit().returnPressed.connect(self._on_calc)  # 엔터로 계산
        r2.addWidget(self.count_spin)
        r2.addStretch(1)
        v.addLayout(r2)

        # 전체폭 결과 보기 버튼
        self.calc_btn = QPushButton("결과 보기")
        self.calc_btn.clicked.connect(self._on_calc)
        v.addWidget(self.calc_btn)

        # 결과: 2열 카드 그리드
        self.result_area = QWidget()
        self.grid = QGridLayout(self.result_area)
        self.grid.setContentsMargins(0, 4, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)
        self._placeholder = QLabel("판매가·인원을 넣고 [결과 보기]를 눌러요.")
        self._placeholder.setStyleSheet(_GRAY)
        self.grid.addWidget(self._placeholder, 0, 0, 1, 2)
        v.addWidget(self.result_area)

        self.note_lbl = QLabel("")
        self.note_lbl.setWordWrap(True)
        self.note_lbl.setStyleSheet(_GRAY)
        v.addWidget(self.note_lbl)
        v.addStretch(1)

        self._done.connect(self._show)

    def _on_calc(self) -> None:
        sale = self.price_spin.value() * 10000
        headcount = self.count_spin.value()
        membership = self.rate_membership.isChecked()
        self._clear_grid()
        if sale <= 0:
            msg = QLabel("판매가를 입력하세요.")
            msg.setStyleSheet(_GRAY)
            self.grid.addWidget(msg, 0, 0, 1, 2)
            self.note_lbl.setText("")
            return
        busy = QLabel("경매장에서 수수료 쿠폰 가격 확인 중…")
        busy.setStyleSheet(_GRAY)
        self.grid.addWidget(busy, 0, 0, 1, 2)
        self.note_lbl.setText("")
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

    def _clear_grid(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _card(self, row: dict, best: dict | None, kg) -> QFrame:
        is_best = best is not None and row["label"] == best["label"]
        f = QFrame()
        f.setObjectName("card")
        border = "#00C9A2" if is_best else "#3a3d44"
        f.setStyleSheet(f"#card {{ border:1px solid {border}; border-radius:8px; }}")
        cv = QVBoxLayout(f)
        cv.setContentsMargins(10, 8, 10, 8)
        cv.setSpacing(2)

        title = QLabel(("⭐ " if is_best else "") + row["label"])
        title.setStyleSheet("font-weight:800;" if is_best else "font-weight:600;")
        cv.addWidget(title)

        if not row["available"]:
            na = QLabel("쿠폰 가격 조회 안됨")
            na.setStyleSheet(_GRAY)
            cv.addWidget(na)
            return f

        per = QLabel(f"1인당 {row['per_person']:,} ({kg(row['per_person'])})")
        per.setStyleSheet(
            "font-size:14px; font-weight:700;"
            + (" color:#00C9A2;" if is_best else "")
        )
        cv.addWidget(per)

        fee_txt = f"수수료 {row['fee_after']:,}"
        if row["pct"] != 0:
            fee_txt += f" + 쿠폰 {(row['coupon_price'] or 0):,}"
        fl = QLabel(fee_txt)
        fl.setStyleSheet(_GRAY)
        cv.addWidget(fl)
        return f

    def _show(self, payload) -> None:
        result, sale, headcount, membership, note = payload
        kg = auction.korean_gold
        self._clear_grid()
        rate_txt = "멤버십 4%" if membership else "기본 5%"
        summary = QLabel(f"판매가 {sale:,} ({kg(sale)}) · {headcount}명 · {rate_txt}")
        summary.setStyleSheet("font-size:12px;")
        self.grid.addWidget(summary, 0, 0, 1, 2)
        best = result["best"]
        for i, row in enumerate(result["rows"]):
            self.grid.addWidget(self._card(row, best, kg), 1 + i // 2, i % 2)
        self.note_lbl.setText(f"※ {note}" if note else "")
