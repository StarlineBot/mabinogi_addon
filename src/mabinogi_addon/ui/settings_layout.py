"""Small layout helpers shared by grouped settings pages."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QLabel, QPushButton, QToolButton
from shiboken6 import isValid

from .palette import color
import weakref

# 상태형 토글(위치 잠금·최적화·FPS 표시·블랙박스 사용) 공통 톤. 굵기 보통·세로 padding 0, 켜짐 초록(안내·도움말 명세 13.1 정정).
# 높이는 스타일시트로 계산하지 않고 style_toggle에서 일반 버튼 높이로 고정한다(스타일시트를 입히면 Windows 기본 버튼 높이를 버리기 때문).
def lock_style():
    return (
        "QPushButton { padding:0 10px; border:1px solid palette(mid); border-radius:3px;"
        " background:palette(button); color:palette(button-text); font-weight:400; }"
        "QPushButton:disabled { color:palette(mid); }"
        # 켜짐 테두리 = 강조색(0.31.1: 고정 민트 #00856b는 개인화 강조색에서 초록으로 남았다 — 이름 색이라 즉시 다시 칠해짐)
        f"QPushButton:checked:enabled {{ background:{color('accent')}; color:{color('on-accent')}; border-color:{color('accent')}; }}"
    )


def danger_style():
    return f"QPushButton:enabled {{ color:{color('danger')}; }}"


LOCK_PADDING = 22  # 잠금 버튼 폭 = 보통 굵기 '…위치 잠금됨' 글자 폭 + 여백(B안)


def plain_button_height():
    """스타일시트 없는 일반 QPushButton의 기본 높이(옆 '알림 미리보기' 등과 같은 키)."""
    return QPushButton("가").sizeHint().height()


def style_toggle(button):
    """상태형 토글 버튼에 공통 톤을 입히는 한 곳: 스타일 + 일반 버튼 높이. 폭은 호출한 쪽이 정한다(토글은 글자에 맞춤)."""
    button.setCheckable(True)
    button.setStyleSheet(lock_style())
    button.setFixedHeight(plain_button_height())
    return button


def lock_text(locked, *, every=False):
    return ("전체 " if every else "") + ("위치 잠금됨" if locked else "위치 잠금")


def lock_width(widget=None, *, every=False):
    """같은 종류끼리 같은 폭: 일반 '위치 잠금(됨)' / '전체 위치 잠금(됨)'. 보통 굵기 '…잠금됨' 글자 폭 + 여백."""
    font = QFont(widget.font()) if widget is not None else QFont()
    return QFontMetrics(font).horizontalAdvance(lock_text(True, every=every)) + LOCK_PADDING


def lock_button(locked=False, *, every=False):
    """같은 모양의 위치 잠금 토글 버튼(일반·전체 종류별 같은 폭). 글자는 set_lock_text로 바꾼다."""
    button = style_toggle(QPushButton(lock_text(locked, every=every)))
    button.setChecked(bool(locked))
    button.setFixedWidth(lock_width(button, every=every))
    button.setProperty("lockEvery", bool(every))
    return button


def set_lock_text(button, locked):
    button.setText(lock_text(locked, every=bool(button.property("lockEvery"))))


def name_label(text, names=()):
    """한 상자 안 여러 줄의 줄 앞 이름 칸(명세 13.1). 폭 = 같은 상자 이름(names) 중 가장 긴 글자 폭.
    상자 안 잠금 버튼은 같은 세로선에 서고, 가장 긴 이름 뒤 간격은 다른 화면의 '라벨 + 버튼' 간격과 같다.
    화면끼리(보스 패턴·1분 헤일로) 버튼 위치는 맞추지 않는다 — 이름 길이가 달라 간격 통일을 택함(2026-10-29 사용자 결정)."""
    label = QLabel(text)
    metrics = label.fontMetrics()
    label.setFixedWidth(max(metrics.horizontalAdvance(name) for name in (*names, text)) + 2)
    return label


def disclosure(title,body,layout):
    button = QToolButton()
    button.setText(title)
    button.setCheckable(True)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setArrowType(Qt.ArrowType.RightArrow)
    body_ref,button_ref = weakref.ref(body),weakref.ref(button)
    def toggle(value):
        target,control = body_ref(),button_ref()
        if target is not None and isValid(target):
            target.setVisible(value)
        if control is not None and isValid(control):
            control.setArrowType(Qt.ArrowType.DownArrow if value else Qt.ArrowType.RightArrow)
    button.toggled.connect(toggle)
    layout.addWidget(button)
    layout.addWidget(body)
    body.hide()
    return button


def opacity_spin(value: int):
    """불투명도 칸(안내·도움말 명세 15절): 배율 칸과 같은 모양, 20~100 %, 10%씩. 0%는 막는다(사라져 보임)."""
    from PySide6.QtWidgets import QSpinBox

    from .. import config
    spin = QSpinBox()
    spin.setRange(config.OPACITY_MIN, config.OPACITY_MAX)
    spin.setSingleStep(config.OPACITY_STEP)
    spin.setPrefix("불투명도 ")  # 뜻이 반대인 '투명도'로 줄이지 않는다
    spin.setSuffix(" %")
    spin.setValue(value)
    spin.setToolTip("오버레이 창 전체의 불투명도예요. 낮출수록 게임 화면이 비쳐 보여요(20~100%).")
    return spin


def enable_drag_reorder(list_widget, on_dropped, *, pinned=None):
    """목록을 끌어서 순서 바꾸기(명세 15절 2항): 안에서만 옮기고(목록 밖으로 끌어도 삭제·복제 없음), 놓일 자리는 Qt 기본 선.

    놓으면 on_dropped(지금 목록 순서의 id들, 놓은 id)를 부른다. pinned(id)는 끌 수 없는 항목(버프 기준) —
    그 위로 놓인 항목은 호출하는 쪽이 고정 항목 바로 아래로 둔다.
    """
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QAbstractItemView

    list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
    list_widget.setDefaultDropAction(Qt.DropAction.MoveAction)
    list_widget.setDragEnabled(True)
    list_widget.setDropIndicatorShown(True)
    list_widget.pinned_id = pinned

    def ids():
        return [list_widget.item(row).data(Qt.ItemDataRole.UserRole) for row in range(list_widget.count())]

    def moved(_parent, start, _end, _dest, row):
        moved_row = row if row <= start else row - 1
        item = list_widget.item(moved_row)
        dropped = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        order = ids()
        # 놓은 뒤 목록을 다시 그리므로, Qt가 끌기 처리를 마친 다음에 부른다
        QTimer.singleShot(0, lambda: on_dropped(order, dropped))

    list_widget.model().rowsMoved.connect(moved)


def equal_columns(*widgets, at_least=0):
    """한 줄 같은 너비 칸(명세 15절 '위치 잠금 │ 배율 │ 불투명도'): 같은 stretch로 여유 폭을 나눠 같은 너비가 되고,
    최소 폭은 칸마다 자기 글자+화살표(minimumSizeHint)만 지킨다. at_least: 글자가 바뀌어 길어지는 칸(잠금 → '위치 잠금됨')의 폭.

    0.31.1: 예전엔 가장 넓은 칸의 기본 폭을 세 칸 모두의 최소 폭으로 걸어 왼쪽 최소 폭이 3배가 됐고, Windows 11 스타일
    (숫자 칸 가로 화살표가 넓음)에서 790 창의 버프·디버프 탭이 두 칸 → 한 칸으로 접혔다(TrackerColumns.fit_width)."""
    for widget in widgets:
        widget.setMinimumWidth(max(at_least, widget.minimumSizeHint().width()))
