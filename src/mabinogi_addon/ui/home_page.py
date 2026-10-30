"""홈 화면(탐색 구조 명세 12절, 0.28.0). 잘 돌고 있는지 확인하고 켜고 끄는 곳.

화면만 담당한다: 메인 창이 0.7초 상태 타이머에서 만든 상태(dict)를 update_state로 넘기면 그대로 그리고,
누름·스위치는 신호로 돌려준다. 새 캡처·판독은 하지 않고, 판독 값(숫자)은 보여주지 않는다(오독 노출 방지).
앱 테마와 관계없이 어두운 남색 디자인을 쓴다(명세 12.4). 아이콘·스위치는 이모지 대신 직접 그린다.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from .. import paths
from .palette import color
from .status_icon import paint_icon

# 홈 디자인 색. 기본은 테마와 관계없이 어두운 남색 디자인(명세 12.4), 색 이름(명세 14.6)은 다크 값.
# 테마 개인화 중에는 배경 = 틀(고른 색 그대로, 아래로 살짝 어둡게), 카드 = 내용 칸(테마 개인화 명세 5·6절).
DEFAULT_DESIGN = {
    "bg_top": "#111827", "bg_bottom": "#0b1220", "box": "#18202c", "border": "#2a3443",
    "text": "#e5e7eb", "title": "#ffffff", "sub": color("muted", dark=True),
    "accent": color("accent", dark=True), "ok": color("ok", dark=True), "muted": color("muted", dark=True),
    "warn": color("warn", dark=True), "danger": color("danger", dark=True),
    # 경고 상자: 주의 색 계열(탭의 '영역 지정 필요'와 같은 주황, 예전 노랑 폐지)
    "warn_bg": "#2b1c10", "warn_border": "#8a4a14", "warn_line": "#5a3416", "warn_text": "#f3b37a", "warn_sub": "#e2c7ae",
    "menu_bg": "#141c28", "menu_border": "#2f5d5a", "track": "#3a4556", "handle": "#3a4556", "handle_hover": "#4b5768",
}
_D = dict(DEFAULT_DESIGN)
KIND_COLORS = {"ok": _D["ok"], "muted": _D["muted"], "warn": _D["warn"]}
TEXT = DEFAULT_DESIGN["text"]


def design(custom: dict | None) -> dict:
    """홈 색 표. custom = theme_colors.compute 결과(개인화 중) 또는 None(기본 남색 디자인)."""
    if custom is None:
        return dict(DEFAULT_DESIGN)
    from ..theme_colors import mix
    roles, names = custom["roles"], custom["names"]
    box = roles["window"]
    return {
        "bg_top": custom["frame"], "bg_bottom": custom["frame_bottom"], "box": box, "border": roles["mid"],
        "text": roles["text"], "title": roles["text"], "sub": names["muted"],
        "accent": names["accent"], "ok": names["ok"], "muted": names["muted"], "warn": names["warn"], "danger": names["danger"],
        "warn_bg": mix(names["warn"], box, 0.12), "warn_border": mix(names["warn"], box, 0.55),
        "warn_line": mix(names["warn"], box, 0.28), "warn_text": names["warn"], "warn_sub": roles["text"],
        "menu_bg": box, "menu_border": roles["mid"], "track": roles["mid"], "handle": roles["mid"], "handle_hover": roles["dark"],
    }


# 전투 보조 2열 10줄(명세 12.2): (키, 이름, 스위치 있음)
COMBAT_ROWS = (("buff", "버프", False), ("debuff", "디버프", False),
               ("boss", "보스 패턴 알림", False), ("halo", "1분 헤일로", False),
               ("stat_bars", "체력바", True), ("dorcha", "도르카 표시", True),
               ("tuarim", "투아림 알림", True), ("custom", "커스텀 오버레이", True),
               ("skillbar", "단축바", False), ("memo", "메모", False))
# 아래 한 줄 3칸(중요도·자주 보는 순): (묶음 제목, [(키, 이름, 스위치 있음)])
BOTTOM_BOXES = (("최적화", (("opt", "게임 최적화", True), ("fps", "FPS 표시", True))),
                ("블랙박스", (("blackbox", "최근 영상 보관", True),)),
                ("파티 모집", (("keywords", "키워드 알림", False),)))
TITLES = {"running": ("마비노기 실행 중 · 화면을 읽고 있어요", "ok"),
          "waiting": ("마비노기를 기다리는 중", "waiting"),
          "paused": ("전투 보조 일시정지", "inactive")}


class Switch(QAbstractButton):
    """직접 그린 둥근 스위치(켜짐 민트, 꺼짐 회색)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def sizeHint(self):
        return QSize(40, 22)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        track = QColor(_D["accent"] if on else _D["track"])
        if not self.isEnabled():
            track.setAlpha(110)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(21 if on else 3, 3, 16, 16))
        p.end()


class StateIcon(QLabel):
    """상태 카드 왼쪽 원형 아이콘(상태 아이콘 B안 계열: 체크·모래시계·일시정지)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(38, 38)
        self.kind = None

    def set_kind(self, kind):
        if kind == self.kind:
            return
        self.kind = kind
        color = {"ok": _D["accent"], "waiting": _D["sub"], "inactive": _D["danger"]}[kind]  # 일시정지 = 위험 색(상단 '● 전투 보조: 일시정지'와 같음)
        pixmap = QPixmap(76, 76)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(2)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        fill = QColor(color)
        fill.setAlpha(46)
        p.setBrush(fill)
        p.drawEllipse(QRectF(0, 0, 38, 38))
        if kind == "ok":  # 원 안에 굵은 체크만(원 테두리 아이콘 대신)
            pen = QPen(QColor(color), 2.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            path = QPainterPath(QPointF(12, 19.5))
            path.lineTo(17, 24.5)
            path.lineTo(26.5, 14)
            p.drawPath(path)
        else:
            p.drawPixmap(QRectF(9, 9, 20, 20), paint_icon(kind, color, size=20), QRectF(0, 0, 40, 40))
        p.end()
        self.setPixmap(pixmap)


def house_icon(color: str = TEXT, size: int = 14) -> QPixmap:
    """상태 줄 '홈' 버튼의 집 모양(이모지 금지 — 직접 그림)."""
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(2)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.5)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    s = float(size)
    roof = QPainterPath(QPointF(1.5, s * 0.5))
    roof.lineTo(s / 2, 1.8)
    roof.lineTo(s - 1.5, s * 0.5)
    p.drawPath(roof)
    p.drawRect(QRectF(s * 0.22, s * 0.45, s * 0.56, s * 0.45))
    p.drawLine(QPointF(s / 2, s * 0.9), QPointF(s / 2, s * 0.66))
    p.end()
    return pixmap


def _label(text, size, role, bold=False):
    """role: 홈 색 표의 이름(text·title·sub·muted·warn·warn_text·warn_sub). 색은 페이지 스타일시트가 칠한다(테마 바뀌면 다시 칠함)."""
    label = QLabel(text)
    label.setObjectName("h_" + role)
    label.setStyleSheet(f"font-size:{size}px; font-weight:{700 if bold else 400}; background:transparent;")
    return label


def _box(name="homeBox"):
    frame = QFrame()
    frame.setObjectName(name)
    return frame


class FeatureRow(QFrame):
    """이름(굵게) + 상태 점·한 줄 + (스위치) + `›`. 줄을 누르면 그 화면으로."""

    clicked = Signal()

    def __init__(self, name, has_switch, parent=None):
        super().__init__(parent)
        self.setObjectName("homeRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 7, 0, 7)  # 줄 높이: 한글 글꼴(Noto·맑은 고딕)이 높아도 790×800에 스크롤 없게
        row.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(1)
        self.name = _label(name, 13, "text")
        text.addWidget(self.name)
        self.state = QLabel()
        self.state.setTextFormat(Qt.TextFormat.RichText)
        self.state.setStyleSheet("background:transparent; font-size:11px;")
        text.addWidget(self.state)
        row.addLayout(text, 1)
        self.switch = Switch() if has_switch else None
        if self.switch is not None:
            row.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)
        chevron = _label("›", 20, "muted")
        row.addWidget(chevron, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_state(self, text, kind, switch=None):
        self._last = (text, kind)
        color = KIND_COLORS.get(kind, _D["muted"])
        self.state.setText(f'<span style="color:{color}">●</span>'
                           f'<span style="color:{color}">&nbsp;{text}</span>')
        if self.switch is not None and switch is not None and self.switch.isChecked() != bool(switch):
            self.switch.blockSignals(True)
            self.switch.setChecked(bool(switch))
            self.switch.blockSignals(False)
            self.switch.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class HomePage(QWidget):
    menu_requested = Signal()  # 전체 메뉴 › — 홈을 닫고 마지막 탭으로
    open_feature = Signal(str)  # 줄·› 누름 → 그 화면
    open_region = Signal(str)  # 설정 필요 상자의 영역 지정 → 그 화면의 영역 지정 상자
    open_combat_tab = Signal()
    switch_toggled = Signal(str, bool)  # 스위치(기능 키, 켬)
    combat_toggled = Signal(bool)  # 전투 보조 켜짐(True)/일시정지(False)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._apply_style()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()  # 설정 필요 줄이 아주 많을 때만 스크롤(기준 창 790×800은 스크롤 없음)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setObjectName("homeContent")
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self.scroll = scroll
        v = QVBoxLayout(content)
        v.setContentsMargins(18, 6, 18, 12)
        v.setSpacing(8)
        self._content_layout = v
        self._tight = False

        # 1. 위 줄: 로고 · 전체 메뉴 ›
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        logo = QLabel()
        image = QPixmap(str(paths.resource_dir() / "startup_logo.png"))  # 글자 로고(투명 여백 포함)
        if not image.isNull():
            ratio = self.devicePixelRatioF() or 1.0
            image = image.scaledToHeight(round(48 * ratio), Qt.TransformationMode.SmoothTransformation)
            image.setDevicePixelRatio(ratio)
            logo.setPixmap(image)
        logo.setStyleSheet("background:transparent;")
        top.addWidget(logo)
        top.addStretch(1)
        self.menu_btn = QPushButton("전체 메뉴  ›")
        self.menu_btn.setObjectName("homeMenu")
        self.menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_btn.clicked.connect(self.menu_requested.emit)
        top.addWidget(self.menu_btn)
        v.addLayout(top)

        # 2. 상태 카드
        card = _box()
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(12)
        self.state_icon = StateIcon()
        row.addWidget(self.state_icon)
        text = QVBoxLayout()
        text.setSpacing(3)
        self.title = _label("", 16, "title", bold=True)
        self.summary = _label("", 12, "sub")
        text.addWidget(self.title)
        text.addWidget(self.summary)
        row.addLayout(text, 1)
        row.addWidget(_label("전투 보조", 12, "text"))
        self.combat_switch = Switch()
        self.combat_switch.toggled.connect(self.combat_toggled.emit)
        row.addWidget(self.combat_switch)
        v.addWidget(card)

        # 3. 설정이 필요한 기능(있을 때만)
        self.warn_box = _box("homeWarn")
        warn = QVBoxLayout(self.warn_box)
        warn.setContentsMargins(16, 10, 16, 6)
        warn.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(6)
        triangle = QLabel()
        self._triangle = triangle
        triangle.setPixmap(paint_icon("region", _D["warn"]))
        triangle.setStyleSheet("background:transparent;")
        head.addWidget(triangle)
        self.warn_title = _label("", 13, "warn", bold=True)
        head.addWidget(self.warn_title)
        head.addStretch(1)
        warn.addLayout(head)
        self._warn_rows = QVBoxLayout()
        self._warn_rows.setSpacing(0)
        warn.addSpacing(4)
        warn.addLayout(self._warn_rows)
        v.addWidget(self.warn_box)

        # 4. 전투 보조 2열 10줄
        combat = _box()
        box = QVBoxLayout(combat)
        box.setContentsMargins(16, 10, 16, 6)
        box.setSpacing(4)
        head = QHBoxLayout()
        head.addWidget(_label("전투 보조", 14, "title", bold=True))
        head.addStretch(1)
        self.combat_link = QPushButton("전투 보조 탭 열기")
        self.combat_link.setObjectName("homeLink")
        self.combat_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combat_link.clicked.connect(self.open_combat_tab.emit)
        head.addWidget(self.combat_link)
        box.addLayout(head)
        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(0)
        self.rows: dict[str, FeatureRow] = {}
        for index, (key, name, has_switch) in enumerate(COMBAT_ROWS):
            grid.addWidget(self._row(key, name, has_switch), index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        box.addLayout(grid)
        v.addWidget(combat)

        # 5. 아래 한 줄 3칸
        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        for title, rows in BOTTOM_BOXES:
            frame = _box()
            frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            box = QVBoxLayout(frame)
            box.setContentsMargins(16, 10, 16, 6)
            box.setSpacing(4)
            box.addWidget(_label(title, 14, "title", bold=True))
            for key, name, has_switch in rows:
                box.addWidget(self._row(key, name, has_switch))
            box.addStretch(1)
            bottom.addWidget(frame, 1)
        v.addLayout(bottom)
        v.addStretch(1)
        self.update_state({})

    def _apply_style(self):
        d = _D
        self.setStyleSheet(f"""
            #homeBox {{ background:{d['box']}; border:1px solid {d['border']}; border-radius:10px; }}
            #homeWarn {{ background:{d['warn_bg']}; border:1px solid {d['warn_border']}; border-radius:10px; }}
            #homeRow {{ background:transparent; border:none; border-top:1px solid {d['border']}; }}
            #homeWarnRow {{ background:transparent; border:none; border-top:1px solid {d['warn_line']}; }}
            QLabel#h_text {{ color:{d['text']}; }} QLabel#h_title {{ color:{d['title']}; }} QLabel#h_sub {{ color:{d['sub']}; }}
            QLabel#h_muted {{ color:{d['muted']}; }} QLabel#h_warn {{ color:{d['warn']}; }}
            QLabel#h_warn_text {{ color:{d['warn_text']}; }} QLabel#h_warn_sub {{ color:{d['warn_sub']}; }}
            QPushButton#homeMenu {{ color:{d['text']}; background:{d['menu_bg']}; border:1px solid {d['menu_border']}; border-radius:8px;
                                    padding:8px 14px; font-size:12px; }}
            QPushButton#homeMenu:hover {{ border-color:{d['accent']}; }}
            QPushButton#homeLink {{ color:{d['accent']}; background:transparent; border:none; font-size:12px; padding:0; }}
            QPushButton#homeRegion {{ color:{d['warn_text']}; background:transparent; border:1px solid {d['warn']}; border-radius:6px;
                                      padding:5px 12px; font-size:12px; }}
            QScrollArea, #homeContent {{ background:transparent; border:none; }}
            QScrollBar:vertical {{ background:transparent; width:8px; margin:4px 2px 4px 0; }}
            QScrollBar::handle:vertical {{ background:{d['handle']}; border-radius:3px; min-height:30px; }}
            QScrollBar::handle:vertical:hover {{ background:{d['handle_hover']}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:none; }}
        """)

    def set_tight(self, tight: bool) -> None:
        """위에 업데이트 배너가 있을 때(0.31.1 시안 A) 여백을 조금 줄여 790×800에서도 설정 필요 3줄까지 스크롤 없게."""
        tight = bool(tight)
        if tight == self._tight:
            return
        self._tight = tight
        self._content_layout.setContentsMargins(18, 0 if tight else 6, 18, 12)
        self._content_layout.setSpacing(6 if tight else 8)
        for line in self._warn_widgets():
            line.layout().setContentsMargins(0, 4 if tight else 5, 0, 4 if tight else 5)

    def apply_theme(self, custom: dict | None) -> None:
        """테마가 바뀌면 홈을 다시 칠한다(개인화 중이면 틀/내용 칸, 아니면 기본 남색). 재시작 없이 즉시."""
        _D.clear()
        _D.update(design(custom))
        KIND_COLORS.update(ok=_D["ok"], muted=_D["muted"], warn=_D["warn"])
        self._apply_style()
        self._triangle.setPixmap(paint_icon("region", _D["warn"]))
        kind, self.state_icon.kind = self.state_icon.kind, None
        if kind is not None:
            self.state_icon.set_kind(kind)
        for row in self.rows.values():
            last = getattr(row, "_last", None)
            if last is not None:
                row.set_state(*last)
        self.update()
        for widget in self.findChildren(QAbstractButton):
            widget.update()

    def _row(self, key, name, has_switch):
        row = FeatureRow(name, has_switch)
        row.clicked.connect(lambda key=key: self.open_feature.emit(key))
        if row.switch is not None:
            row.switch.toggled.connect(lambda on, key=key: self.switch_toggled.emit(key, on))
        self.rows[key] = row
        return row

    def paintEvent(self, _event):
        p = QPainter(self)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor(_D["bg_top"]))
        gradient.setColorAt(1, QColor(_D["bg_bottom"]))
        p.fillRect(self.rect(), gradient)
        p.end()

    def update_state(self, state: dict) -> None:
        """state: title('running'|'waiting'|'paused'), combat_on, working, needs[(키, 이름)], rows{키: (문구, 종류, 스위치)}."""
        title, icon = TITLES[state.get("title", "waiting")]
        self.title.setText(title)
        self.state_icon.set_kind(icon)
        needs = list(state.get("needs", ()))
        summary = f"전투 보조 {state.get('working', 0)}개 동작 중"
        if needs:
            summary += f" · {len(needs)}개 설정 필요"
        self.summary.setText(summary)
        on = bool(state.get("combat_on", True))
        if self.combat_switch.isChecked() != on:
            self.combat_switch.blockSignals(True)
            self.combat_switch.setChecked(on)
            self.combat_switch.blockSignals(False)
            self.combat_switch.update()
        self._set_needs(needs)
        for key, value in state.get("rows", {}).items():
            if key in self.rows:
                self.rows[key].set_state(*value)

    def _set_needs(self, needs):
        if [w.property("key") for w in self._warn_widgets()] != [k for k, _ in needs]:
            while self._warn_rows.count():
                item = self._warn_rows.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()
            for key, name in needs:
                line = QFrame()
                line.setObjectName("homeWarnRow")
                line.setProperty("key", key)
                row = QHBoxLayout(line)
                pad = 4 if self._tight else 5
                row.setContentsMargins(0, pad, 0, pad)
                row.setSpacing(14)
                row.addWidget(_label(name, 12, "warn_text", bold=True))
                row.addWidget(_label("판독 영역을 지정해야 동작해요", 12, "warn_sub"), 1)
                button = QPushButton("영역 지정")
                button.setObjectName("homeRegion")
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.clicked.connect(lambda _=False, key=key: self.open_region.emit(key))
                row.addWidget(button)
                self._warn_rows.addWidget(line)
        self.warn_title.setText(f"설정이 필요한 기능 {len(needs)}개")
        self.warn_box.setVisible(bool(needs))  # 0개면 상자 자체를 숨긴다(명세 12.2)

    def _warn_widgets(self):
        return [self._warn_rows.itemAt(i).widget() for i in range(self._warn_rows.count())
                if self._warn_rows.itemAt(i).widget() is not None]
