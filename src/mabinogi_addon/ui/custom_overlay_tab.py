"""커스텀 오버레이(미러링) 탭 (기획서 3.6).

화면 일부를 드래그로 잘라 투명 오버레이로 복제(=오버레이)하고, 여러 오버레이 묶음을
'프리셋'으로 저장해 캐릭터별로 전환한다.

현재 적용 대상, 목록 선택과 시작 자동 불러오기를 독립적으로 관리한다.
완료된 편집은 묶어서 저장하고 전환/종료 전에 반드시 반영한다.
"""

from __future__ import annotations

from copy import deepcopy
import logging

from PySide6.QtCore import Qt, QSignalBlocker, QTimer
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QSizePolicy,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..system.window_watcher import WindowWatcher
from .help_dialog import tab_header
from .mirror_manager import MirrorManager
from .widgets import CapturePathLabel, checkbox, section_label

_log = logging.getLogger(__name__)

# 커스텀 오버레이 사용법(? 아이콘 → 새 창).
HELP_TITLE = "커스텀 오버레이 사용법"
HELP_HTML = """
<h3>커스텀 오버레이란?</h3>
<p>지정한 화면 영역을 원하는 위치로 <b>미러링(복제)</b>하는 기능입니다.
예를 들어 <b>자주 쓰는 특정 스킬의 쿨타임</b>을 캐릭터 근처 눈에 편한 곳에 두고
관리할 수 있습니다.</p>
<p>(단축바 전체·체력바는 전용 <b>'단축바'·'체력바'</b> 기능을 쓰면 더 편합니다.)</p>

<h3>사용 순서</h3>
<ol>
<li><b>영역 지정</b> — 복제할 화면 영역을 드래그로 잡습니다.
(돋보기로 픽셀 단위 조정)</li>
<li><b>오버레이 이동</b> — 만들어진 오버레이를 드래그로 원하는 위치에 둡니다.
마우스 휠로 크기 조절, 더블클릭으로 원래 크기.
<b>위치 잠금</b>을 선택하면 위치가 잠기고 클릭도 통과합니다.</li>
</ol>

<h3>프리셋</h3>
<p>여러 오버레이 묶음을 <b>프리셋</b>으로 저장해 캐릭터·상황별로 전환할 수 있습니다.
(선택/전체 잠금·해제·삭제)</p>
<p><b>적용 중</b>인 프리셋의 변경은 자동 저장됩니다. 목록에서 다른 이름을 선택만 해도
저장 대상은 바뀌지 않습니다. 원본을 보존하려면 <b>다른 이름으로 저장</b>을 먼저 사용하세요.
<b>시작 시 자동 불러오기</b>는 별도 설정입니다.</p>
"""

# 외곽 테두리 + 최소 높이 → 비어 있어도 '여기 리스트가 있다'가 보이게.
# outline:0 → 선택 시 생기는 포커스 박스(버튼처럼 보이던 테두리) 제거해 '리스트' 느낌.
_LIST_QSS = """
QListWidget { border:1px solid palette(mid); border-radius:6px; background:palette(base);
  min-height:72px; outline:0; }
QListWidget::item { padding:7px 10px; border:none; }
QListWidget::item:hover { background:palette(midlight); }
QListWidget::item:selected { background:#00B894; color:white; }
"""
_DANGER_QSS = (
    "QPushButton { background:#e74c3c; color:white; font-weight:600; }"
    "QPushButton:hover { background:#c0392b; }"
)


class _DashSeparatorDelegate(QStyledItemDelegate):
    """항목 사이에 점선 구분선을 그린다(줄 폭의 ~95%, 가운데 정렬). 리스트다운 느낌."""

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        if index.row() >= index.model().rowCount() - 1:
            return  # 마지막 항목 아래엔 선 없음
        r = option.rect
        margin = int(r.width() * 0.025)  # 양쪽 2.5% 비움 → 95% 폭
        # 다크에선 palette(Mid)가 바탕(base)과 거의 같아 점선이 안 보인다.
        # 테마별로 바탕과 대비되는 회색을 직접 고른다.
        from .theme import is_dark

        color = QColor("#6b7078") if is_dark() else QColor("#b8bcc4")
        pen = QPen(color, 1, Qt.PenStyle.DashLine)
        painter.save()
        painter.setPen(pen)
        y = r.bottom()
        painter.drawLine(r.left() + margin, y, r.right() - margin, y)
        painter.restore()


def _name_list() -> QListWidget:
    lst = QListWidget()
    lst.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    lst.setStyleSheet(_LIST_QSS)
    lst.setItemDelegate(_DashSeparatorDelegate(lst))
    return lst


class CustomOverlayTab(QWidget):
    def __init__(self, watcher: WindowWatcher) -> None:
        super().__init__()
        self._watcher = watcher
        # 미러 표시 조건: (1) 게임이 포그라운드 = 실제 사용 중, 또는
        # (2) 우리 앱이 포그라운드 '이면서 이 커스텀 오버레이 탭을 보고 있을 때' = 위치
        #     조정(세팅) 중. → 다른 탭·다른 작업 중엔 안 떠서 화면을 가리지 않고 커서
        #     깜빡임도 없다. 이 탭에서 미러를 클릭해 드래그해도 탭이 보이는 상태라 안 숨음.
        self._game_hwnd = 0  # DWM 미러 소스(게임 창) 캐시
        self._mgr = MirrorManager(
            fps=60,  # mss 폴백 경로에서만 쓰임(Windows는 DWM 썸네일 → fps 무관).
            is_active=lambda: (
                watcher.is_game_active()
                or (watcher.is_self_active() and self.isVisible())
            ),
            # Windows: 게임 창을 소스로 DWM 썸네일 미러(CPU ~0%). 못 찾으면 mss 폴백.
            source_hwnd=self._find_game_hwnd,
            # 호환 캡처 모드: 전체창+특정 GPU(MPO)에서 DWM 미러가 검정/멈춤일 때 켜면
            # 항상 캡처(mss)로 그린다.
            force_capture=config.load_mirror_force_capture(),
            parent=self,
        )
        self._active_preset: str | None = None
        self._changing_preset = False
        self._editing_lock = False
        self._dirty = False
        self._save_error = ""
        self._last_saved = []
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(300)
        self._save_timer.timeout.connect(self.flush_pending)
        self._mgr.changed.connect(self._save_current)
        self._mgr.overlay_moved.connect(self._save_current)
        self._pending_name = "화면"
        self._selector = None

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        # 세로 여유가 뷰포트와 거의 딱 맞아(≈9px) Windows 글꼴/DPI에선 아주 얇은
        # 스크롤바가 생겼다. 위젯 간격을 살짝 줄여 그만큼의 여유를 확보한다.
        v.setSpacing(8)

        v.addWidget(tab_header(
            "게임 화면의 일부를 복제해 원하는 위치에 표시합니다.",
            HELP_TITLE, HELP_HTML, self
        ))
        from .widgets import feature_checkbox
        self._paused = False
        self.enable = feature_checkbox("custom", "커스텀 오버레이 사용")
        self.enable.toggled.connect(self._on_enable)
        v.addWidget(self.enable)
        self._mgr.set_paused(not self.enable.isChecked())
        self.region_btn = QPushButton("복제할 영역 추가")
        self.region_btn.setToolTip("드래그로 화면 일부를 잘라 오버레이로 복제(돋보기)")
        self.region_btn.clicked.connect(self._on_region)
        row = QHBoxLayout()
        row.addWidget(self.region_btn)
        row.addStretch()
        v.addLayout(row)

        row = QHBoxLayout()
        self.active_label = CapturePathLabel()
        self.active_label.setStyleSheet("")
        self.save_status = QLabel()
        self.save_btn = QPushButton("다른 이름으로 저장...")
        self.save_btn.clicked.connect(self._on_preset_save)
        row.addWidget(self.active_label, 1)
        row.addWidget(self.save_status)
        row.addWidget(self.save_btn)
        v.addLayout(row)
        self.error_box = QWidget()
        error_row = QHBoxLayout(self.error_box)
        self.error_label = CapturePathLabel()
        self.error_label.setStyleSheet("")
        self.retry_btn = QPushButton("다시 저장")
        self.retry_btn.clicked.connect(self.flush_pending)
        error_row.addWidget(self.error_label, 1)
        error_row.addWidget(self.retry_btn)
        self.error_box.setStyleSheet("color:#c0392b; background:#fdecea;")
        v.addWidget(self.error_box)
        self.error_box.hide()

        # 프리셋
        v.addWidget(section_label("프리셋"))
        self.preset_list = _name_list()
        self.preset_list.setMaximumHeight(128)
        self.preset_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        v.addWidget(self.preset_list, 1)
        preset_row = QHBoxLayout()
        self.preset_load_btn = QPushButton("불러오기")
        self.preset_load_btn.clicked.connect(self._on_preset_load)
        self.preset_delete_btn = QPushButton("선택 프리셋 삭제")
        self.preset_delete_btn.setStyleSheet(_DANGER_QSS)
        self.preset_delete_btn.clicked.connect(self._on_preset_delete)
        preset_row.addWidget(self.preset_load_btn)
        preset_row.addWidget(self.preset_delete_btn)
        self.selection_label = CapturePathLabel()
        self.selection_label.setText("선택: 없음")
        preset_row.addWidget(self.selection_label, 1)
        v.addLayout(preset_row)

        # 시작 대상은 적용 대상이나 목록 선택과 별도로 저장한다.
        row = QHBoxLayout()
        row.addWidget(QLabel("시작 시 자동 불러오기"))
        self.auto_combo = QComboBox()
        self.auto_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.auto_combo.setMinimumContentsLength(12)
        self.auto_combo.currentIndexChanged.connect(self._on_auto_changed)
        row.addWidget(self.auto_combo, 1)
        v.addLayout(row)
        self.preset_list.itemSelectionChanged.connect(self._selection_changed)

        # 오버레이 목록(선택만)
        self.overlays_title = CapturePathLabel()
        self.overlays_title.setStyleSheet("font-weight:600; color:#c8ccd4;")
        self.overlays_title.setText("적용 중인 오버레이")
        v.addWidget(self.overlays_title)
        self.overlay_list = QTreeWidget()
        self.overlay_list.setRootIsDecorated(False)
        self.overlay_list.setMinimumHeight(100)
        self.overlay_list.setMaximumHeight(160)
        self.overlay_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.overlay_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.overlay_list.setHeaderLabels(["이름", "원본 영역", "표시 배율", "위치 잠금"])
        self.overlay_list.setStyleSheet(_LIST_QSS.replace("QListWidget", "QTreeWidget"))
        self.overlay_list.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.overlay_list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.overlay_list.itemChanged.connect(self._on_item_lock)
        v.addWidget(self.overlay_list, 2)

        # 호환 캡처 모드: 미러가 검정/멈춤(고정)으로 나올 때 켠다. '전체 창 모드' + 특정
        # GPU(MPO)에서 DWM 미러가 안 그려지는 경우를 캡처 방식으로 우회(CPU 약간↑).
        self.compat_chk = checkbox("호환 캡처 모드 (미러가 검정·멈춤으로 나올 때 켜세요)")
        self.compat_chk.setChecked(config.load_mirror_force_capture())
        self.compat_chk.toggled.connect(self._on_compat_toggled)

        # 선택/전체 명령을 행으로 구분한다.
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        for c in range(4):
            grid.setColumnStretch(c, 1)
        self.sel_lock_btn = QPushButton("선택 잠금")
        self.sel_lock_btn.clicked.connect(lambda: self._lock_selected(True))
        self.sel_unlock_btn = QPushButton("선택 잠금 해제")
        self.sel_unlock_btn.clicked.connect(lambda: self._lock_selected(False))
        self.del_sel_btn = QPushButton("선택 삭제")
        self.del_sel_btn.setStyleSheet(_DANGER_QSS)
        self.del_sel_btn.clicked.connect(self._on_delete_selected)
        self.del_all_btn = QPushButton("전체 삭제")
        self.del_all_btn.setStyleSheet(_DANGER_QSS)
        self.del_all_btn.clicked.connect(self._on_delete_all)
        self.lock_all_btn = QPushButton("전체 잠금")
        self.lock_all_btn.clicked.connect(lambda: self._mgr.set_locked_all(True))
        self.unlock_all_btn = QPushButton("전체 잠금 해제")
        self.unlock_all_btn.clicked.connect(lambda: self._mgr.set_locked_all(False))
        grid.addWidget(self.sel_lock_btn, 0, 0)
        grid.addWidget(self.sel_unlock_btn, 0, 1)
        grid.addWidget(self.del_sel_btn, 0, 2)
        grid.addWidget(self.lock_all_btn, 1, 0)
        grid.addWidget(self.unlock_all_btn, 1, 1)
        grid.addWidget(self.del_all_btn, 1, 2)
        v.addLayout(grid)
        self.advanced_btn = QToolButton()
        self.advanced_btn.setText("고급 · 캡처 호환성")
        self.advanced_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_btn.setCheckable(True)
        self.advanced_btn.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_btn.toggled.connect(self._show_advanced)
        v.addWidget(self.advanced_btn)
        v.addWidget(self.compat_chk)
        self.compat_chk.hide()
        v.addStretch()

        self._refresh_presets()
        self._refresh_overlays()
        self._auto_load_startup()  # 시작 시 자동 프리셋 불러오기
        self._update_save_status()

    def _show_advanced(self, checked):
        self.compat_chk.setVisible(checked)
        self.advanced_btn.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    # ---- 시작 시 자동 불러오기 ----
    def _find_game_hwnd(self) -> int:
        """DWM 미러 소스로 쓸 게임 창 HWND(캐시; 무효화되면 다시 찾는다). 0=못 찾음."""
        from ..system import dwm_thumbnail
        from ..system.window_watcher import DEFAULT_GAME_TITLES

        cached = getattr(self, "_game_hwnd", 0)  # __init__ 순서와 무관하게 안전
        if cached and dwm_thumbnail.window_rect(cached):
            return cached  # 아직 유효 → 재탐색 생략(EnumWindows 비용 회피)
        self._game_hwnd = dwm_thumbnail.find_game_window(
            config.load_game_exe(), DEFAULT_GAME_TITLES
        )
        return self._game_hwnd

    def _auto_load_startup(self) -> None:
        name = config.load_auto_preset()
        if not name:
            return
        if name in config.load_custom_presets():
            self._apply_preset(name)

    def _selection_changed(self) -> None:
        rows = self._selected_rows(self.preset_list)
        self.selection_label.setText("선택: " + (self._preset_name(rows[0]) if rows else "없음"))
        self.preset_load_btn.setEnabled(bool(rows))
        self.preset_delete_btn.setEnabled(bool(rows))

    def _on_auto_changed(self) -> None:
        try:
            config.save_auto_preset(self.auto_combo.currentData())
        except OSError:
            self._info("시작 시 자동 불러오기 설정을 저장하지 못했습니다.")
        self._refresh_presets()

    def _on_compat_toggled(self, checked: bool) -> None:
        config.save_mirror_force_capture(checked)
        self._mgr.set_force_capture(checked)

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
        if self._editing_lock:
            return
        selected = self._selected_rows(self.overlay_list)
        with QSignalBlocker(self.overlay_list):
            self.overlay_list.clear()
            for i, data in enumerate(self._mgr.to_dicts()):
                item = QTreeWidgetItem([
                    data.get("name") or f"오버레이{i + 1}",
                    "{x}, {y} · {w} × {h}".format(**data),
                    f"{round(data.get('scale', 1) * 100)}%", "",
                ])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(3, Qt.CheckState.Checked if data.get("locked") else Qt.CheckState.Unchecked)
                self.overlay_list.addTopLevelItem(item)
                item.setToolTip(0, item.text(0))
                item.setToolTip(1, item.text(1))
                item.setSelected(i in selected)

    def _on_item_lock(self, item, column):
        if column == 3:
            self._editing_lock = True
            try:
                self._mgr.set_locked([self.overlay_list.indexOfTopLevelItem(item)],
                                     item.checkState(3) == Qt.CheckState.Checked)
            finally:
                self._editing_lock = False

    def _refresh_presets(self) -> None:
        rows = self._selected_rows(self.preset_list)
        selected = self._preset_name(rows[0]) if rows else None
        auto = config.load_auto_preset()
        with QSignalBlocker(self.preset_list), QSignalBlocker(self.auto_combo):
            self.preset_list.clear()
            self.auto_combo.clear()
            self.auto_combo.addItem("사용 안 함", None)
            for name in sorted(config.load_custom_presets()):
                tags = []
                if name == self._active_preset:
                    tags.append("적용 중")
                if name == auto:
                    tags.append("시작 시 자동 불러오기")
                item = QListWidgetItem(" · ".join([name, *tags]))
                item.setData(Qt.ItemDataRole.UserRole, name)
                item.setToolTip(item.text())
                self.preset_list.addItem(item)
                if name == selected:
                    item.setSelected(True)
                self.auto_combo.addItem(name, name)
            self.auto_combo.setCurrentIndex(max(0, self.auto_combo.findData(auto)))
        self._selection_changed()

    def _preset_name(self, row: int) -> str:
        return self.preset_list.item(row).data(Qt.ItemDataRole.UserRole)

    def _selected_rows(self, lst) -> list[int]:
        row = lst.indexOfTopLevelItem if isinstance(lst, QTreeWidget) else lst.row
        return sorted(row(i) for i in lst.selectedItems())

    def _save_current(self) -> None:
        if self._changing_preset:
            return
        self._refresh_overlays()
        if self._mgr.to_dicts() == self._last_saved and not self._save_error:
            return
        self._dirty = True
        self._save_timer.start()
        self._update_save_status()

    def _update_save_status(self):
        name = self._active_preset or "없음"
        self.active_label.setText(f"적용 중: {name}")
        self.overlays_title.setText("적용 중인 오버레이 · " + name)
        self.save_status.setText("저장 실패" if self._save_error else "저장 대기 중" if self._dirty else "자동 저장됨")
        self.save_status.setStyleSheet("color:#c0392b;" if self._save_error else "")
        self.error_box.setVisible(bool(self._save_error))
        self.error_label.setText(
            f"{name}의 변경 내용을 저장하지 못했습니다. 프리셋 전환·종료 보류. "
            "현재 편집 내용 유지 · 마지막 정상 저장본 보존")
        self.error_label.setToolTip(self._save_error)

    def _save_failed(self, error):
        self._dirty = True
        self._save_error = str(error)
        _log.warning("커스텀 오버레이 저장 실패: %s", error)
        self._update_save_status()

    def flush_pending(self) -> bool:
        self._save_timer.stop()
        if not self._dirty:
            return True
        items = self._mgr.to_dicts()
        try:
            config.save_custom_edit(items, self._active_preset)
        except OSError as error:
            self._save_failed(error)
            return False
        self._last_saved = deepcopy(items)
        self._dirty = False
        self._save_error = ""
        self._update_save_status()
        return True

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
        # Stop the debounce across the modal dialog so cancellation cannot write a preset.
        pending = self._save_timer.isActive()
        self._save_timer.stop()
        name, ok = QInputDialog.getText(self, "다른 이름으로 저장",
                                       f"새 프리셋 이름 (현재 적용: {self._active_preset or '없음'})")
        name = name.strip()
        if not ok or not name:
            if pending:
                self._save_timer.start()
            return
        if name in config.load_custom_presets() and not self._confirm(
            "프리셋 덮어쓰기", f"'{name}' 프리셋을 덮어쓸까요?"
        ):
            if pending:
                self._save_timer.start()
            return
        items = self._mgr.to_dicts()
        try:
            config.save_custom_edit(items, name, self._active_preset)
        except OSError as error:
            self._save_failed(error)
            return
        self._active_preset = name
        self._last_saved = deepcopy(items)
        self._dirty = False
        self._save_error = ""
        self._update_save_status()
        self._refresh_presets()

    def _on_preset_load(self) -> None:
        rows = self._selected_rows(self.preset_list)
        if not rows:
            return
        self._apply_preset(self._preset_name(rows[0]))

    def _apply_preset(self, name) -> bool:
        if not self.flush_pending():
            return False
        items = config.load_custom_presets().get(name)
        if items is None:
            return False
        previous = self._mgr.to_dicts()
        self._changing_preset = True
        try:
            self._mgr.load(items)
            current = self._mgr.to_dicts()
            config.save_custom_edit(current, name)
        except (OSError, ValueError, TypeError, KeyError) as error:
            self._mgr.load(previous)
            self._save_failed(error)
            return False
        finally:
            self._changing_preset = False
            self._refresh_overlays()
        self._active_preset = name
        self._last_saved = deepcopy(current)
        self._dirty = False
        self._save_error = ""
        self._update_save_status()
        self._refresh_presets()
        return True

    def _on_preset_delete(self) -> None:
        rows = self._selected_rows(self.preset_list)
        if not rows:
            return
        name = self._preset_name(rows[0])
        if self._confirm("프리셋 삭제", f"'{name}' 프리셋을 삭제할까요?"):
            if not self.flush_pending():
                return
            try:
                config.delete_custom_preset(name)
            except OSError as error:
                _log.warning("커스텀 프리셋 삭제 실패: %s", error)
                self._info(f"'{name}' 프리셋을 삭제하지 못했습니다. 기존 프리셋과 적용 상태를 유지합니다.")
                return
            if name == self._active_preset:
                self._active_preset = None
            self._update_save_status()
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
        self._paused = paused
        self._mgr.set_paused(paused or not self.enable.isChecked())

    def _on_enable(self, value):
        self._mgr.set_paused(self._paused or not self.enable.isChecked())

    def shutdown(self) -> None:
        if not self.flush_pending():
            return
        self._save_timer.stop()
        self._mgr.shutdown()
