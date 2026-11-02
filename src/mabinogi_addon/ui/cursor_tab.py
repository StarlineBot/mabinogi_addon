"""편의기능 › 마우스 커서 화면(마우스 커서 명세 2절).

설정을 바꾸면 바로 저장하고 오버레이(CursorFx)에 반영한다. 미리보기는 같은 그리기 함수로 정해진 길을 따라
움직이는 예시를 보여준다(화면이 보일 때만 움직인다).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QGroupBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)

from ..cursor_fx import DEFAULTS, PARTICLE_KINDS, PRESET_COLORS, Particles, SHAPES, TAIL_SECONDS, TAILS, Trail, shake_scale, sparkle_multicolor
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
        self.setStyleSheet(f"QPushButton {{ background:{self.hex}; border:{ring}; border-radius:13px; }}")

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
        if s["tail"] in self._particles:
            paint_particles(p, self._particles[s["tail"]].alive(self._t), s["tail"], s["color"], opacity,
                            multicolor=sparkle_multicolor(s))
        else:
            paint_tail(p, points, s["tail"], s["color"], s["size"], opacity, multicolor=sparkle_multicolor(s))
        scale = shake_scale(self._t - self._shake_at) if s["shake"] else 1.0
        if s["shape"] == "lines":
            c = QColor(s["color"])
            c.setAlphaF(opacity * 0.8)
            p.fillRect(0, int(pos.y()), self.width(), 1, c)
            p.fillRect(int(pos.x()), 0, 1, self.height(), c)
        if s["shape"] == "scope" and scale <= 1.0:
            paint_scope(p, pos, s["size"], s["color"], opacity)
        elif s["shape"] == "ring" or scale > 1.0:
            paint_ring(p, pos, s["size"] * scale, s["color"], opacity)
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

        colors = QHBoxLayout()
        colors.setSpacing(8)
        self.swatches: list[_Swatch] = []
        for hex_color in PRESET_COLORS:
            sw = _Swatch(hex_color)
            sw.clicked.connect(lambda _=False, h=hex_color: self._choose_color(h))
            self.swatches.append(sw)
            colors.addWidget(sw)
        self.custom_color = QPushButton("+")
        self.custom_color.setFixedSize(26, 26)
        self.custom_color.setToolTip("색 직접 고르기")
        self.custom_color.clicked.connect(self._pick_color)
        colors.addWidget(self.custom_color)
        self.color_note = hint_label("")
        colors.addWidget(self.color_note, 1)
        grid.addWidget(QLabel("색"), 3, 0)
        grid.addLayout(colors, 3, 1)

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
        grid.addWidget(QLabel("원 크기"), 4, 0)
        grid.addLayout(sizes, 4, 1)

        self.preview = CursorPreview(self)
        grid.addWidget(QLabel("미리보기"), 5, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self.preview, 5, 1, Qt.AlignmentFlag.AlignLeft)
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
        for sw in self.swatches:
            sw.set_on(sw.hex == s["color"])
        custom = s["color"] not in PRESET_COLORS
        self.custom_color.setStyleSheet(
            f"QPushButton {{ background:{s['color']}; border:3px solid {color('accent')}; border-radius:5px; }}"
            if custom else "")
        self.color_note.setText("무지개 선은 색 설정을 쓰지 않아요." if s["tail"] == "rainbow"
                                else "노랑(기본)을 고르면 반짝이는 여러 색, 불꽃은 기본 불꽃색으로 보여요."
                                if s["tail"] in ("sparkle", "fire") else "")
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

    def _pick_color(self) -> None:
        from .theme_panel import ColorPickerDialog

        dlg = ColorPickerDialog("커서 색", self.settings["color"], self)
        if dlg.exec() == ColorPickerDialog.DialogCode.Accepted:
            self._choose_color(dlg.value())

    def _choose_color(self, hex_color: str) -> None:
        """0.38.1: 기본색(노랑)을 고르면 기본 상태(colorChosen=False — 반짝이 여러 색·기본 불꽃색)로 되돌린다.
        다른 색(견본·직접 고르기 모두)은 고른 색. 예전엔 한 번 고르면 기본으로 돌아갈 길이 없었다."""
        chosen = hex_color.upper() != DEFAULTS["color"].upper()
        self._change(color=hex_color, colorChosen=chosen)
