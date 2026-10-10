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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..system.window_watcher import WindowWatcher
from .help_dialog import tab_header
from .mirror_manager import MirrorManager
from .widgets import checkbox, hint_label, section_label

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

# 밝은 배경 + 또렷한 테두리 + 최소 높이 → 비어 있어도 '여기 리스트가 있다'가 보이게.
_LIST_QSS = """
QListWidget { border:1px solid palette(mid); border-radius:6px; background:palette(base);
  min-height:72px; }
QListWidget::item { padding:6px 10px; border:none; }
QListWidget::item:hover { background:palette(midlight); }
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
        # 미러 표시 조건: (1) 게임이 포그라운드 = 실제 사용 중, 또는
        # (2) 우리 앱이 포그라운드 '이면서 이 커스텀 오버레이 탭을 보고 있을 때' = 위치
        #     조정(세팅) 중. → 다른 탭·다른 작업 중엔 안 떠서 화면을 가리지 않고 커서
        #     깜빡임도 없다. 이 탭에서 미러를 클릭해 드래그해도 탭이 보이는 상태라 안 숨음.
        self._mgr = MirrorManager(
            fps=60,  # mss 폴백 경로에서만 쓰임(Windows는 DWM 썸네일 → fps 무관).
            is_active=lambda: (
                watcher.is_game_active()
                or (watcher.is_self_active() and self.isVisible())
            ),
            # Windows: 게임 창을 소스로 DWM 썸네일 미러(CPU ~0%). 못 찾으면 mss 폴백.
            source_hwnd=self._find_game_hwnd,
            parent=self,
        )
        self._mgr.changed.connect(self._refresh_overlays)
        self._mgr.changed.connect(self._save_current)
        self._mgr.overlay_moved.connect(self._save_current)
        self._pending_name = "화면"
        self._selector = None
        self._game_hwnd = 0  # DWM 미러 소스(게임 창) 캐시

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        # 세로 여유가 뷰포트와 거의 딱 맞아(≈9px) Windows 글꼴/DPI에선 아주 얇은
        # 스크롤바가 생겼다. 위젯 간격을 살짝 줄여 그만큼의 여유를 확보한다.
        v.setSpacing(8)

        v.addWidget(tab_header(
            "화면 일부를 다른 위치에 미러링 — 단축바·체력바 등을 눈에 편한 곳에",
            HELP_TITLE, HELP_HTML, self
        ))
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

        # 시작 시 자동 불러오기(선택한 프리셋 대상). ⭐ 표시로 목록에서 구분.
        self.auto_chk = checkbox("⭐ 선택한 프리셋을 시작 시 자동 불러오기")
        self.auto_chk.toggled.connect(self._on_auto_toggled)
        v.addWidget(self.auto_chk)
        self.preset_list.itemSelectionChanged.connect(self._sync_auto_checkbox)

        # 오버레이 목록(선택만)
        v.addWidget(section_label("오버레이 목록"))
        self.overlay_list = _name_list()
        v.addWidget(self.overlay_list, 2)
        v.addWidget(
            hint_label(
                "영역 지정으로 추가됩니다.\n"
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
        self._auto_load_startup()  # 시작 시 자동 프리셋 불러오기

    # ---- 시작 시 자동 불러오기 ----
    def _find_game_hwnd(self) -> int:
        """DWM 미러 소스로 쓸 게임 창 HWND(캐시; 무효화되면 다시 찾는다). 0=못 찾음."""
        from ..system import dwm_thumbnail
        from ..system.window_watcher import DEFAULT_GAME_TITLES

        if self._game_hwnd and dwm_thumbnail.window_rect(self._game_hwnd):
            return self._game_hwnd  # 아직 유효 → 재탐색 생략(EnumWindows 비용 회피)
        self._game_hwnd = dwm_thumbnail.find_game_window(
            config.load_game_exe(), DEFAULT_GAME_TITLES
        )
        return self._game_hwnd

    def _auto_load_startup(self) -> None:
        name = config.load_auto_preset()
        if not name:
            return
        items = config.load_custom_presets().get(name)
        if items:
            self._mgr.load(items)

    def _sync_auto_checkbox(self) -> None:
        """선택한 프리셋이 자동 불러오기 대상인지 체크박스에 반영."""
        rows = self._selected_rows(self.preset_list)
        self.auto_chk.blockSignals(True)
        if rows:
            name = self.preset_list.item(rows[0]).data(Qt.ItemDataRole.UserRole)
            self.auto_chk.setEnabled(True)
            self.auto_chk.setChecked(name == config.load_auto_preset())
        else:
            self.auto_chk.setChecked(False)
            self.auto_chk.setEnabled(False)
        self.auto_chk.blockSignals(False)

    def _on_auto_toggled(self, checked: bool) -> None:
        rows = self._selected_rows(self.preset_list)
        if not rows:
            return
        name = self.preset_list.item(rows[0]).data(Qt.ItemDataRole.UserRole)
        if checked:
            config.save_auto_preset(name)
        elif config.load_auto_preset() == name:
            config.save_auto_preset(None)
        self._refresh_presets()

    # ---- 영역 지정 → 오버레이 추가 ----
    def _on_region(self) -> None:
        # 선택창을 띄우기 전 포그라운드 프로그램명을 라벨로 기록.
        try:
            _title, exe = self._watcher.foreground_info()
            self._pending_name = exe or "화면"
        except Exception:  # noqa: BLE001 — 창 정보 못 읽으면 기본 라벨
            self._pending_name = "화면"
        from .region_selector import RegionSelector

        # 게임 창 HWND를 넘겨, 영역 지정 돋보기가 작업표시줄에 가린 부분도 게임 내용으로
        # 보이게 한다(PrintWindow로 창을 직접 읽음 — 하단 체력바 미러링 등).
        self._selector = RegionSelector(window_hwnd=self._find_game_hwnd() or None)
        self._selector.selected.connect(self._on_selected)
        self._selector.start()

    def _on_selected(self, x: int, y: int, w: int, h: int) -> None:
        # 새 미러는 원본 위에 겹쳐 뜨면 "된 건가?" 헷갈리므로, 화면 좌측 1/4 지점에
        # 띄워 분명히 보이게 한다(사용자가 원하는 위치로 드래그).
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        geo = screen.geometry() if screen else None
        if geo is not None:
            pos_x = geo.x() + geo.width() // 4 - w // 2
            pos_y = geo.y() + geo.height() // 4 - h // 2
        else:
            pos_x, pos_y = x, y
        self._mgr.add(
            {
                "x": x, "y": y, "w": w, "h": h,
                "posX": pos_x, "posY": pos_y, "name": self._pending_name,
            }
        )

    # ---- 목록 ----
    def _refresh_overlays(self) -> None:
        self.overlay_list.clear()
        overlays = self._mgr.overlays()
        if not overlays:
            # 비었을 때: 리스트가 비어 '없는 줄' 알기 쉬워, 안내 문구를 회색으로 1줄.
            from PySide6.QtGui import QColor

            hint = QListWidgetItem("표시할 오버레이가 없어요 — 위 '영역 지정'으로 추가하세요")
            hint.setFlags(Qt.ItemFlag.NoItemFlags)  # 선택·호버 안 됨(안내 전용)
            hint.setForeground(QColor("#8a8f98"))
            self.overlay_list.addItem(hint)
            return
        for i, o in enumerate(overlays, 1):
            tag = " · 고정" if o.locked else ""
            self.overlay_list.addItem(f"오버레이{i}{tag}")

    def _refresh_presets(self) -> None:
        self.preset_list.clear()
        auto = config.load_auto_preset()
        for name in sorted(config.load_custom_presets()):
            # 실제 이름은 UserRole에 보관(표시엔 자동 불러오기 ⭐ 표시 추가).
            item = QListWidgetItem(f"⭐ {name}" if name == auto else name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.preset_list.addItem(item)
        self._sync_auto_checkbox()

    def _preset_name(self, row: int) -> str:
        return self.preset_list.item(row).data(Qt.ItemDataRole.UserRole)

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
        rows = self._selected_rows(self.preset_list)
        if rows:
            # 상단 목록에서 고른 프리셋이 있으면: 이름 입력 없이 그 프리셋에 덮어쓰기(확인).
            name = self._preset_name(rows[0])
            if not self._confirm(
                "프리셋 덮어쓰기", f"'{name}' 프리셋을 덮어쓸까요?"
            ):
                return
        else:
            # 선택이 없으면: 새 프리셋으로 등록(이름 입력). 이름이 겹치면 한 번 확인.
            name, ok = QInputDialog.getText(self, "프리셋 저장", "프리셋 이름:")
            name = name.strip()
            if not ok or not name:
                return
            if name in config.load_custom_presets() and not self._confirm(
                "프리셋 덮어쓰기", f"'{name}' 프리셋을 덮어쓸까요?"
            ):
                return
        config.save_custom_preset(name, self._mgr.to_dicts())
        self._refresh_presets()

    def _on_preset_load(self) -> None:
        rows = self._selected_rows(self.preset_list)
        if not rows:
            return
        name = self._preset_name(rows[0])
        items = config.load_custom_presets().get(name, [])
        self._mgr.load(items)

    def _on_preset_delete(self) -> None:
        rows = self._selected_rows(self.preset_list)
        if not rows:
            return
        name = self._preset_name(rows[0])
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

    def set_paused(self, paused: bool) -> None:
        """사용자 일시정지 → 미러 오버레이 숨김·캡처 쉼(메인 윈도우가 호출)."""
        self._mgr.set_paused(paused)

    def shutdown(self) -> None:
        self._mgr.shutdown()
