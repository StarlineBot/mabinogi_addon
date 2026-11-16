"""음악 버프 계산기 탭(편의기능, docs/music-buff-calculator-spec.md, 0.52.0 모든 사용자).

- 위쪽(고정): 곡 세 묶음(전장의 서곡·비바체·행진곡) 결과 줄 `보통 · 훌륭 · **신들린%**`. 표가 아니라 라벨.
  보너스뎀 줄은 세인트 바드 링크 개방 10단계를 켰을 때만.
- 아래(스크롤): 입력 2단. 왼쪽 2차 타이틀→악기→모자→옷→장갑→신발, 오른쪽 액세서리 1·2→에코스톤→주화·유물→기타→기타 보너스.
- 입력을 바꾸면 즉시 다시 계산(순수 계산 `market.music_buff`)하고 config `musicBuff`에 자동 저장.

런타임: 네트워크·타이머 없음. 칸 하나 바뀔 때마다 계산 1회(수십 번 곱셈)와 config 파일 쓰기 1회뿐.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..market import music_buff as mb
from .palette import color
from .widgets import FeatureHeader, checkbox, divider

TITLE = "음악 버프 계산기"
DESCRIPTION = ("전장의 서곡·비바체·행진곡 수치를 장비 구성으로 계산해요. 입력은 자동 저장돼요. "
               "수치 참고: It's 마비노기 음악 버프 계산기")
INSTRUMENT_NOTE = "스킬 7종 1랭 · 개조·등급 보너스 최대(리라 25+7, 글루미 16) · 곡별 마스터 타이틀 기준"
BOTTOM_NOTE = "곡마다 그 곡의 마스터 타이틀(+8)을 단 기준 · 보너스뎀은 세인트 바드 링크 개방 10단계 효과"
CHECK_LABELS = (("cloud_cushion", "구름방석 4단계 (+1)"), ("music_boost_potion", "음악 부스트 포션 (+2)"),
                ("rose_couple_bracelet", "로즈 커플 팔찌 (+1)"),
                ("saint_bard_arcana", "세인트 바드 링크 개방 10단계 (+3, 보너스뎀)"),
                ("grandmaster", "그랜마 음유시인 (+5)"))


def _muted(text: str = "", wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color:{color('muted')};")
    lbl.setWordWrap(wrap)
    return lbl


def _section_title(text: str) -> QLabel:
    """구역 제목 14px · 700(ui-rules — 입력 칸이 많은 계산기 예외)."""
    lbl = QLabel(text)
    lbl.setStyleSheet("font-size:14px; font-weight:700;")
    return lbl


def _with_plus(entry: dict) -> str:
    name = entry["name"]
    return name if "(+" in name else f"{name} (+{entry['buff']})"


class _Fold(QWidget):
    """칸 여러 개를 가로로 — 폭이 모자라면(글자를 키웠을 때 등) 세로로 접는다. 최소 폭 = 가장 넓은 칸."""

    def __init__(self, parts: list[QWidget], spacing: int, stretch: bool = False):
        super().__init__()
        self.parts = parts
        self._spacing = spacing
        self._box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._box.setContentsMargins(0, 0, 0, 0)
        self._box.setSpacing(spacing)
        for part in parts:
            self._box.addWidget(part, 1 if stretch else 0, Qt.AlignmentFlag.AlignTop)
        if not stretch:
            self._box.addStretch(1)

    @property
    def folded(self) -> bool:
        return self._box.direction() == QBoxLayout.Direction.TopToBottom

    def _need(self) -> int:
        return sum(p.minimumSizeHint().width() for p in self.parts) + self._spacing * (len(self.parts) - 1)

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(max(p.minimumSizeHint().width() for p in self.parts))
        return hint

    def resizeEvent(self, event):
        direction = (QBoxLayout.Direction.TopToBottom if self._need() > event.size().width()
                     else QBoxLayout.Direction.LeftToRight)
        if direction != self._box.direction():
            self._box.setDirection(direction)
        super().resizeEvent(event)


def _boxed(layout) -> QWidget:
    w = QWidget()
    layout.setContentsMargins(0, 0, 0, 0)
    w.setLayout(layout)
    return w


class _Combo(QComboBox):
    """스크롤하다 휠이 칸 값을 바꾸지 않게(포커스가 있을 때만 휠)."""

    def __init__(self, items: list[tuple[str, object]]):
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(6)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for text, data in items:
            self.addItem(text, data)

    def value(self):
        return self.currentData()

    def set_value(self, value) -> None:
        for i in range(self.count()):
            d = self.itemData(i)
            if d == value or (isinstance(d, float) and isinstance(value, (int, float)) and abs(d - value) < 1e-9):
                self.setCurrentIndex(i)
                return
        self.setCurrentIndex(0)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class _Spin(QSpinBox):
    def __init__(self, lo: int, hi: int, prefix: str = "", suffix: str = ""):
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setRange(lo, hi)
        self.setPrefix(prefix)
        self.setSuffix(suffix)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class _ReforgeLine(QWidget):
    """세공 한 줄: 옵션 드롭다운 + Lv(옵션 최대까지, 옵션 없으면 0 고정)."""

    def __init__(self, opts: list[dict], on_change):
        super().__init__()
        self._max = {o["id"]: o["max"] for o in opts}
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.option = _Combo([("없음", None)] + [(o["name"], o["id"]) for o in opts])
        self.level = _Spin(0, 0, prefix="Lv ")
        self.level.setFixedWidth(64)
        h.addWidget(self.option, 1)
        h.addWidget(self.level)
        self.option.currentIndexChanged.connect(self._limit)
        self.option.currentIndexChanged.connect(on_change)
        self.level.valueChanged.connect(on_change)

    def _limit(self) -> None:
        self.level.setMaximum(self._max.get(self.option.value(), 0))
        self.level.setEnabled(self.option.value() is not None)

    def value(self) -> list:
        return [self.option.value(), self.level.value() if self.option.value() else 0]

    def set_value(self, line) -> None:
        self.option.set_value(line[0])
        self._limit()
        self.level.setValue(line[1])


class _Section(QWidget):
    """구역: 제목 + (흐린 이름 | 입력) 줄들."""

    def __init__(self, title: str):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        v.addWidget(_section_title(title))
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(6)
        self.grid.setColumnStretch(1, 1)
        v.addLayout(self.grid)
        self._rows = 0

    def row(self, label: str, *widgets: QWidget) -> None:
        if label:
            self.grid.addWidget(QLabel(label), self._rows, 0)
        if len(widgets) == 1:
            self.grid.addWidget(widgets[0], self._rows, 1)
        else:
            box = QWidget()
            h = QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0)
            for w in widgets:
                h.addWidget(w, 1)
            self.grid.addWidget(box, self._rows, 1)
        self._rows += 1

    def note(self, text: str) -> QLabel:
        lbl = _muted(text, wrap=True)
        self.layout().addWidget(lbl)
        return lbl


class MusicBuffTab(QWidget):
    def __init__(self, tables: dict | None = None) -> None:
        super().__init__()
        self._t = tables or mb.tables()
        self._loading = True
        self.combos: dict[str, _Combo] = {}
        self.reforges: dict[str, list[_ReforgeLine]] = {}
        self.checks = {}

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.addWidget(FeatureHeader(TITLE, DESCRIPTION))
        v.addWidget(self._build_results())
        v.addWidget(divider())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(120)
        self.scroll.setWidget(self._build_inputs())
        v.addWidget(self.scroll, 1)

        self.set_state(mb.normalize(config.load_music_buff(), self._t), save=False)
        self._loading = False

    # ---- 위: 결과 ----
    def _build_results(self) -> QWidget:
        box = QWidget()
        box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        v = QVBoxLayout(box)
        v.setContentsMargins(8, 0, 8, 0)
        v.setSpacing(8)
        self.prob_label = _muted()
        self.prob_label.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.prob_label)
        columns = []
        self.value_labels: dict[tuple[str, str], QLabel] = {}
        self.name_labels: dict[tuple[str, str], QLabel] = {}
        for song, name, rows in mb.SONGS:
            col = QGridLayout()
            col.setHorizontalSpacing(12)
            col.setVerticalSpacing(4)
            head = QLabel(name)
            head.setStyleSheet("font-weight:700;")
            col.addWidget(head, 0, 0, 1, 2)
            for r, (key, label) in enumerate(rows, start=1):
                n = _muted(label)
                val = QLabel()
                val.setTextFormat(Qt.TextFormat.RichText)
                val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                col.addWidget(n, r, 0)
                col.addWidget(val, r, 1)
                self.name_labels[(song, key)] = n
                self.value_labels[(song, key)] = val
            col.setRowStretch(len(rows) + 1, 1)
            columns.append(_boxed(col))
        self.songs = _Fold(columns, 28)
        v.addWidget(self.songs)
        v.addWidget(_muted(BOTTOM_NOTE, wrap=True))
        return box

    # ---- 아래: 입력 ----
    def _combo(self, key: str, none: str = "없음") -> _Combo:
        c = _Combo([(none, None)] + [(_with_plus(e), e["id"]) for e in mb.options(key, self._t)])
        c.currentIndexChanged.connect(self._changed)
        self.combos[key] = c
        return c

    def _value_combo(self, key: str, items: list[tuple[str, object]]) -> _Combo:
        c = _Combo(items)
        c.currentIndexChanged.connect(self._changed)
        self.combos[key] = c
        return c

    def _reforge(self, sec: _Section, key: str) -> None:
        lines = [_ReforgeLine(mb.reforge_options(key, self._t), self._changed) for _ in range(mb.REFORGE_LINES[key])]
        self.reforges[key] = lines
        for i, line in enumerate(lines):
            sec.row("세공" if i == 0 else "", line)

    def _build_inputs(self) -> QWidget:
        t = self._t
        left, right = QVBoxLayout(), QVBoxLayout()
        for col in (left, right):
            col.setSpacing(18)
        # 왼쪽
        s = _Section("2차 타이틀")
        s.row("타이틀", self._combo("secondary_title"))
        left.addWidget(s)
        s = _Section("악기")
        s.row("악기", self._value_combo("instrument", [(e["name"], e["id"]) for e in t["instruments"]]))
        s.row("인챈트", self._combo("inst_prefix", "접두 없음"), self._combo("inst_suffix", "접미 없음"))
        self.special_mod = _Spin(0, len(t["special_mod_bonus"]) - 1, suffix="단계")
        self.special_mod.setFixedWidth(96)
        self.special_mod.valueChanged.connect(self._changed)
        s.row("특개", self._left(self.special_mod))
        self._reforge(s, "inst_reforge")
        s.note(INSTRUMENT_NOTE)
        left.addWidget(s)
        s = _Section("모자")
        s.row("장비", self._combo("head_equipment"))
        s.row("접미", self._combo("head_suffix", "접미 없음"))
        left.addWidget(s)
        for title, key in (("옷", "armor_prefix"), ("장갑", "gloves_prefix")):
            s = _Section(title)
            s.row("접두", self._combo(key, "접두 없음"))
            left.addWidget(s)
        s = _Section("신발")
        s.row("접두", self._combo("shoes_prefix", "접두 없음"))
        self._reforge(s, "shoes_reforge")
        left.addWidget(s)
        left.addStretch(1)
        # 오른쪽
        for n in (1, 2):
            s = _Section(f"액세서리 {n}")
            s.row("인챈트", self._combo(f"acc{n}_prefix", "접두 없음"), self._combo(f"acc{n}_suffix", "접미 없음"))
            self._reforge(s, f"acc{n}_reforge")
            right.addWidget(s)
        s = _Section("에코스톤")
        self._reforge(s, "eco_reforge")
        right.addWidget(s)
        s = _Section("주화 · 유물")
        for key, name in (("brirehe_attack", "브리 레흐의 주화"), ("tala_attack", "탈라 가흐의 주화")):
            items = [("없음", 0)] + [(f"공격력 +{v:g}%", v) for v in t[f"{key}_options"] if v]
            s.row(name, self._value_combo(key, items))
        s.row("무리아스의 유물",
              self._value_combo("relic_prefix_count", [(e["label"], e["count"]) for e in t["relic_prefix_count_options"]]),
              self._value_combo("relic_suffix_count", [(e["label"], e["count"]) for e in t["relic_suffix_count_options"]]))
        right.addWidget(s)
        s = _Section("기타")
        s.row("엑스트라 미니어처", self._combo("extra_miniature"))
        s.row("일반 미니어처", self._combo("normal_miniature"))
        s.row("나팔", self._combo("horn"))
        s.row("인형 가방", self._combo("doll_bag"))
        s.row("무리아스의 성수",
              self._value_combo("murias_holy_water", [("미사용", 0)] + [(f"+{v}", v) for v in t["murias_holy_water"] if v]))
        s.row("펫", self._value_combo("pet", [(_pet_name(e), e["id"]) for e in t["pets"]]))
        right.addWidget(s)
        s = _Section("기타 보너스")
        for key, text in CHECK_LABELS:
            cb = checkbox(text)
            cb.toggled.connect(self._changed)
            self.checks[key] = cb
            s.layout().addWidget(cb)
        right.addWidget(s)
        right.addStretch(1)
        self.columns = _Fold([_boxed(left), _boxed(right)], 24, stretch=True)
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 4, 4, 8)
        outer.addWidget(self.columns)
        return page

    @staticmethod
    def _left(widget: QWidget) -> QWidget:
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(widget)
        h.addStretch(1)
        return box

    # ---- 상태 ----
    def state(self) -> dict:
        s = {key: c.value() for key, c in self.combos.items()}
        s.update({key: [line.value() for line in lines] for key, lines in self.reforges.items()})
        s.update({key: cb.isChecked() for key, cb in self.checks.items()})
        s["special_mod"] = self.special_mod.value()
        return s

    def set_state(self, s: dict, *, save: bool = True) -> None:
        loading, self._loading = self._loading, True
        for key, c in self.combos.items():
            c.set_value(s.get(key))
        for key, lines in self.reforges.items():
            for line, val in zip(lines, s.get(key, [])):
                line.set_value(val)
        for key, cb in self.checks.items():
            cb.setChecked(bool(s.get(key)))
        self.special_mod.setValue(s.get("special_mod", 0))
        self._loading = loading
        self._recalc(save=save)

    def _changed(self, *_args) -> None:
        if not self._loading:
            self._recalc(save=True)

    def _recalc(self, *, save: bool) -> None:
        s = self.state()
        if save:
            config.save_music_buff(s)
        r = mb.calc(s, self._t)
        p = r["prob"]
        self.prob_label.setText(f"값은 보통 · 훌륭 · <b>신들린</b> 순 · 확률 {p['normal']:.1f}% · "
                                f"{p['excellent']:.1f}% · {p['divine']:.1f}%")
        saint = bool(s.get("saint_bard_arcana"))
        for song, _name, rows in mb.SONGS:
            for key, _label in rows:
                vals = [r[song][q][key] for q in mb.QUALITIES]
                show = key != "bonus_damage" or saint
                self.name_labels[(song, key)].setVisible(show)
                self.value_labels[(song, key)].setVisible(show)
                if show:
                    self.value_labels[(song, key)].setText(
                        f"{mb.fmt(vals[0])} · {mb.fmt(vals[1])} · <b>{mb.fmt(vals[2])}%</b>")


def _pet_name(e: dict) -> str:
    return e["name"] if not e["baseBuff"] else f"{e['name']} (+{e['baseBuff']})"
