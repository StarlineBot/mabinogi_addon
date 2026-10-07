"""커스텀 오버레이(미러링) 탭 — UI 레이아웃 (기획서 3.6).

화면의 일부(단축바 등)를 드래그로 잘라 투명 오버레이로 복제(=오버레이)하고, 여러
오버레이 묶음을 '프리셋'으로 저장해 캐릭터별로 전환한다. 이 파일은 지금 레이아웃만
구성하고, 실제 캡처·복제·프리셋 저장/불러오기 로직은 이후 단계에서 연결한다.

레이아웃:
  [영역 지정]
  프리셋 (이름만 세로 나열, hover/선택 강조) + [불러오기] [삭제]
  오버레이 목록 (이름만 세로 나열, 선택만)
  [프리셋 저장 5 : 선택 고정 2.5 : 선택 해제 2.5]
  [선택 삭제 : 전체 삭제 : 전체 고정 : 전체 해제] (각 2.5)
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHBoxLayout,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .widgets import hint_label, section_label

# 불릿/체크박스 없이 이름만, hover=밝게, 선택=강조색.
_LIST_QSS = """
QListWidget { border:1px solid #3a3d44; border-radius:4px; background:#202227; }
QListWidget::item { padding:6px 10px; border:none; }
QListWidget::item:hover { background:#2f333a; }
QListWidget::item:selected { background:#00B894; color:white; }
"""

# 삭제(파괴적) 버튼 강조색
_DANGER_QSS = (
    "QPushButton { background:#e74c3c; color:white; font-weight:600; }"
    "QPushButton:hover { background:#c0392b; }"
)


def _name_list() -> QListWidget:
    lst = QListWidget()
    lst.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    lst.setStyleSheet(_LIST_QSS)
    return lst


class CustomOverlayTab(QWidget):
    # 실제 로직 연결 지점(지금은 UI만). 버튼이 눌리면 방출.
    region_requested = Signal()  # [영역 지정]
    preset_load_requested = Signal()  # [불러오기]
    preset_delete_requested = Signal()  # 프리셋 [삭제]
    preset_save_requested = Signal()  # [프리셋 저장]

    def __init__(self) -> None:
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)

        # 영역 지정
        self.region_btn = QPushButton("영역 지정")
        self.region_btn.setToolTip("드래그로 화면 일부를 잘라 오버레이로 복제(돋보기)")
        self.region_btn.clicked.connect(self.region_requested)
        v.addWidget(self.region_btn)

        # 프리셋
        v.addWidget(section_label("프리셋"))
        self.preset_list = _name_list()
        v.addWidget(self.preset_list, 1)
        preset_row = QHBoxLayout()
        self.preset_load_btn = QPushButton("불러오기")
        self.preset_load_btn.clicked.connect(self.preset_load_requested)
        self.preset_delete_btn = QPushButton("삭제")
        self.preset_delete_btn.setStyleSheet(_DANGER_QSS)
        self.preset_delete_btn.clicked.connect(self.preset_delete_requested)
        preset_row.addWidget(self.preset_load_btn)
        preset_row.addWidget(self.preset_delete_btn)
        v.addLayout(preset_row)

        # 오버레이 목록(선택만)
        v.addWidget(section_label("오버레이 목록"))
        self.overlay_list = _name_list()
        v.addWidget(self.overlay_list, 2)
        v.addWidget(hint_label("영역 지정으로 추가됩니다. 이름 옆 (…)은 캡처한 프로그램."))

        # 액션 버튼 (2행, 4열 그리드로 비율 정렬)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        for c in range(4):
            grid.setColumnStretch(c, 1)
        self.save_btn = QPushButton("프리셋 저장")
        self.save_btn.setStyleSheet(
            "QPushButton { background:#00B894; color:white; font-weight:600; }"
        )
        self.save_btn.clicked.connect(self.preset_save_requested)
        self.sel_lock_btn = QPushButton("선택 고정")
        self.sel_unlock_btn = QPushButton("선택 해제")
        self.del_sel_btn = QPushButton("선택 삭제")
        self.del_sel_btn.setStyleSheet(_DANGER_QSS)
        self.del_all_btn = QPushButton("전체 삭제")
        self.del_all_btn.setStyleSheet(_DANGER_QSS)
        self.lock_all_btn = QPushButton("전체 고정")
        self.unlock_all_btn = QPushButton("전체 해제")
        # 1행: 프리셋 저장(2칸) · 선택 고정(1) · 선택 해제(1)
        grid.addWidget(self.save_btn, 0, 0, 1, 2)
        grid.addWidget(self.sel_lock_btn, 0, 2)
        grid.addWidget(self.sel_unlock_btn, 0, 3)
        # 2행: 선택 삭제 · 전체 삭제 · 전체 고정 · 전체 해제 (각 1칸)
        grid.addWidget(self.del_sel_btn, 1, 0)
        grid.addWidget(self.del_all_btn, 1, 1)
        grid.addWidget(self.lock_all_btn, 1, 2)
        grid.addWidget(self.unlock_all_btn, 1, 3)
        v.addLayout(grid)
