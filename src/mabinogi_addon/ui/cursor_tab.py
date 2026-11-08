"""편의기능 › 마우스 커서 화면(마우스 커서 명세 2절).

설정을 바꾸면 바로 저장하고 오버레이(CursorFx)에 반영한다. 미리보기는 같은 그리기 함수로 정해진 길을 따라
움직이는 예시를 보여준다(화면이 보일 때만 움직인다).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFrame, QGroupBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)

from ..cursor_fx import DEFAULT_COLOR, PARTICLE_KINDS, PRESET_COLORS, Particles, SHAPES, TAIL_SECONDS, TAILS, Trail, ring_color, shake_scale, sparkle_multicolor, tail_color
from .cursor_paint import paint_particles, paint_ring, paint_scope, paint_tail
from .help_dialog import help_button
from .palette import color
from .widgets import FeatureHeader, SuffixSpinBox, hint_label, switch

SHAPE_TEXT = dict(zip(SHAPES, ("없음", "원", "스코프(짧은 십자)", "스코프(화면 선)")))
TAIL_TEXT = dict(zip(TAILS, ("없음", "점", "선", "무지개 선", "반짝이", "불꽃")))
LENGTH_TEXT = {"short": "짧게", "normal": "보통", "long": "길게"}
COLOR_NAMES = dict(zip(PRESET_COLORS, ("민트", "노랑", "빨강", "흰색", "보라")))

HELP_HTML = """
<p><b>마우스 커서 표시</b>는 전투 중 커서를 놓치지 않게 커서 둘레에 모양이나 꼬리를 그려요.</p>
<ul>
<li><b>모양</b>과 <b>꼬리</b>는 따로 골라요. 둘 다 고르면 함께 보여요.</li>
<li><b>흔들어 찾기</b>: 마우스를 빠르게 좌우로 흔들면 원이 잠깐 크게 커졌다가 돌아와요. 모양이 '없음'이어도 흔들 때만 보여요.</li>
<li>클릭은 그대로 게임으로 통과해요. 위치 잠금은 없어요.</li>
<li>게임이 앞에 있을 때만 보이고, 전투 보조를 일시정지하면 숨겨요.</li>
<li>커서 위치는 읽기만 해요. 마우스를 움직이거나 누르지 않아요.</li>
</ul>
"""


def _segment_qss() -> str:
    return (
        "QPushButton { border:1px solid palette(mid); padding:5px 12px; border-radius:0px; }"
        f"QPushButton:checked {{ background:{color('accent')}; color:{color('on-accent')};"
        f" border-color:{color('accent')}; font-weight:700; }}"
    )


class _Segments(QWidget):
    """붙어 있는 선택 버튼 묶음(하나만 선택)."""

    changed = Signal(str)

    def __init__(self, items: dict[str, str]) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        for key, text in items.items():
            b = QPushButton(text)
            b.setCheckable(True)
            b.setStyleSheet(_segment_qss())
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.group.addButton(b)
            self.buttons[key] = b
            row.addWidget(b)
        row.addStretch(1)

    def set_value(self, key: str) -> None:
        self.buttons[key].setChecked(True)


class _Swatch(QPushButton):
    def __init__(self, hex_color: str) -> None:
        super().__init__()
        self.hex = hex_color
        self.setFixedSize(26, 26)
        self.setCheckable(True)
        self.setToolTip(COLOR_NAMES.get(hex_color, hex_color))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style(False)

    def _style(self, on: bool) -> None:
        ring = f"3px solid {color('accent')}" if on else "1px solid palette(mid)"
        fill = self.hex
        if not self.isEnabled():  # 흐려진 줄(원 색·꼬리 색): 견본도 옅게 — 저장 색 표시는 그대로
            c = QColor(self.hex)
            fill = f"rgba({c.red()},{c.green()},{c.blue()},90)"
            ring = "3px solid palette(mid)" if on else "1px solid palette(midlight)"
        self.setStyleSheet(f"QPushButton {{ background:{fill}; border:{ring}; border-radius:13px; }}")

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange:
            self._style(self.isChecked())

    def set_on(self, on: bool) -> None:
        self.setChecked(on)
        self._style(on)


class CursorPreview(QWidget):
    """설정 미리보기: 정해진 길(8자)을 따라 움직이는 커서와 효과."""

    def __init__(self, tab: "CursorTab") -> None:
        super().__init__()
        self._tab = tab
        self.setFixedSize(300, 120)
        self._t = 0.0
        self._trail = Trail()
        self._particles = {k: Particles(k, seed=7) for k in PARTICLE_KINDS}  # 미리보기는 고정 시드
        self._timer = QTimer(self)
        self._timer.setInterval(33)  # 미리보기는 초당 30번이면 충분
        self._timer.timeout.connect(self._advance)
        self._shake_at = -10.0

    def _path(self, t: float) -> QPointF:
        return QPointF(150 + 115 * math.sin(t * 3.4), 60 + 34 * math.sin(t * 6.8))  # 실제 손놀림처럼 빠르게(꼬리가 보이게)

    def _advance(self) -> None:
        self._t += 0.033
        p = self._path(self._t)
        self._trail.add(self._t, p.x(), p.y())
        kind = self._tab.settings["tail"]
        if kind in self._particles:
            self._particles[kind].spawn(self._t, p.x(), p.y())
        if self._tab.settings["shake"] and int(self._t * 10) % 60 == 0:
            self._shake_at = self._t  # 6초마다 흔들기 예시
        self.update()

    def set_time(self, t: float) -> None:
        """렌더·테스트용: t초까지 진행한 모습."""
        self._trail.clear()
        for parts in self._particles.values():
            parts.clear()
        step = 0.016
        k = max(0.0, t - 0.9)
        while k <= t:
            p = self._path(k)
            self._trail.add(k, p.x(), p.y())
            for parts in self._particles.values():
                parts.spawn(k, p.x(), p.y())
            k += step
        self._t = t
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def paintEvent(self, _event):
        s = self._tab.settings
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#3b4a3c"))  # 풀밭 같은 어두운 초록 바탕
        opacity = s["opacity"] / 100
        pos = self._path(self._t)
        points = self._trail.points(self._t, TAIL_SECONDS[s["tailLength"]])
        ring, tail = ring_color(s), tail_color(s)  # 오버레이와 같은 분리 규칙(cursor_fx)
        if s["tail"] in self._particles:
            paint_particles(p, self._particles[s["tail"]].alive(self._t), s["tail"], tail, opacity,
                            multicolor=sparkle_multicolor(s))
        else:
            paint_tail(p, points, s["tail"], tail, s["size"], opacity, multicolor=sparkle_multicolor(s))
        scale = shake_scale(self._t - self._shake_at) if s["shake"] else 1.0
        if s["shape"] == "lines":
            c = QColor(ring)
            c.setAlphaF(opacity * 0.8)
            p.fillRect(0, int(pos.y()), self.width(), 1, c)
            p.fillRect(int(pos.x()), 0, 1, self.height(), c)
        if s["shape"] == "scope" and scale <= 1.0:
            paint_scope(p, pos, s["size"], ring, opacity)
        elif s["shape"] == "ring" or scale > 1.0:
            paint_ring(p, pos, s["size"] * scale, ring, opacity)
        # 커서 화살표(간단한 모양)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor("black"))
        p.setBrush(QColor("white"))
        x, y = pos.x(), pos.y()
        from PySide6.QtGui import QPolygonF
        p.drawPolygon(QPolygonF([QPointF(x, y), QPointF(x, y + 16), QPointF(x + 4.5, y + 12),
                                 QPointF(x + 8, y + 18), QPointF(x + 10.5, y + 17), QPointF(x + 7, y + 11),
                                 QPointF(x + 12, y + 11)]))
        p.end()


class CursorTab(QWidget):
    """설정 화면. fx(CursorFx)에 바로 반영한다."""

    enabled_changed = Signal(bool)

    def __init__(self, fx) -> None:
        super().__init__()
        self.fx = fx
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        v.addWidget(FeatureHeader(
            "마우스 커서 표시",
            "전투 중 커서를 놓치지 않게 커서 둘레에 모양이나 꼬리를 그려요. 클릭은 그대로 통과해요.",
            help_button("마우스 커서 표시 사용법", HELP_HTML, self)))

        box = QGroupBox("표시")
        g = QVBoxLayout(box)
        g.setSpacing(10)
        top = QHBoxLayout()
        self.switch = switch("커서 표시")
        self.switch.toggled.connect(self._on_switch)
        top.addWidget(self.switch)
        top.addSpacing(10)
        self.status = QLabel()
        self.status.setWordWrap(True)
        top.addWidget(self.status, 1)
        g.addLayout(top)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self.shape = _Segments(SHAPE_TEXT)
        self.shape.changed.connect(lambda k: self._change(shape=k))
        grid.addWidget(QLabel("모양"), 0, 0)
        grid.addWidget(self.shape, 0, 1)
        self.tail = _Segments(TAIL_TEXT)
        self.tail.changed.connect(lambda k: self._change(tail=k))
        grid.addWidget(QLabel("꼬리"), 1, 0)
        grid.addWidget(self.tail, 1, 1)
        self.shake = QCheckBox("흔들어 찾기 — 마우스를 빠르게 좌우로 흔들면 원이 잠깐 커져요")
        self.shake.toggled.connect(lambda on: self._change(shake=bool(on)))
        grid.addWidget(self.shake, 2, 1)

        sizes = QHBoxLayout()
        sizes.setSpacing(8)
        self.size = SuffixSpinBox()
        self.size.setRange(20, 120)
        self.size.setSuffix(" px")
        self.size.setSingleStep(5)
        self.size.valueChanged.connect(lambda n: self._change(size=n))
        sizes.addWidget(self.size)
        sizes.addSpacing(14)
        sizes.addWidget(QLabel("꼬리 길이"))
        self.length = _Segments(LENGTH_TEXT)
        self.length.layout().takeAt(self.length.layout().count() - 1)  # 끝 여백 빼기(한 줄에 붙여 놓으려고)
        self.length.changed.connect(lambda k: self._change(tailLength=k))
        sizes.addWidget(self.length)
        sizes.addSpacing(14)
        sizes.addWidget(QLabel("불투명도"))
        self.opacity = SuffixSpinBox()
        self.opacity.setRange(20, 100)
        self.opacity.setSingleStep(10)
        self.opacity.setSuffix(" %")
        self.opacity.valueChanged.connect(lambda n: self._change(opacity=n))
        sizes.addWidget(self.opacity)
        sizes.addStretch(1)
        grid.addWidget(QLabel("원 크기"), 3, 0)
        grid.addLayout(sizes, 3, 1)

        # 확정 배치(A안, 사용자 결정 11-07): 모양 묶음 → 구분선 → 원 색 → 꼬리 색 → 미리보기.
        # 두 줄은 같은 격자 칸이라 견본 5개·'+'·'기본 색'이 같은 세로줄에 온다.
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        grid.addWidget(line, 4, 0, 1, 2)
        self.ring_row = _ColorRow("원 색", "원 색상", self)
        self.tail_row = _ColorRow("꼬리 색", "꼬리 색상", self)
        for r, row in ((5, self.ring_row), (6, self.tail_row)):
            grid.addWidget(row.label, r, 0)
            grid.addLayout(row.row, r, 1)
            row.chosen.connect(lambda hex_color, k=row.key: self._choose_color(k, hex_color))

        self.preview = CursorPreview(self)
        grid.addWidget(QLabel("미리보기"), 7, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self.preview, 7, 1, Qt.AlignmentFlag.AlignLeft)
        g.addLayout(grid)
        g.addWidget(hint_label("일시정지 중이거나 게임이 뒤에 있을 때는 숨겨요."))
        v.addWidget(box)
        v.addStretch(1)
        for w in (self.shape, self.tail):
            w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._loading = False
        self.load()

    @property
    def settings(self) -> dict:
        return self.fx.settings

    def load(self) -> None:
        """저장된 설정을 화면에 (신호 없이) 채운다."""
        s = self.settings
        self._loading = True
        try:
            self.switch.setChecked(s["enabled"])
            self.shape.set_value(s["shape"])
            self.tail.set_value(s["tail"])
            self.shake.setChecked(s["shake"])
            self.size.setValue(s["size"])
            self.length.set_value(s["tailLength"])
            self.opacity.setValue(s["opacity"])
        finally:
            self._loading = False
        self._refresh()

    def _refresh(self) -> None:
        s = self.settings
        self.ring_row.show_value(ring_color(s), "" if s["shape"] != "none" or s["shake"]
                                 else "모양과 흔들어 찾기가 꺼져 있어요.")
        self.tail_row.show_value(tail_color(s), "꼬리가 꺼져 있어요." if s["tail"] == "none"
                                 else "무지개 선은 고유 색을 사용해요." if s["tail"] == "rainbow" else "")
        palette = {"sparkle": "노랑(기본): 여러 색 반짝이", "fire": "노랑(기본): 기본 불꽃색"}.get(s["tail"], "")
        self.tail_row.set_default_hint(palette)
        self.size.setEnabled(s["shape"] in ("ring", "scope") or s["shake"] or s["tail"] != "none")
        self.length.setEnabled(s["tail"] != "none")
        on = s["enabled"]
        dot = color("ok") if on else color("muted")
        self.status.setText(f"<span style='color:{dot}'>● {'켜짐 — 게임이 앞에 있을 때 보여요' if on else '꺼짐'}</span>")
        self.preview.update()

    def _on_switch(self, on: bool) -> None:
        if self._loading:
            return
        self._change(enabled=bool(on))
        self.enabled_changed.emit(bool(on))

    def set_enabled(self, on: bool) -> None:
        """홈 스위치에서 켜기·끄기(같은 값)."""
        if self.switch.isChecked() != bool(on):
            self.switch.setChecked(bool(on))

    def _change(self, **changes) -> None:
        if self._loading:
            return
        self.fx.update_settings(**changes)
        self._refresh()

    def _pick_color(self, key: str) -> None:
        """'+': 기존 색 선택 창(제목 '원 색상'/'꼬리 색상'). 적용을 눌러야 저장·반영, 취소·닫기·Esc는 그대로."""
        from .theme_panel import ColorPickerDialog

        row = self.ring_row if key == "ring" else self.tail_row
        current = ring_color(self.settings) if key == "ring" else tail_color(self.settings)
        dlg = ColorPickerDialog(row.dialog_title, current, self)
        if dlg.exec() == ColorPickerDialog.DialogCode.Accepted:
            self._choose_color(key, dlg.value())

    def _choose_color(self, key: str, hex_color: str) -> None:
        """그 줄만 바꾼다. 꼬리: 노랑(기본)을 고르면 기본 팔레트(tailColorChosen=False — 반짝이 여러 색·기본 불꽃색, 0.38.1),
        다른 색은 고른 색. 원: 색만(꼬리 팔레트에 영향 없음)."""
        if key == "ring":
            self._change(ringColor=hex_color)
        else:
            self._change(tailColor=hex_color, tailColorChosen=hex_color.upper() != DEFAULT_COLOR)


class _ColorRow(QObject):
    """원 색·꼬리 색 한 줄: 견본 5개 · '+' · '기본 색' · (흐려질 때) 이유 한 줄."""

    chosen = Signal(str)

    def __init__(self, label: str, dialog_title: str, tab: "CursorTab") -> None:
        super().__init__(tab)  # 신호용 객체 — 화면에는 label·row(가로 묶음)만 격자에 놓인다
        self.key = "ring" if label == "원 색" else "tail"
        self.dialog_title = dialog_title
        self.label = QLabel(label)
        self.row = QHBoxLayout()
        self.row.setSpacing(8)
        self.swatches: list[_Swatch] = []
        for hex_color in PRESET_COLORS:
            sw = _Swatch(hex_color)
            sw.clicked.connect(lambda _=False, h=hex_color: self.chosen.emit(h))
            self.swatches.append(sw)
            self.row.addWidget(sw)
        self.custom = QPushButton("+")
        self.custom.setFixedSize(26, 26)
        self.custom.setToolTip(f"{dialog_title} 직접 고르기")
        self.custom.clicked.connect(lambda: tab._pick_color(self.key))
        self.row.addWidget(self.custom)
        self.row.addSpacing(8)
        self.default = QPushButton("기본 색")
        self.default.setFixedWidth(80)
        self.default.clicked.connect(lambda: self.chosen.emit(DEFAULT_COLOR))
        self.row.addWidget(self.default)
        self.row.addSpacing(8)
        self.note = hint_label("")
        self.row.addWidget(self.note, 1)
        self._base_tip = "노랑으로 되돌려요"

    def show_value(self, hex_color: str, disabled_reason: str) -> None:
        """고른 색 표시 + 흐림(저장 색은 그대로, 이유는 줄 오른쪽에 한 줄)."""
        for sw in self.swatches:
            sw.set_on(sw.hex == hex_color)
        custom = hex_color not in PRESET_COLORS
        self.custom.setStyleSheet(
            f"QPushButton {{ background:{hex_color}; border:3px solid {color('accent')}; border-radius:5px; }}"
            if custom else "")
        on = not disabled_reason
        for w in (self.label, *self.swatches, self.custom, self.default):
            w.setEnabled(on)
        self.note.setText(disabled_reason)

    def set_default_hint(self, hint: str) -> None:
        """반짝이·불꽃: 노랑(기본) 견본·'기본 색'의 뜻(기본 팔레트)을 말풍선으로 — 오른쪽 안내 문구는 흐릴 때만."""
        tip = hint or self._base_tip
        self.default.setToolTip(tip)
        self.swatches[PRESET_COLORS.index(DEFAULT_COLOR)].setToolTip(f"노랑 — {hint}" if hint else "노랑")
