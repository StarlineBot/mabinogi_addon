"""구슬 분배 계산기 탭 (편의기능).

던전(브리레흐/탈라가흐)에서 먹은 구슬 갯수와 구슬금액·분배 인원을 넣으면 1인당
분배금을 바로 계산해 준다. 구슬은 1개 = 2개로 친다(x2) — '총' 칸에 x2 적용한 총
구슬 갯수가 자동으로 뜨고, 아래 테두리 카드에 1인당 금액이 크게 나온다.

- 브리레흐: 1관·2관·3관 세 칸
- 탈라가흐: 한 칸
계산은 순수 함수(bead_split)라 맥에서도 테스트 가능하고, 입력하면 즉시 갱신된다.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import bead_split
from ..market.auction import korean_gold
from .widgets import SuffixSpinBox, hint_label

_GRAY = "color:#9aa0aa; font-size:12px;"
_ACCENT = "#00C9A2"


def _spin(maximum: int, width: int = 90, suffix: str = "") -> QSpinBox:
    s = SuffixSpinBox()
    s.setRange(0, maximum)
    s.setGroupSeparatorShown(True)
    if suffix:
        s.setSuffix(suffix)
    s.setMinimumWidth(width)
    return s


class BeadSplitTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        v.addWidget(
            hint_label(
                "구슬 개수·개당 가격·인원을 입력하면 1인당 분배금을 계산합니다."
            )
        )

        # 던전 선택(브리레흐 / 탈라가흐)
        mode_row = QHBoxLayout()
        lbl = QLabel("던전")
        lbl.setStyleSheet(_GRAY)
        mode_row.addWidget(lbl)
        self.mode_brireh = QRadioButton("브리레흐")
        self.mode_talagah = QRadioButton("탈라가흐")
        self.mode_brireh.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.mode_brireh)
        grp.addButton(self.mode_talagah)
        mode_row.addWidget(self.mode_brireh)
        mode_row.addWidget(self.mode_talagah)
        mode_row.addStretch(1)
        v.addLayout(mode_row)

        # 구슬금액 · 분배 인원
        top = QHBoxLayout()
        top.addWidget(QLabel("구슬 1개 가격"))
        self.price_spin = _spin(99_999_999, width=140, suffix=" 만")
        top.addWidget(self.price_spin)
        top.addSpacing(18)
        top.addWidget(QLabel("분배 인원"))
        self.people_spin = QSpinBox()
        self.people_spin.setRange(1, 40)
        self.people_spin.setValue(1)
        self.people_spin.setMinimumWidth(70)
        top.addWidget(self.people_spin)
        top.addStretch(1)
        v.addLayout(top)

        # 브리레흐 입력(1관/2관/3관)
        self.brireh_box = QWidget()
        br = QHBoxLayout(self.brireh_box)
        br.setContentsMargins(0, 0, 0, 0)
        br.addWidget(QLabel("1관"))
        self.gwan1 = _spin(999, width=70)
        br.addWidget(self.gwan1)
        br.addWidget(QLabel("2관"))
        self.gwan2 = _spin(999, width=70)
        br.addWidget(self.gwan2)
        br.addWidget(QLabel("3관"))
        self.gwan3 = _spin(999, width=70)
        br.addWidget(self.gwan3)
        br.addStretch(1)
        v.addWidget(self.brireh_box)

        # 탈라가흐 입력(한 칸)
        self.talagah_box = QWidget()
        ta = QHBoxLayout(self.talagah_box)
        ta.setContentsMargins(0, 0, 0, 0)
        ta.addWidget(QLabel("탈라가흐"))
        self.gwan_tala = _spin(999, width=70)
        ta.addWidget(self.gwan_tala)
        ta.addStretch(1)
        v.addWidget(self.talagah_box)

        # 입력 칸 바로 아래 안내(상단 설명을 안 읽는 사람 대비)
        note = hint_label("등장한 개수를 입력하세요. 계산에는 2배가 반영됩니다.")
        note.setStyleSheet(_GRAY)
        v.addWidget(note)

        # 결과 카드(테두리, 강조): 총 구슬 갯수(자동) + 1인당 분배금
        self.result_card = QFrame()
        self.result_card.setObjectName("card")
        self.result_card.setStyleSheet(
            f"#card {{ border:1px solid {_ACCENT}; border-radius:8px; }}"
        )
        cv = QVBoxLayout(self.result_card)
        cv.setContentsMargins(12, 10, 12, 10)
        cv.setSpacing(2)
        self.result_total = QLabel()
        self.result_total.setStyleSheet("font-size:13px; font-weight:600;")
        cv.addWidget(self.result_total)
        self.result_main = QLabel()
        self.result_main.setStyleSheet(
            f"font-size:16px; font-weight:800; color:{_ACCENT};"
        )
        cv.addWidget(self.result_main)
        self.result_sub = QLabel()
        self.result_sub.setStyleSheet(_GRAY)
        self.result_sub.setWordWrap(True)
        cv.addWidget(self.result_sub)
        v.addWidget(self.result_card)
        v.addStretch(1)

        # 입력하면 즉시 갱신
        for w in (
            self.price_spin,
            self.people_spin,
            self.gwan1,
            self.gwan2,
            self.gwan3,
            self.gwan_tala,
        ):
            w.valueChanged.connect(self._recalc)
        self.mode_brireh.toggled.connect(self._on_mode)
        self._on_mode()

    def _on_mode(self) -> None:
        brireh = self.mode_brireh.isChecked()
        self.brireh_box.setVisible(brireh)
        self.talagah_box.setVisible(not brireh)
        self._recalc()

    def _counts(self) -> list[int]:
        if self.mode_brireh.isChecked():
            return [self.gwan1.value(), self.gwan2.value(), self.gwan3.value()]
        return [self.gwan_tala.value()]

    def _recalc(self) -> None:
        total = bead_split.total_beads(self._counts())
        price_man = self.price_spin.value()
        price = price_man * 10000  # 만 단위 입력 → 실제 금액(원)
        people = self.people_spin.value()
        self.result_total.setText(f"계산에 반영한 구슬 {total}개")
        each = bead_split.per_person(total, price, people)
        if each <= 0:
            self.result_main.setText("1인당 —")
            self.result_sub.setText("구슬금액·갯수·인원을 넣어 주세요.")
            return
        self.result_main.setText(f"1인당 {each:,} ({korean_gold(each)})")
        self.result_sub.setText(
            f"구슬금액 {price_man:,}만 × 총 {total}개 ÷ {people}명"
        )
