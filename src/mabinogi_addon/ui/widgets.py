"""UI 공용 소형 위젯.

지금 단계는 레이아웃 확정을 위한 '껍데기'다. 동작(파일 선택, 영역 지정,
설정 저장)은 아직 연결하지 않고 자리만 잡는다.
"""

from __future__ import annotations

import math
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QFocusEvent, QPainter, QPalette, QTextLayout, QTextOption
from PySide6.QtWidgets import QBoxLayout, QCheckBox, QFormLayout, QLabel, QMessageBox, QSizePolicy, QSpinBox, QWidget


def wrapping_row(left, right):
    """Keep two control groups inline, wrapping the second at its native minimum width."""
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    groups = []
    for layout in (left, right):
        body = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        body.setLayout(layout)
        groups.append(body)
    form.addRow(*groups)
    return form


class CapturePathLabel(QLabel):
    """Wrap unbroken paths without imposing their minimum word width."""

    def __init__(self):
        super().__init__()
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setStyleSheet("color:#8a8f98;")
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        self.setSizePolicy(policy)

    def _text_layout(self, width):
        layout = QTextLayout(self.text(), self.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        height = 0
        layout.beginLayout()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1, width))
            line.setPosition(QPointF(0, height))
            height += line.height()
        layout.endLayout()
        return layout, math.ceil(height)

    def heightForWidth(self, width):
        return self._text_layout(width)[1]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        self._text_layout(self.width())[0].draw(painter, QPointF())
        painter.end()


class TrackerColumns(QBoxLayout):
    """기본 두 열을 유지하고 실제 최소 폭이 넘칠 때만 세로로 배치한다."""

    def __init__(self, left, right):
        super().__init__(QBoxLayout.Direction.LeftToRight)
        self.setSpacing(14)
        self.addWidget(left, 1)
        self.addWidget(right, 1)

    @property
    def stacked(self):
        return self.direction() == QBoxLayout.Direction.TopToBottom

    def fit_width(self, width):
        margins = self.parentWidget().layout().contentsMargins()
        available = width - margins.left() - margins.right()
        required = self.spacing() + sum(
            max(self.itemAt(i).widget().minimumSizeHint().width(), self.itemAt(i).widget().minimumWidth())
            for i in range(2))
        direction = (QBoxLayout.Direction.TopToBottom if required > available
                     else QBoxLayout.Direction.LeftToRight)
        if direction != self.direction():
            self.setDirection(direction)


class SuffixSpinBox(QSpinBox):
    """suffix(' 만' 등)가 있어도 숫자 입력이 막히지 않는 스핀박스.

    기본 QSpinBox는 커서가 suffix 뒤에 놓이면(칸을 클릭하면 보통 맨 뒤=suffix 뒤로
    간다) 타이핑이 전부 무시된다. 그래서:
    - 포커스가 들어오면 숫자를 전체 선택해 바로 타이핑하면 덮어쓰게 하고,
    - 커서가 suffix 영역으로 들어가면 숫자 끝(suffix 앞)으로 되돌린다.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.lineEdit().cursorPositionChanged.connect(self._clamp_cursor)

    def _max_cursor(self) -> int:
        return len(self.lineEdit().text()) - len(self.suffix())

    def _clamp_cursor(self, _old: int, new: int) -> None:
        limit = self._max_cursor()
        if new > limit:
            self.lineEdit().setCursorPosition(limit)  # suffix 앞으로 되돌림

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        self.lineEdit().selectAll()  # 포커스 즉시 전체 선택 → 타이핑하면 교체


def checkbox(text: str = "") -> QCheckBox:
    """체크박스를 글자 너비만큼만 차지하게 만든다.

    세로/stretch 레이아웃에 넣으면 체크박스가 가로로 꽉 늘어나, 그 줄의 빈 공간을
    클릭해도 토글돼 버린다(앱을 클릭하려다 설정이 바뀌는 문제). 가로 정책을 Maximum으로
    두면 sizeHint 너비(체크표시+이름)만 차지해 그 영역만 클릭에 반응한다.
    """
    cb = QCheckBox(text)
    cb.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return cb


def feature_checkbox(key: str, text: str) -> QCheckBox:
    from ..setup_state import enabled, save_enabled

    cb = checkbox(text)
    cb.setChecked(enabled(key))

    def save(value):
        try:
            save_enabled(key, value)
        except OSError:
            cb.blockSignals(True)
            cb.setChecked(enabled(key))
            cb.blockSignals(False)
            QMessageBox.warning(cb, "설정 저장 실패", "사용 설정을 저장하지 못했습니다. 쓰기 권한을 확인하세요.")

    cb.toggled.connect(save)
    return cb


def icon_slot(placeholder: str = "▣") -> QLabel:
    """아이콘 미리보기 칸. 나중에 QPixmap을 setPixmap으로 채운다."""
    slot = QLabel(placeholder)
    slot.setAlignment(Qt.AlignmentFlag.AlignCenter)
    slot.setFixedSize(44, 44)
    slot.setStyleSheet(
        "border:1px solid palette(mid); border-radius:6px;"
        "font-size:22px; color:palette(mid); background:palette(base);"
    )
    return slot


def hint_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)  # 긴 안내문이 한 줄로 창 폭을 강제하지 않게(여러 줄로 접힘)
    lbl.setStyleSheet("color:#8a8f98;")
    return lbl


def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("font-weight:600; color:#c8ccd4;")
    return lbl


def callout(text: str, icon: str = "⚠") -> QLabel:
    """꼭 알아야 할 제약·주의를 눈에 띄게 보여주는 호박색 박스.

    회색 각주(hint_label)로 묻히면 놓치기 쉬운 '제약'(예: 같은 아이콘은 구분 불가)을
    테두리·배경 있는 콜아웃으로 승격한다. 색은 라이트/다크 테마 모두에서 읽히게
    반투명 호박색을 쓴다.
    """
    lbl = QLabel(f"{icon}  {text}" if icon else text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(
        "QLabel { background: rgba(230,160,30,0.12);"
        " border:1px solid rgba(230,160,30,0.55);"
        " border-radius:7px; padding:8px 10px; color:#d98a1a; }"
    )
    return lbl
