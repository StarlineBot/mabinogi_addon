"""One settings surface, retaining both existing controllers and stored regions."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from .widgets import checkbox, section_label
from .help_dialog import help_button
from .tuarim_tab import HELP_HTML, HELP_TITLE


class ResourceTab(QWidget):
    def __init__(self, dorcha, tuarim):
        super().__init__()
        self.dorcha, self.tuarim = dorcha, tuarim
        for controller in (dorcha, tuarim):
            controller.setParent(self)
            controller.hide()
        dorcha._view = self
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12,12,12,12)
        layout.setSpacing(10)
        row = QHBoxLayout()
        dorcha.enable.setText("도르카 표시")
        self.percent_chk = checkbox("투아림 % 표시")
        self.percent_chk.setChecked(dorcha._cfg["showTuarim"])
        dorcha.bind_tuarim(tuarim,self.percent_chk)
        for control in (dorcha.enable,self.percent_chk,tuarim.enable):
            row.addWidget(control)
        row.addStretch()
        self.help_btn = help_button(HELP_TITLE,HELP_HTML,self)
        row.addWidget(self.help_btn)
        layout.addLayout(row)
        dorcha._beta_notice.setText("표시 기능 · Discord 로그인 베타")
        layout.addWidget(dorcha._beta_notice)

        layout.addWidget(section_label("판독 영역"))
        grid = QGridLayout()
        for index,(name,controller) in enumerate((("도르카 숫자",dorcha),("투아림 %",tuarim))):
            grid.addWidget(QLabel(name),index*2,0)
            grid.addWidget(controller.region_label,index*2,1,1,3)
            controller.auto_find_btn.setText("자동 찾기")
            controller.view_region_btn.setText("지정 영역 보기")
            commands = QHBoxLayout()
            for button in (controller.auto_find_btn,controller.region_btn,controller.view_region_btn,controller.clear_region_btn):
                commands.addWidget(button)
            commands.addStretch()
            grid.addLayout(commands,index*2+1,0,1,4)
        grid.setColumnStretch(1,1)
        layout.addLayout(grid)
        layout.addWidget(QLabel("원본 미리보기"))
        row = QHBoxLayout()
        row.addWidget(QLabel("도르카"))
        row.addWidget(dorcha.source_preview)
        row.addWidget(dorcha.value_label,1)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("투아림"))
        row.addWidget(tuarim.preview)
        row.addWidget(tuarim.value_label,1)
        layout.addLayout(row)

        self._separator(layout)
        layout.addWidget(section_label("표시·배치"))
        row = QHBoxLayout()
        row.addWidget(QLabel("표시 배율"))
        row.addWidget(dorcha.scale_spin)
        dorcha.lock_chk.setText("위치 잠금")
        row.addWidget(dorcha.lock_chk)
        row.addStretch()
        layout.addLayout(row)
        layout.addWidget(QLabel("표시 미리보기"))
        layout.addWidget(dorcha.preview_scroll)

        self._separator(layout)
        tuarim.threshold_box.setTitle("투아림 알림 (% 이상)")
        layout.addWidget(tuarim.threshold_box)
        self.diagnostics_btn = QToolButton()
        self.diagnostics_btn.setText("진단 · 투아림 판독 / 수집")
        self.diagnostics_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.diagnostics_btn.setArrowType(Qt.ArrowType.RightArrow)
        self.diagnostics_btn.setCheckable(True)
        tuarim._diagnostics_toggle = self.diagnostics_btn
        layout.addWidget(self.diagnostics_btn)
        layout.addWidget(tuarim._collect_box)
        self.diagnostics_btn.toggled.connect(self._show_diagnostics)
        layout.addStretch()
        self._show_diagnostics(False)
        dorcha._apply_gate()

    @staticmethod
    def _separator(layout):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)

    def _show_diagnostics(self, checked):
        self.diagnostics_btn.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.tuarim._apply_collect_gate()
