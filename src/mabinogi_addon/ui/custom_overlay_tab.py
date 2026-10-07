"""커스텀 오버레이(미러링) 탭 (기획서 3.6).

화면 일부를 드래그로 잘라 투명 오버레이로 복제(=오버레이)하고, 여러 오버레이 묶음을
'프리셋'으로 저장해 캐릭터별로 전환한다.

레이아웃:
  설명 문구
  [영역 지정]
  프리셋 (이름만 나열, hover/선택 강조) + [불러오기] [삭제]
  오버레이 목록 (선택만)
  [프리셋 저장 5 : 선택 고정 2.5 : 선택 해제 2.5]
  [선택 삭제 : 전체 삭제 : 전체 고정 : 전체 해제] (각 2.5)
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..system.window_watcher import WindowWatcher
from .help_dialog import help_title_row
from .mirror_manager import MirrorManager
from .widgets import hint_label, section_label

# 커스텀 오버레이 사용법(? 아이콘 → 새 창).
HELP_TITLE = "커스텀 오버레이 사용법"
HELP_HTML = """
<h3>커스텀 오버레이란?</h3>
<p>지정한 화면 영역을 원하는 위치로 <b>미러링(복제)</b>하는 기능입니다.
단축바에 있는 스킬의 쿨타임을 캐릭터 근처에 두고 확인하거나,
체력바를 지정해 원하는 위치에 둘 수 있습니다.</p>

<h3>사용 순서</h3>
<ol>
<li><b>영역 지정</b> — 복제할 화면 영역을 드래그로 잡습니다.
(돋보기로 픽셀 단위 조정)</li>
<li><b>오버레이 이동</b> — 만들어진 오버레이를 드래그로 원하는 위치에 둡니다.
마우스 휠로 크기 조절, 더블클릭으로 원래 크기.
<b>고정</b>을 누르면 위치가 잠기고 클릭도 통과합니다.</li>
</ol>

<h3>프리셋</h3>
<p>여러 오버레이 묶음을 <b>프리셋</b>으로 저장해 캐릭터·상황별로 전환할 수 있습니다.
(선택/전체 고정·해제·삭제)</p>
"""

_LIST_QSS = """
QListWidget { border:1px solid #3a3d44; border-radius:4px; background:#202227; }
QListWidget::item { padding:6px 10px; border:none; }
QListWidget::item:hover { background:#2f333a; }
QListWidget::item:selected { background:#00B894; color:white; }
"""
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
    def __init__(self, watcher: WindowWatcher) -> None:
        super().__init__()
        self._watcher = watcher
        # 게임 비활성/최소화면 미러 캡처를 쉬고 오버레이를 숨긴다(CPU 절약).
        self._mgr = MirrorManager(is_active=watcher.is_game_active, parent=self)
        self._mgr.changed.connect(self._refresh_overlays)
        self._mgr.changed.connect(self._save_current)
        self._mgr.overlay_moved.connect(self._save_current)
        self._pending_name = "화면"
        self._selector = None

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)

        v.addLayout(help_title_row("커스텀 오버레이", HELP_TITLE, HELP_HTML, self))
        v.addWidget(
            hint_label("화면 특정 영역을 선택, 원하는 위치에 오버레이로 띄우는 기능입니다.")
        )
        self.region_btn = QPushButton("영역 지정")
        self.region_btn.setToolTip("드래그로 화면 일부를 잘라 오버레이로 복제(돋보기)")
        self.region_btn.clicked.connect(self._on_region)
        v.addWidget(self.region_btn)

        # 프리셋
        v.addWidget(section_label("프리셋"))
        self.preset_list = _name_list()
        v.addWidget(self.preset_list, 1)
        preset_row = QHBoxLayout()
        self.preset_load_btn = QPushButton("불러오기")
        self.preset_load_btn.clicked.connect(self._on_preset_load)
        self.preset_delete_btn = QPushButton("삭제")
        self.preset_delete_btn.setStyleSheet(_DANGER_QSS)
        self.preset_delete_btn.clicked.connect(self._on_preset_delete)
        preset_row.addWidget(self.preset_load_btn)
        preset_row.addWidget(self.preset_delete_btn)
        v.addLayout(preset_row)

        # 오버레이 목록(선택만)
        v.addWidget(section_label("오버레이 목록"))
        self.overlay_list = _name_list()
        v.addWidget(self.overlay_list, 2)
        v.addWidget(
            hint_label(
                "영역 지정으로 추가됩니다. 이름 옆 (…)은 캡처한 프로그램.\n"
                "해제 상태에서 드래그로 이동 · 마우스 휠로 크기 조절 · 더블클릭 원래 크기."
            )
        )

        # 액션 버튼 (2행, 4열 그리드)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        for c in range(4):
            grid.setColumnStretch(c, 1)
        self.save_btn = QPushButton("프리셋 저장")
        self.save_btn.setStyleSheet(
            "QPushButton { background:#00B894; color:white; font-weight:600; }"
        )
        self.save_btn.clicked.connect(self._on_preset_save)
        self.sel_lock_btn = QPushButton("선택 고정")
        self.sel_lock_btn.clicked.connect(lambda: self._lock_selected(True))
        self.sel_unlock_btn = QPushButton("선택 해제")
        self.sel_unlock_btn.clicked.connect(lambda: self._lock_selected(False))
        self.del_sel_btn = QPushButton("선택 삭제")
        self.del_sel_btn.setStyleSheet(_DANGER_QSS)
        self.del_sel_btn.clicked.connect(self._on_delete_selected)
        self.del_all_btn = QPushButton("전체 삭제")
        self.del_all_btn.setStyleSheet(_DANGER_QSS)
        self.del_all_btn.clicked.connect(self._on_delete_all)
        self.lock_all_btn = QPushButton("전체 고정")
        self.lock_all_btn.clicked.connect(lambda: self._mgr.set_locked_all(True))
        self.unlock_all_btn = QPushButton("전체 해제")
        self.unlock_all_btn.clicked.connect(lambda: self._mgr.set_locked_all(False))
        grid.addWidget(self.save_btn, 0, 0, 1, 2)
        grid.addWidget(self.sel_lock_btn, 0, 2)
        grid.addWidget(self.sel_unlock_btn, 0, 3)
        grid.addWidget(self.del_sel_btn, 1, 0)
        grid.addWidget(self.del_all_btn, 1, 1)
        grid.addWidget(self.lock_all_btn, 1, 2)
        grid.addWidget(self.unlock_all_btn, 1, 3)
        v.addLayout(grid)

        self._refresh_presets()
        self._refresh_overlays()

    # ---- 영역 지정 → 오버레이 추가 ----
    def _on_region(self) -> None:
        # 선택창을 띄우기 전 포그라운드 프로그램명을 라벨로 기록.
        try:
            _title, exe = self._watcher.foreground_info()
            self._pending_name = exe or "화면"
        except Exception:  # noqa: BLE001 — 창 정보 못 읽으면 기본 라벨
            self._pending_name = "화면"
        from .region_selector import RegionSelector

        self._selector = RegionSelector()
        self._selector.selected.connect(self._on_selected)
        self._selector.start()

    def _on_selected(self, x: int, y: int, w: int, h: int) -> None:
        self._mgr.add(
            {"x": x, "y": y, "w": w, "h": h, "posX": x, "posY": y, "name": self._pending_name}
        )

    # ---- 목록 ----
    def _refresh_overlays(self) -> None:
        self.overlay_list.clear()
        for i, o in enumerate(self._mgr.overlays(), 1):
            tag = " · 고정" if o.locked else ""
            self.overlay_list.addItem(f"오버레이{i} ({o.name}){tag}")

    def _refresh_presets(self) -> None:
        self.preset_list.clear()
        for name in sorted(config.load_custom_presets()):
            self.preset_list.addItem(name)

    def _selected_rows(self, lst: QListWidget) -> list[int]:
        return sorted(lst.row(i) for i in lst.selectedItems())

    def _save_current(self) -> None:
        config.save_custom_overlays(self._mgr.to_dicts())

    # ---- 오버레이 버튼 ----
    def _lock_selected(self, locked: bool) -> None:
        self._mgr.set_locked(self._selected_rows(self.overlay_list), locked)

    def _on_delete_selected(self) -> None:
        rows = self._selected_rows(self.overlay_list)
        if rows:
            self._mgr.remove_indices(rows)

    def _on_delete_all(self) -> None:
        if not self._mgr.overlays():
            return
        if self._confirm("오버레이 전체 삭제", "모든 오버레이를 삭제할까요?"):
            self._mgr.clear()

    # ---- 프리셋 버튼 ----
    def _on_preset_save(self) -> None:
        if not self._mgr.overlays():
            self._info("저장할 오버레이가 없습니다.")
            return
        name, ok = QInputDialog.getText(self, "프리셋 저장", "프리셋 이름:")
        name = name.strip()
        if not ok or not name:
            return
        config.save_custom_preset(name, self._mgr.to_dicts())
        self._refresh_presets()

    def _on_preset_load(self) -> None:
        rows = self._selected_rows(self.preset_list)
        if not rows:
            return
        name = self.preset_list.item(rows[0]).text()
        items = config.load_custom_presets().get(name, [])
        self._mgr.load(items)

    def _on_preset_delete(self) -> None:
        rows = self._selected_rows(self.preset_list)
        if not rows:
            return
        name = self.preset_list.item(rows[0]).text()
        if self._confirm("프리셋 삭제", f"'{name}' 프리셋을 삭제할까요?"):
            config.delete_custom_preset(name)
            self._refresh_presets()

    # ---- 유틸 ----
    def _confirm(self, title: str, text: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        yes = box.addButton("예", QMessageBox.ButtonRole.YesRole)
        box.addButton("아니오", QMessageBox.ButtonRole.NoRole)
        box.exec()
        return box.clickedButton() is yes

    def _info(self, text: str) -> None:
        QMessageBox.information(self, "커스텀 오버레이", text)

    def shutdown(self) -> None:
        self._mgr.shutdown()
