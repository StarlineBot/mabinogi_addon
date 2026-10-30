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
    QHBoxLayout,
    QInputDialog,
    QListWidget,
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
    QGroupBox,
)

from .palette import color
from .. import config
from ..system.window_watcher import WindowWatcher
from .help_dialog import tab_header
from .mirror_manager import MirrorManager
from .widgets import CapturePathLabel, checkbox, hint_label
from .settings_layout import danger_style, lock_button, set_lock_text

_log = logging.getLogger(__name__)

# 커스텀 오버레이 사용법(? 아이콘 → 새 창).
from .feature_copy import HELP

HELP_TITLE = '커스텀 오버레이 사용법'
HELP_HTML = HELP['커스텀 오버레이']

# 외곽 테두리 + 최소 높이 → 비어 있어도 '여기 리스트가 있다'가 보이게.
# outline:0 → 선택 시 생기는 포커스 박스(버튼처럼 보이던 테두리) 제거해 '리스트' 느낌.
def _list_qss():
    return f"""
QListWidget {{ border:1px solid palette(mid); border-radius:6px; background:palette(base);
  min-height:72px; outline:0; }}
QListWidget::item {{ padding:7px 10px; border:none; }}
QListWidget::item:hover {{ background:palette(midlight); }}
QListWidget::item:selected {{ background:{color('accent')}; color:{color('on-accent')}; }}
"""


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
    lst.setStyleSheet(_list_qss())
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
        self._writes_suspended = False
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
            "게임 화면의 일부를 복제해 원하는 위치에 표시해요.",
            HELP_TITLE, HELP_HTML, self
        ))
        from .widgets import feature_switch
        self._paused = False
        self.enable = feature_switch("custom", "커스텀 오버레이 사용")  # 기능 켜기 = 스위치(명세 14.5)
        self.enable.toggled.connect(self._on_enable)
        v.addWidget(self.enable)
        self._mgr.set_paused(not self.enable.isChecked())
        # 프리셋(명세 11.2): 1줄 선택·불러오기·관리, 2줄 현재 프리셋 · 자동 저장 + 다른 이름으로 저장(안내 2줄 삭제)
        preset_box = QGroupBox("프리셋")
        preset_box_layout = QVBoxLayout(preset_box)
        preset_row = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.preset_combo.setMinimumContentsLength(8)
        preset_row.addWidget(self.preset_combo, 1)
        self.preset_load_btn = QPushButton("불러오기")
        self.preset_load_btn.clicked.connect(self._on_preset_load)
        preset_row.addWidget(self.preset_load_btn)
        preset_row.addStretch()
        self.preset_manage_btn = QToolButton()
        self.preset_manage_btn.setText("프리셋 관리")
        self.preset_manage_btn.setCheckable(True)
        preset_row.addWidget(self.preset_manage_btn)
        preset_box_layout.addLayout(preset_row)
        row = QHBoxLayout()
        self.active_label = CapturePathLabel()
        self.active_label.setStyleSheet("")
        self.save_status = QLabel()
        self.save_btn = QPushButton("다른 이름으로 저장...")
        self.save_btn.clicked.connect(self._on_preset_save)
        row.addWidget(self.active_label, 1)
        row.addWidget(self.save_status)
        row.addWidget(self.save_btn)
        preset_box_layout.addLayout(row)
        self.error_box = QWidget()
        error_row = QHBoxLayout(self.error_box)
        self.error_label = CapturePathLabel()
        self.error_label.setStyleSheet("")
        self.retry_btn = QPushButton("다시 저장")
        self.retry_btn.clicked.connect(self.flush_pending)
        error_row.addWidget(self.error_label, 1)
        error_row.addWidget(self.retry_btn)
        self.error_box.setStyleSheet(f"color:{color('danger')}; background:#fdecea;")
        preset_box_layout.addWidget(self.error_box)
        self.error_box.hide()
        preset_group = QWidget()  # 프리셋 관리(펼침): 삭제·시작 시 자동 불러오기
        preset_layout = QVBoxLayout(preset_group)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_row = QHBoxLayout()
        self.preset_delete_btn = QPushButton("선택 프리셋 삭제")
        self.preset_delete_btn.setStyleSheet(danger_style())
        self.preset_delete_btn.clicked.connect(self._on_preset_delete)
        preset_row.addWidget(self.preset_delete_btn)
        self.selection_label = CapturePathLabel()
        self.selection_label.setText("선택: 없음")
        preset_row.addWidget(self.selection_label, 1)
        preset_layout.addLayout(preset_row)
        # 시작 대상은 적용 대상이나 목록 선택과 별도로 저장한다.
        row = QHBoxLayout()
        row.addWidget(QLabel("시작 시 자동 불러오기"))
        self.auto_combo = QComboBox()
        self.auto_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.auto_combo.setMinimumContentsLength(12)
        self.auto_combo.currentIndexChanged.connect(self._on_auto_changed)
        row.addWidget(self.auto_combo, 1)
        preset_layout.addLayout(row)
        preset_box_layout.addWidget(preset_group)
        preset_group.hide()
        self.preset_manage_btn.toggled.connect(preset_group.setVisible)
        self.preset_combo.currentIndexChanged.connect(self._selection_changed)
        v.addWidget(preset_box)

        # 오버레이(명세 11.2): 비었을 때는 점선 안내, 있을 때 추가·전체 잠금 + 표 + 선택 삭제. 표의 잠금 칸 = 하나씩 잠금/해제
        overlay_group = QGroupBox("오버레이")
        overlay_layout = QVBoxLayout(overlay_group)
        v.addWidget(overlay_group)
        self.region_btn = QPushButton("＋ 복제할 영역 추가")
        self.region_btn.setToolTip("드래그로 화면 일부를 잘라 오버레이로 복제(돋보기)")
        self.region_btn.clicked.connect(self._on_region)
        self.lock_all_btn = lock_button(every=True)
        self.lock_all_btn.clicked.connect(lambda checked: self._mgr.set_locked_all(checked))
        row = QHBoxLayout()
        row.addWidget(self.region_btn)
        row.addStretch()
        row.addWidget(self.lock_all_btn)
        overlay_layout.addLayout(row)
        self.empty_hint = QLabel("아직 오버레이가 없어요. ‘복제할 영역 추가’로 게임 화면 일부를 골라 원하는 위치에 띄워 보세요.")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setStyleSheet(f"color:{color('muted')}; border:1px dashed {color('muted')}; border-radius:4px; padding:14px;")
        overlay_layout.addWidget(self.empty_hint)
        self.overlays_title = CapturePathLabel()  # 설정 교체(재시작 대기) 때만 보임
        self.overlays_title.setStyleSheet("font-weight:600;")
        self.overlays_title.setText("적용 중인 오버레이")
        self.overlays_title.hide()
        overlay_layout.addWidget(self.overlays_title)
        self.overlay_list = QTreeWidget()
        self.overlay_list.setRootIsDecorated(False)
        self.overlay_list.setMinimumHeight(100)
        self.overlay_list.setMaximumHeight(160)
        self.overlay_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.overlay_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.overlay_list.setHeaderLabels(["이름", "원본 영역", "표시 배율", "위치 잠금"])
        self.overlay_list.setStyleSheet(_list_qss().replace("QListWidget", "QTreeWidget"))
        self.overlay_list.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.overlay_list.header().setMinimumSectionSize(85)
        self.overlay_list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.overlay_list.itemClicked.connect(self._on_item_lock)
        self.overlay_list.itemSelectionChanged.connect(self._update_commands)
        overlay_layout.addWidget(self.overlay_list)
        row = QHBoxLayout()
        self.del_sel_btn = QPushButton("선택 삭제")
        self.del_sel_btn.setStyleSheet(danger_style())
        self.del_sel_btn.clicked.connect(self._on_delete_selected)
        row.addWidget(self.del_sel_btn)
        row.addStretch()
        overlay_layout.addLayout(row)
        self.list_hint = hint_label("표의 위치 잠금 칸을 눌러 하나씩 잠그거나 풀 수 있어요. 잠금을 풀면 마우스 휠로 크기를 바꿀 수 있어요.")
        overlay_layout.addWidget(self.list_hint)
        self._populated_widgets = (self.lock_all_btn, self.overlay_list, self.del_sel_btn, self.list_hint)

        # 호환 캡처 모드: 미러가 검정/멈춤(고정)으로 나올 때 켠다. '전체 창 모드' + 특정
        # GPU(MPO)에서 DWM 미러가 안 그려지는 경우를 캡처 방식으로 우회(CPU 약간↑).
        self.compat_chk = checkbox("호환 캡처 모드 (미러가 검정·멈춤으로 나올 때 켜세요)")
        self.compat_chk.setChecked(config.load_mirror_force_capture())
        self.compat_chk.toggled.connect(self._on_compat_toggled)
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
        name = self.preset_combo.currentData()
        self.selection_label.setText("선택 프리셋: " + (name or "없음"))
        self.preset_load_btn.setEnabled(bool(name))
        self.preset_delete_btn.setEnabled(bool(name))

    def _update_commands(self):
        selected = bool(self.overlay_list.selectedItems())
        populated = self.overlay_list.topLevelItemCount() > 0
        self.del_sel_btn.setEnabled(selected)
        self.lock_all_btn.setEnabled(populated)
        locked = populated and all(o.get("locked") for o in self._mgr.to_dicts())
        self.lock_all_btn.setChecked(locked)
        set_lock_text(self.lock_all_btn, locked)
        for widget in self._populated_widgets:  # 비었으면 표·버튼 대신 점선 안내(명세 11.2)
            widget.setVisible(populated)
        self.empty_hint.setVisible(not populated)

    def _on_auto_changed(self) -> None:
        if self._writes_suspended:
            return
        try:
            config.save_auto_preset(self.auto_combo.currentData())
        except OSError:
            self._info("시작 시 자동 불러오기 설정을 저장하지 못했어요.")
        self._refresh_presets()

    def _on_compat_toggled(self, checked: bool) -> None:
        if self._writes_suspended:
            return
        config.save_mirror_force_capture(checked)
        self._mgr.set_force_capture(checked)

    # ---- 영역 지정 → 오버레이 추가 ----
    def _on_region(self) -> None:
        if self._writes_suspended:
            return
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
        if self._writes_suspended:
            return
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
                    f"{round(data.get('scale', 1) * 100)}%", "잠금됨" if data.get("locked") else "잠금 해제",
                ])
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                self.overlay_list.addTopLevelItem(item)
                item.setToolTip(0, item.text(0))
                item.setToolTip(1, item.text(1))
                item.setSelected(i in selected)
        self._update_commands()

    def _on_item_lock(self, item, column):
        """표의 '위치 잠금' 칸을 누르면 그 오버레이만 잠금/해제(명세 11.2 신규 동작)."""
        if column != 3 or self._writes_suspended:
            return
        index = self.overlay_list.indexOfTopLevelItem(item)
        overlays = self._mgr.to_dicts()
        if not 0 <= index < len(overlays):
            return
        locked = not overlays[index].get("locked")
        self._editing_lock = True  # 목록을 다시 만들지 않아 선택·스크롤이 그대로 남는다
        try:
            self._mgr.set_locked([index], locked)
        finally:
            self._editing_lock = False
        item.setText(3, "잠금됨" if locked else "잠금 해제")
        self._update_commands()

    def _refresh_presets(self) -> None:
        selected = self.preset_combo.currentData()
        auto = config.load_auto_preset()
        with QSignalBlocker(self.preset_combo), QSignalBlocker(self.auto_combo):
            self.preset_combo.clear()
            self.preset_combo.addItem("선택 안 함", None)
            self.auto_combo.clear()
            self.auto_combo.addItem("사용 안 함", None)
            for name in sorted(config.load_custom_presets()):
                tags = []
                if name == self._active_preset:
                    tags.append("적용 중")
                if name == auto:
                    tags.append("시작 시 자동 불러오기")
                self.preset_combo.addItem(" · ".join([name, *tags]), name)
                self.auto_combo.addItem(name, name)
            self.auto_combo.setCurrentIndex(max(0, self.auto_combo.findData(auto)))
            self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(selected)))
        self._selection_changed()

    def _preset_name(self, row: int) -> str:
        return self.preset_combo.itemData(row)

    def _selected_rows(self, lst) -> list[int]:
        row = lst.indexOfTopLevelItem if isinstance(lst, QTreeWidget) else lst.row
        return sorted(row(i) for i in lst.selectedItems())

    def _save_current(self) -> None:
        if self._writes_suspended or self._changing_preset:
            return
        self._refresh_overlays()
        if self._mgr.to_dicts() == self._last_saved and not self._save_error:
            return
        self._dirty = True
        self._save_timer.start()
        self._update_save_status()

    def _update_save_status(self):
        if self._writes_suspended:
            self.active_label.setText("설정이 교체되었어요")
            self.overlays_title.setText("적용 중인 오버레이 · 재시작 대기")
            self.overlays_title.show()
            self.save_status.setText("재시작 필요")
            self.save_status.setStyleSheet("")
            self.error_box.hide()
            return
        name = self._active_preset or "이름 없는 구성"
        self.active_label.setText(f"현재: {name} · 바꾸면 자동 저장돼요")
        self.overlays_title.hide()
        self.save_status.setText("저장 실패" if self._save_error else "저장 대기 중" if self._dirty else "")
        self.save_status.setStyleSheet(f"color:{color('danger')};" if self._save_error else "")
        self.error_box.setVisible(bool(self._save_error))
        self.error_label.setText(
            f"{name}의 변경 내용을 저장하지 못했어요. 프리셋 전환·종료 보류. "
            "현재 편집 내용 유지 · 마지막 정상 저장본 보존")
        self.error_label.setToolTip(self._save_error)

    def _save_failed(self, error):
        self._dirty = True
        self._save_error = str(error)
        _log.warning("커스텀 오버레이 저장 실패: %s", error)
        self._update_save_status()

    def flush_pending(self) -> bool:
        self._save_timer.stop()
        if self._writes_suspended:
            return True
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
    def _on_delete_selected(self) -> None:
        rows = self._selected_rows(self.overlay_list)
        names = [self.overlay_list.topLevelItem(i).text(0) for i in rows]
        summary = "\n".join(name[:80] for name in names[:8])
        if len(names) > 8:
            summary += f"\n외 {len(names)-8}개"
        if rows and self._confirm("선택 오버레이 삭제", "다음 오버레이를 삭제할까요?\n" + summary):
            self._mgr.remove_indices(rows)

    # ---- 프리셋 버튼 ----
    def _on_preset_save(self) -> None:
        if self._writes_suspended:
            return
        # Stop the debounce across the modal dialog so cancellation cannot write a preset.
        pending = self._save_timer.isActive()
        self._save_timer.stop()
        name, ok = QInputDialog.getText(self, "다른 이름으로 저장",
                                       f"새 프리셋 이름 (현재 적용: {self._active_preset or '없음'})")
        name = name.strip()
        if self._writes_suspended:
            return
        if not ok or not name:
            if pending:
                self._save_timer.start()
            return
        if name in config.load_custom_presets():
            confirmed = self._confirm("프리셋 덮어쓰기", f"'{name}' 프리셋을 덮어쓸까요?")
            if self._writes_suspended:
                return
            if not confirmed:
                if pending:
                    self._save_timer.start()
                return
        items = self._mgr.to_dicts()
        if self._writes_suspended:
            return
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
        name = self.preset_combo.currentData()
        if not name:
            return
        self._apply_preset(name)

    def _apply_preset(self, name) -> bool:
        if self._writes_suspended:
            return False
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
        if self._writes_suspended:
            return
        name = self.preset_combo.currentData()
        if not name:
            return
        if self._confirm("프리셋 삭제", f"'{name}' 프리셋을 삭제할까요?"):
            if self._writes_suspended:
                return
            if not self.flush_pending():
                return
            try:
                config.delete_custom_preset(name)
            except OSError as error:
                _log.warning("커스텀 프리셋 삭제 실패: %s", error)
                self._info(f"'{name}' 프리셋을 삭제하지 못했어요. 기존 프리셋과 적용 상태를 유지해요.")
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
        self._mgr.set_paused(self._writes_suspended or paused or not self.enable.isChecked())

    def _on_enable(self, value):
        self._mgr.set_paused(self._writes_suspended or self._paused or not self.enable.isChecked())

    def suspend_for_config_replacement(self) -> None:
        """A successful import/reset supersedes this session's pending composition."""
        self._writes_suspended = True
        self._save_timer.stop()
        self._dirty = False
        self._save_error = ""
        self._active_preset = None
        if self._selector is not None:
            self._selector.close()
        self._mgr.set_paused(True)
        self._mgr.shutdown()
        self._refresh_overlays()
        self.setEnabled(False)
        self._update_save_status()

    def shutdown(self) -> None:
        if not self.flush_pending():
            return
        self._save_timer.stop()
        self._mgr.shutdown()
