"""버프 탭 (기획서 5.1 상단).

목록 = 등록된 버프(카탈로그, 아이콘·이미지 폴더 기반). 앵커(premium_battle)는 최상단 고정.
버프별 설정(지속시간 표시·종료 알림)과 표시 순서를 config.local.json에 저장한다.
- − : 오버레이에서 숨김(목록에서 빠짐) / + : 숨긴 버프 다시 표시 / ▲▼ : 표시 순서
- 새 버프는 아이콘·이미지 파일을 추가하면 목록에 자동 등장한다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .palette import color
from .. import catalog as catalog_mod
from .. import config
from ..catalog import BuffDef, available_catalog
from .dpi import to_logical
from .screen_grab import capture_for_autofind
from .widgets import TrackerColumns, callout, checkbox, hint_label, icon_slot, section_label
from .settings_layout import lock_text, style_toggle, danger_style

# 앵커로 고정 사용할 버프(항상 존재, 지속시간 없음 → 판정 기준)
ANCHOR_ID = "premium_battle"

# 영역에 꼭 들어가야 하는 것(앱 힌트 ↔ 화면 점선 라벨이 같은 기준을 공유).
REGION_CRITERION = "버프 아이콘 + 남은시간이 함께 보이게 드래그하세요"
# 판독 영역 안내(기획서 3.1.1 — 0.33.0 전체 공개: 모든 사용자가 구분선 위·아래를 함께 읽는다)
REGION_GUIDE = "상태목록창을 맨 위(즐겨찾기 칸 포함)부터 지정하세요. 즐겨찾기 칸은 구분선을 찾아 따로 읽어요."
HIGHLIGHT_TITLE = "버프 영역 확인"
HIGHLIGHT_SUB = "아이콘 + 남은시간이 점선 안에 다 들어왔나요?"

# 버프 트래커 사용법(? 버튼 → 새 창). 내용만 바꾸면 다른 탭에도 재사용 가능.
from .feature_copy import HELP

HELP_TITLE = '버프 트래커 사용법'
HELP_HTML = HELP['버프 트래커']


def _capture_icon_to(tab: QWidget, item_id: str, on_done) -> None:
    """전체화면 선택창(돋보기)으로 아이콘을 드래그해 임시 PNG로 저장한다.

    저장이 끝나면 on_done(item_id, tmp_path, ok)를 호출한다. 선택창은 GC되지 않도록
    탭에 참조(_icon_selector)를 붙여 둔다.
    """
    import tempfile

    from .region_selector import RegionSelector

    tmp = Path(tempfile.gettempdir()) / f"_mabi_icon_{item_id}.png"
    selector = RegionSelector(save_path=tmp)
    tab._icon_selector = selector  # 참조 유지(GC 방지)
    selector.captured.connect(lambda ok: on_done(item_id, tmp, ok))
    selector.start()


def _pixmap(path: Path | None, size: int) -> QPixmap | None:
    if path is None:
        return None
    pm = QPixmap(str(path))
    if pm.isNull():
        return None
    return pm.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )


class BuffTab(QWidget):
    lock_toggled = Signal(bool)  # 오버레이 고정 토글 → main이 오버레이에 적용
    tracking_changed = Signal()  # 순서·노출·지속시간·알림 변경 → 라이브 반영(재시작 X)
    catalog_changed = Signal()  # 버프 추가·삭제·아이콘 변경 → 엔진 재구성 필요
    scale_changed = Signal(int)  # 오버레이 배율(%) 변경
    opacity_changed = Signal(int)  # 오버레이 불투명도(%) 변경(명세 15절)
    window_visible_changed = Signal(bool)  # '오버레이 창 보이기'(0.32.0)

    def __init__(self) -> None:
        super().__init__()
        from .notifier import default_sound_map

        self._catalog: dict[str, BuffDef] = {b.id: b for b in available_catalog()}
        self._sound_ids = set(default_sound_map())  # 사운드 파일이 있는 버프만
        self._settings, self._order = self._load_state()
        self._current: str | None = None
        self._name_id: str | None = None
        self._loading = False

        from .help_dialog import tab_header

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)
        outer.addWidget(tab_header(
            "등록한 버프의 남은 시간을 오버레이로 표시", HELP_TITLE, HELP_HTML, self
        ))
        list_panel = self._build_list_panel()
        self._buff_editor = self._build_form_panel()
        self.form_panel = QWidget()
        form_layout = QVBoxLayout(self.form_panel)
        form_layout.setContentsMargins(0, 0, 0, 0)
        self._form_stack = QStackedWidget()
        form_layout.addWidget(self._form_stack)
        self._form_stack.addWidget(self._buff_editor)
        self.anchor_panel = QWidget()
        anchor_layout = QVBoxLayout(self.anchor_panel)
        anchor_layout.setContentsMargins(0, 0, 0, 0)
        anchor_layout.addWidget(section_label("기준 버프"))
        self.anchor_icon = icon_slot()
        anchor_layout.addWidget(self.anchor_icon)
        self.anchor_name = QLabel()
        self.anchor_name.setWordWrap(True)
        anchor_layout.addWidget(self.anchor_name)
        anchor_layout.addWidget(hint_label(
            "버프 트래커가 상태목록 위치를 찾을 때 사용하는 기준 버프예요.\n\n"
            "판독 영역 안에 이 버프가 포함되어야 해요.\n\n"
            "기준 버프 자체는 오버레이에 표시하거나 개별 알림을 설정하지 않아요.\n\n"
            "표시·알림을 설정하려면 왼쪽 목록에서 일반 버프를 선택하세요."))
        anchor_layout.addStretch()
        self._form_stack.addWidget(self.anchor_panel)
        self._empty_panel = QLabel("설정할 버프를 선택하세요.")
        self._empty_panel.setWordWrap(True)
        self._form_stack.addWidget(self._empty_panel)
        self._columns = TrackerColumns(list_panel, self.form_panel)
        outer.addLayout(self._columns, 1)

        self._rebuild_list()
        self.buff_list.setCurrentRow(0)

    # ---- 상태(카탈로그 + 저장된 설정) ----
    def _load_state(self) -> tuple[dict[str, config.BuffSettings], list[str]]:
        saved = config.load_buff_settings()
        settings = {s.id: s for s in saved}
        # 모든 카탈로그 버프에 설정 보장
        settings.setdefault(
            ANCHOR_ID,
            config.BuffSettings(
                id=ANCHOR_ID,
                show_duration=False,
                alert=config.AlertConfig(enabled=False),
            ),
        )
        for bid in self._catalog:
            # 새 버프 기본값: 기본 음성알림 있는 버프만 '사라짐 경고' 켜짐, 나머지는 꺼짐.
            settings.setdefault(
                bid,
                config.BuffSettings(
                    id=bid,
                    alert=config.AlertConfig(warn_gone=bid in self._sound_ids),
                ),
            )

        # 목록 순서 = 저장 순서(앵커 제외) + 새 카탈로그 버프. 추적을 끈(hidden) 버프도 넣는다 —
        # 0.32.0: 예전엔 빼서 다시 실행하면 목록에서 사라져 다시 켤 방법이 없었다. 추적 제외는 MainWindow가 hidden으로 따로 판단.
        order: list[str] = []
        for s in saved:
            if s.id in self._catalog and s.id != ANCHOR_ID and s.id not in order:
                order.append(s.id)
        for bid in self._catalog:
            if bid != ANCHOR_ID and bid not in order:
                order.append(bid)
        return settings, order

    def fit_width(self, width):
        self._columns.fit_width(width)

    def _save(self) -> None:
        shown = [self._settings[i] for i in self._order]
        # 숨김(표시 OFF)뿐 아니라, 아이콘이 (일시적으로) 없어 목록에서 빠진 설정도 보존한다.
        # 업데이트 중 카탈로그가 잠깐 비어도 자동저장이 사용자 버프를 영구 삭제하지 않도록
        # (아이콘이 다시 생기면 복원). 삭제(－)는 self._settings에서 직접 빼므로 의도대로 사라진다.
        rest = [
            s
            for i, s in self._settings.items()
            if i != ANCHOR_ID and i not in self._order
        ]
        config.save_buff_settings([self._settings[ANCHOR_ID], *shown, *rest])

    # ---- 목록 ----
    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)

        top = QHBoxLayout()
        top.setSpacing(6)
        region_btn = QPushButton("직접 지정")
        region_btn.clicked.connect(self._pick_region)
        self.region_btn = region_btn  # 온보딩 투어가 강조 대상으로 참조
        # 버프·디버프 잠금 줄은 한 줄 세 칸 '위치 잠금 │ 배율 │ 불투명도'(같은 너비, 안내·도움말 명세 15절 — 13절 9항 5:5 대체)
        self.lock_btn = style_toggle(QPushButton(lock_text(False)))
        self.lock_btn.setToolTip(
            "잠그면 오버레이 위치가 고정되고, 클릭이 통과돼 게임을 가리지 않아요.\n"
            "해제하면 드래그로 위치를 옮길 수 있어요."
        )
        self.lock_btn.toggled.connect(self._on_lock_toggled)
        top.addWidget(self.lock_btn, 1)
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(50, 300)
        self.scale_spin.setSingleStep(10)
        self.scale_spin.setPrefix("배율 ")  # 0.31.1: '표시 배율' → '배율'(세 칸 한 줄 최소 폭 줄이기)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setValue(config.load_overlay_scales()[0])
        self.scale_spin.valueChanged.connect(self._on_scale)
        top.addWidget(self.scale_spin, 1)
        from .settings_layout import opacity_spin
        self.opacity_spin = opacity_spin(config.load_overlay_opacities()[0])
        self.opacity_spin.valueChanged.connect(self._on_opacity)
        top.addWidget(self.opacity_spin, 1)
        from .settings_layout import equal_columns, lock_width
        equal_columns(self.lock_btn, self.scale_spin, self.opacity_spin, at_least=lock_width(self.lock_btn))

        hint_row = QHBoxLayout()
        hint_row.setSpacing(6)
        self.region_hint = hint_label("")
        hint_row.addWidget(self.region_hint, 1)
        self.view_region_btn = QPushButton("지정 영역 보기")
        self.view_region_btn.setToolTip("잡힌 영역을 화면에 점선으로 잠깐 표시")
        self.view_region_btn.clicked.connect(self._flash_region)
        self.auto_find_btn = QPushButton("자동 찾기")
        self.auto_find_btn.setToolTip("상태목록창(버프)을 화면에서 자동으로 찾아 지정")
        self.auto_find_btn.clicked.connect(self._on_auto_find)
        hint_row.addWidget(self.auto_find_btn)
        hint_row.addWidget(region_btn)
        hint_row.addWidget(self.view_region_btn)
        from .region_registration import clear_button
        self.clear_region_btn = clear_button(self, "buff", self._region_cleared)
        hint_row.addWidget(self.clear_region_btn)
        # 영역 묶음(안내·도움말 명세 11절): 지정 전 '영역 지정' 상자, 지정 후 상태 줄 + 접힌 '영역 다시 지정 ▸'
        body = QWidget()
        region = QVBoxLayout(body)
        region.setContentsMargins(0, 0, 0, 0)
        region.addWidget(self.region_hint)
        hint_row.removeWidget(self.region_hint)
        hint_row.addStretch()
        region.addLayout(hint_row)
        self.region_guide = hint_label(REGION_GUIDE)
        region.addWidget(self.region_guide)
        # 즐겨찾기 칸 인식 줄: 칸 줄 수·등록 버프 켜짐/꺼짐. 메인 상태 폴링이 갱신한다.
        self.favorites_info = hint_label("")
        region.addWidget(self.favorites_info)

        self.status_label = hint_label("")  # 진단 상태(추적 중/게임 비활성 등) = 지정 후 요약 줄
        from .status_icon import status_row
        status, self.status_icon = status_row(self.status_label)  # B안: 앞 기호 대신 그린 아이콘
        summary = QWidget()
        summary.setLayout(status)
        from .region_section import RegionSection
        self.region_section = RegionSection(body, unset_text="지정하면 버프 남은 시간을 오버레이로 보여줘요",
                                            summary=summary)
        v.addWidget(section_label("판독 영역 · 버프 목록"))
        v.addWidget(self.region_section)
        self._update_region_hint()
        v.addLayout(top)
        # '오버레이 창 보이기'(0.32.0): 끄면 창만 숨기고 탐지·알림은 계속 — 아이콘 없이 소리 알림만 쓰는 사람용.
        # 잠금 줄과 다른 줄이라 두 칸(목록|상세) 최소 폭에 영향 없음(0.31.1).
        self.window_check = checkbox("오버레이 창 보이기")
        self.window_check.setChecked(config.load_overlay_windows()[0])
        self.window_check.setToolTip("끄면 버프 오버레이 창만 숨겨요. 추적·알림·소리는 그대로예요.\n"
                                     "일시정지와 달리 알림도 계속 울려요.")
        self.window_check.toggled.connect(self._on_window_visible)
        self.window_hint = hint_label("끄면 창 없이 알림만 받아요")
        window_row = QHBoxLayout()
        window_row.setSpacing(8)
        window_row.addWidget(self.window_check)
        window_row.addWidget(self.window_hint, 1)
        v.addLayout(window_row)

        self.buff_list = QListWidget()
        self.buff_list.setIconSize(QSize(32, 32))
        self.buff_list.currentRowChanged.connect(self._on_select)
        v.addWidget(self.buff_list, 1)
        from .settings_layout import enable_drag_reorder
        enable_drag_reorder(self.buff_list, self._on_dropped, pinned=ANCHOR_ID)  # 끌어서 순서 바꾸기(명세 15절 2항), ▲▼도 그대로

        # 추가·삭제는 글자 라벨(짝 맞춤), 순서 이동은 아이콘 — 4등분 균등 너비.
        order_row = QHBoxLayout()
        order_row.setSpacing(4)
        self.add_btn = QPushButton("＋ 추가")
        self.add_btn.setToolTip("새 버프 등록")
        self.add_btn.clicked.connect(self._on_register)
        self.del_btn = QPushButton("－ 삭제")
        self.del_btn.setStyleSheet(danger_style())
        self.del_btn.setToolTip("선택한 버프 삭제")
        self.del_btn.clicked.connect(self._on_delete)
        self.up_btn = QPushButton("▲")
        self.up_btn.setToolTip("위로 (표시 순서)")
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn = QPushButton("▼")
        self.down_btn.setToolTip("아래로 (표시 순서)")
        self.down_btn.clicked.connect(lambda: self._move(1))
        for b in (self.add_btn, self.del_btn, self.up_btn, self.down_btn):
            order_row.addWidget(b, 1)
        v.addLayout(order_row)

        v.addWidget(
            callout(
                "아이콘이 똑같은 버프는 오탐 여지가 있어요\n"
                "예: 급소관통(스킬), 물리공격력증가(물약)"
            )
        )
        return panel

    def set_favorites_info(self, text: str, color: str) -> None:
        self.favorites_info.setText(text)
        self.favorites_info.setStyleSheet(f"color:{color};")

    def _on_scale(self, pct: int) -> None:
        config.set_buff_scale(pct)
        self.scale_changed.emit(pct)

    def _on_window_visible(self, visible: bool) -> None:
        config.set_buff_window_visible(visible)
        self.window_visible_changed.emit(visible)

    def _on_opacity(self, pct: int) -> None:
        config.set_buff_opacity(pct)
        self.opacity_changed.emit(pct)

    def _rows(self) -> list[str]:
        """목록에 표시되는 id 순서: 앵커 먼저, 그다음 표시 순서."""
        return [ANCHOR_ID, *self._order]

    def _on_lock_toggled(self, locked: bool) -> None:
        self.lock_btn.setText(lock_text(locked))
        self.lock_toggled.emit(locked)

    def set_lock_state(self, locked: bool) -> None:
        """저장된 고정 상태 복원(버튼 UI 동기화 + 적용)."""
        self.lock_btn.blockSignals(True)
        self.lock_btn.setChecked(locked)
        self.lock_btn.blockSignals(False)
        self._on_lock_toggled(locked)  # 텍스트 갱신 + lock_toggled 방출(→ 오버레이 적용)

    def set_status(self, text: str, color: str, icon: str | None = None) -> None:
        """진단 상태 한 줄 갱신(메인의 주기 폴링에서 호출). icon: status_icon 종류(B안)."""
        self.status_icon.set_kind(icon, color)
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color:{color};")

    # ---- 영역 지정 ----
    def _update_region_hint(self, *, just_set: bool = False) -> None:
        region = config.load_capture_region("buffTracker")
        self.clear_region_btn.setEnabled(region is not None)
        section = getattr(self, "region_section", None)
        if section is not None:  # 영역 묶음: 미지정이면 '영역 지정' 상자, 지정되면 요약 줄 + 접힘
            newly = bool(region) and not section.registered and getattr(self, "_region_ready", False)
            section.set_registered(bool(region), just_set=just_set or newly)
            self.region_hint.setVisible(bool(region))
            self._region_ready = True
        if region:
            self.region_hint.setText(
                f"등록됨 · {region['x']},{region['y']}  "
                f"{region['w']}×{region['h']}"
            )
            self.region_hint.setStyleSheet(f"color:{color('ok')};")
            self.view_region_btn.setEnabled(True)
        else:
            self.region_hint.setText(f"영역 미지정 — {REGION_CRITERION}")
            self.region_hint.setStyleSheet(f"color:{color('muted')};")
            self.view_region_btn.setEnabled(False)

    def _pick_region(self) -> None:
        from .region_selector import RegionSelector

        self._selector = RegionSelector()  # 참조 유지(GC 방지)
        from .region_registration import connect_selection
        connect_selection(self, self._selector, self._on_region_selected)
        self._selector.start()

    def _on_region_selected(self, x: int, y: int, w: int, h: int) -> None:
        config.save_capture_region(x, y, w, h, "buffTracker")
        self._update_region_hint()
        self._flash_region()  # 잡힌 영역을 화면에 점선으로 바로 확인
        self.catalog_changed.emit()

    def _region_cleared(self):
        self._update_region_hint()
        self.catalog_changed.emit()

    def _on_auto_find(self) -> None:
        from .region_registration import generation, connect_selection
        stamp = generation(self)
        """상태목록창을 앵커로 자동 검출 → 민트 점선 미리보기 + 확인 후에만 저장(모든 사용자, 기능 공개 정책 7절)."""
        from ..autofind_diagnostics import perform_autofind
        frame, ox, oy, box = perform_autofind("buff", capture_for_autofind)
        if frame is None:
            QMessageBox.warning(self, "자동 찾기", "화면 캡처에 실패했어요.")
            return
        if box is None:
            QMessageBox.information(
                self,
                "자동 찾기 — 못 찾음",
                "상태목록창을 찾지 못했어요.\n\n"
                "• 상태목록창에 '프리미엄 배틀 멤버십'이 떠 있나요? (이 아이콘을 기준으로 찾아요)\n"
                "• 상태목록창이 화면에 보이나요?\n\n"
                "다시 시도하거나 버프 판독 영역의 '직접 지정'으로 잡으세요.",
            )
            return
        from ..detect.favorites import widen_to_favorites
        x, y, w, h = widen_to_favorites(frame, box)  # 위쪽을 즐겨찾기 칸 맨 위까지(0.33.0 전체 공개)
        lx, ly, lw, lh = to_logical(x + ox, y + oy, w, h)  # 물리 → 논리
        # 위 경계만 사용자가 맞추는 오버레이. 좌우(너비)·아래(화면 끝)는 자동값으로 고정하고,
        # 상태목록창 맨 위(즐겨찾기 첫 줄 위)를 찍게 한다. 클릭=확정 / Enter=자동값 그대로 / ESC=취소.
        from .top_edge_selector import TopEdgeSelector

        self._top_sel = TopEdgeSelector(lx, lw, ly)
        if generation(self) != stamp:
            return
        connect_selection(self, self._top_sel, self._on_region_selected)
        self._top_sel.start()

    def _flash_region(self) -> None:
        """저장된 버프 영역을 화면에 굵은 점선으로 잠깐 표시(아이콘·시간 확인용)."""
        region = config.load_capture_region("buffTracker")
        if not region:
            return
        from .region_highlight import RegionHighlight

        self._highlight = RegionHighlight()  # 참조 유지(GC 방지)
        self._highlight.flash(
            region["x"], region["y"], region["w"], region["h"],
            HIGHLIGHT_TITLE, HIGHLIGHT_SUB,
        )

    def _display_name(self, bid: str) -> str:
        s = self._settings.get(bid)
        if s is not None and s.name:
            return s.name
        buff = self._catalog.get(bid)
        return buff.name if buff else bid

    def _rebuild_list(self) -> None:
        keep = self._current
        self.buff_list.blockSignals(True)
        self.buff_list.clear()
        for bid in self._rows():
            buff = self._catalog.get(bid)
            name = self._display_name(bid)
            # 설명과 용어 통일: '앵커'(스킬 앵커러시와 혼동)가 아니라 '기준' 버프로 표기.
            label = f"⚓ {name} (기준)" if bid == ANCHOR_ID else name
            item = QListWidgetItem(label)  # 글자·아이콘은 _style_item이 정함
            item.setData(Qt.ItemDataRole.UserRole, bid)
            if bid == ANCHOR_ID:  # 기준 버프는 맨 위 고정 — 끌 수 없음(▲▼에서 빠지는 것과 같은 규칙)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            self.buff_list.addItem(item)
            self._style_item(item, bid)
        self.buff_list.blockSignals(False)

        rows = self._rows()
        row = rows.index(keep) if keep in rows else 0
        self.buff_list.setCurrentRow(row)

    def _style_item(self, item, bid: str) -> None:
        """목록 한 줄의 글자·아이콘. 추적을 끈 버프는 흐리게 + '추적 안 함'(사라진 것처럼 보이지 않게, 0.32.0)."""
        from .settings_layout import style_tracked_item
        buff = self._catalog.get(bid)
        settings = self._settings.get(bid)
        off = bid != ANCHOR_ID and settings is not None and settings.hidden
        name = self._display_name(bid)
        label = f"⚓ {name} (기준)" if bid == ANCHOR_ID else name
        pm = _pixmap(buff.display_image or buff.match_icon, 32) if buff is not None else None
        style_tracked_item(item, label, pm, off, "버프")

    def _current_id(self) -> str | None:
        item = self.buff_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    # ---- 등록/삭제/순서 ----
    def _new_id(self) -> str:
        n = 1
        while f"buff_{n}" in self._catalog:
            n += 1
        return f"buff_{n}"

    def _on_register(self) -> None:
        """새 버프 추가: 빈 아이콘·이름 '-'로 목록 하단에 넣고, 오른쪽에서 설정."""
        new_id = self._new_id()
        catalog_mod.register_buff(
            new_id, catalog_mod.NONE_MATCH_ICON, catalog_mod.NONE_DISPLAY_IMAGE
        )
        self._catalog = {b.id: b for b in available_catalog()}
        self._settings, self._order = self._load_state()
        self._settings[new_id].name = "-"  # 미설정 표시
        self._current = new_id
        self._save()
        self._rebuild_list()
        self.catalog_changed.emit()

    def _on_delete(self) -> None:
        bid = self._current_id()
        if bid is None or bid == ANCHOR_ID:
            return
        box = QMessageBox(self)
        box.setWindowTitle("버프 삭제")
        is_default = bid in catalog_mod.default_buff_ids()
        msg = (
            f"'{bid}' 기본 버프를 목록에서 뺄까요?\n(배포돼도 계속 숨겨져요)"
            if is_default
            else f"'{bid}' 버프를 삭제할까요?\n(매칭 아이콘·표시 이미지 파일이 삭제돼요)"
        )
        box.setText(msg)
        yes = box.addButton("예", QMessageBox.ButtonRole.YesRole)
        box.addButton("아니오", QMessageBox.ButtonRole.NoRole)
        box.exec()
        if box.clickedButton() is not yes:
            return
        if is_default:
            config.add_removed_default(bid, "buffTracker")
        catalog_mod.delete_buff(bid)  # 사용자 커스텀/덮어쓴 파일 정리(기본 파일은 보존)
        self._settings.pop(bid, None)
        if bid in self._order:
            self._order.remove(bid)
        self._current = None
        self._reload_catalog()

    def _reload_catalog(self, select: str | None = None) -> None:
        """파일 변경(등록/삭제) 후 카탈로그·상태 재적재."""
        self._catalog = {b.id: b for b in available_catalog()}
        self._settings, self._order = self._load_state()
        self._current = select
        self._save()
        self._rebuild_list()
        self.catalog_changed.emit()

    def _move(self, delta: int) -> None:
        bid = self._current_id()
        if bid is None or bid == ANCHOR_ID or bid not in self._order:
            return
        i = self._order.index(bid)
        j = i + delta
        if not (0 <= j < len(self._order)):
            return
        self._order[i], self._order[j] = self._order[j], self._order[i]
        self._current = bid
        self._save()
        self._rebuild_list()
        self.tracking_changed.emit()

    def _on_dropped(self, order: list[str], dropped: str | None) -> None:
        """끌어서 놓은 순서를 ▲▼과 같은 경로로 저장. 기준 버프는 맨 위 고정(그 위로 놓인 항목은 바로 아래로)."""
        new = [bid for bid in order if bid != ANCHOR_ID]
        if sorted(new) != sorted(self._order):  # 이동만(삭제·복제 없음) — 어긋나면 목록만 다시 그림
            self._rebuild_list()
            return
        self._order = new
        self._current = dropped if dropped in new else self._current
        self._save()
        self._rebuild_list()
        self.tracking_changed.emit()

    # ---- 폼 ----
    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # --- 그룹 1: 아이콘(이름 + 매칭/표시 아이콘) ---
        icon_box = QGroupBox("아이콘")
        iv = QVBoxLayout(icon_box)
        iv.setSpacing(6)
        iv.addWidget(section_label("이름"))
        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self._save_name)  # 포커스 아웃·엔터 시 저장
        iv.addWidget(self.name_edit)

        iv.addWidget(section_label("찾을 아이콘"))
        match_row = QHBoxLayout()
        self.match_slot = icon_slot()
        match_row.addWidget(self.match_slot)
        self.match_capture_btn = QPushButton("상태창에서 가져오기")
        self.match_capture_btn.setToolTip(
            "화면에서 아이콘을 드래그로 집어 매칭 아이콘으로 저장(돋보기 지원)"
        )
        self.match_capture_btn.clicked.connect(self._capture_match_icon)
        match_row.addWidget(self.match_capture_btn)
        self.match_file_btn = QPushButton("파일 선택")
        self.match_file_btn.clicked.connect(self._pick_match_icon)
        match_row.addWidget(self.match_file_btn)
        match_row.addStretch(1)
        iv.addLayout(match_row)

        iv.addWidget(section_label("오버레이 아이콘"))
        show_row = QHBoxLayout()
        self.display_slot = icon_slot("—")
        show_row.addWidget(self.display_slot)
        self.display_file_btn = QPushButton("파일 선택")
        self.display_file_btn.clicked.connect(self._pick_display_image)
        self.display_clear_btn = QPushButton("초기화")
        self.display_clear_btn.clicked.connect(self._clear_display_image)
        show_row.addWidget(self.display_file_btn)
        show_row.addWidget(self.display_clear_btn)
        show_row.addStretch(1)
        iv.addLayout(show_row)
        iv.addWidget(hint_label("└ 비워 두면 찾을 아이콘을 사용해요."))
        v.addWidget(icon_box)

        # --- 그룹 2: 표시(추적·지속시간·사라짐 경고) ---
        show_box = QGroupBox("표시")
        sv = QVBoxLayout(show_box)
        sv.setSpacing(6)
        # '이 버프 추적'(0.32.0 — 예전 '오버레이에 표시', 자리 그대로·사용자 결정). 끄면 그 아래 설정은 흐리게.
        from .settings_layout import track_check
        self.display_check = track_check("버프")
        self.display_check.toggled.connect(self._form_changed)
        sv.addWidget(self.display_check)
        self.show_duration = checkbox("지속시간 표시")
        self.show_duration.toggled.connect(self._form_changed)
        sv.addWidget(self.show_duration)
        self.warn_gone_check = checkbox("사라짐 경고")
        self.warn_gone_check.setToolTip(
            "추적 중이던 버프가 사라지면 그 자리를 잠깐(3초) 빨간 테두리+X로 "
            "보여주고 소리로 알려요."
        )
        self.warn_gone_check.toggled.connect(self._form_changed)
        sv.addWidget(self.warn_gone_check)
        v.addWidget(show_box)

        # --- 그룹 3: 알림(종료 알림 + 2차) ---
        alert_box = QGroupBox("알림")
        self._alert_box = alert_box
        alv = QVBoxLayout(alert_box)
        alv.setSpacing(6)
        alert_row = QHBoxLayout()
        self.alert_check = checkbox("종료 알림")
        self.before_spin = QSpinBox()
        self.before_spin.setRange(1, 300)
        self.before_spin.setSuffix(" 초 전")
        self.sound_check = checkbox("소리")
        for wdg in (self.alert_check, self.before_spin, self.sound_check):
            alert_row.addWidget(wdg)
        alert_row.addStretch(1)
        alv.addLayout(alert_row)
        self.alert_check.toggled.connect(self._on_alert_toggled)
        for wdg in (self.before_spin, self.sound_check):
            if isinstance(wdg, QCheckBox):
                wdg.toggled.connect(self._form_changed)
            else:
                wdg.valueChanged.connect(self._form_changed)

        # 2차 알림: 놓침·오독 대비 재알림(소리는 1차 설정을 그대로 재사용).
        alert_row2 = QHBoxLayout()
        self.alert2_check = checkbox("2차 알림")
        self.before2_spin = QSpinBox()
        self.before2_spin.setRange(1, 300)
        self.before2_spin.setValue(5)  # 기본 5초 전
        self.before2_spin.setSuffix(" 초 전")
        alert_row2.addWidget(self.alert2_check)
        alert_row2.addWidget(self.before2_spin)
        alert_row2.addStretch(1)
        alv.addLayout(alert_row2)
        self.alert2_check.toggled.connect(self._on_alert2_toggled)
        self.before2_spin.valueChanged.connect(self._form_changed)
        self._alert2_hint = hint_label("└ 1차를 놓치거나 시간을 잘못 읽었을 때 한 번 더 알림")
        alv.addWidget(self._alert2_hint)
        v.addWidget(alert_box)

        v.addStretch(1)
        return panel

    def _on_select(self, _row: int) -> None:
        bid = self._current_id()
        self._current = bid
        if bid is None:
            self._name_id = None
            self._form_stack.setCurrentWidget(self._empty_panel)
            return
        buff = self._catalog.get(bid)
        s = self._settings[bid]
        is_anchor = bid == ANCHOR_ID
        self._form_stack.setCurrentWidget(self.anchor_panel if is_anchor else self._buff_editor)
        if is_anchor:
            self.anchor_name.setText(self._display_name(bid))
            self._set_slot(self.anchor_icon, buff.match_icon if buff else None, "")

        self._loading = True
        self._name_id = bid  # name_edit이 편집 중인 버프(포커스 아웃 저장 기준)
        self.name_edit.setText(self._display_name(bid))
        self._set_slot(self.match_slot, buff.match_icon if buff else None, "▣")
        self._set_slot(
            self.display_slot, buff.display_image if buff else None, "—"
        )
        self.display_check.setChecked(not s.hidden)
        self.show_duration.setChecked(s.show_duration)
        self.warn_gone_check.setChecked(s.alert.warn_gone)
        self.alert_check.setChecked(s.alert.enabled)
        self.before_spin.setValue(s.alert.before_sec)
        # 소리 체크와 2차 알림은 사운드 파일이 등록된 버프에만 노출한다.
        # (소리 없는 버프는 2차 알림이 무의미 — 다시 울릴 소리가 없다)
        has_sound = bid in self._sound_ids
        self.sound_check.setVisible(has_sound)
        self.sound_check.setChecked(s.alert.sound and has_sound)
        self.alert2_check.setVisible(has_sound)
        self.before2_spin.setVisible(has_sound)
        self._alert2_hint.setVisible(has_sound)
        self.alert2_check.setChecked(s.alert.enabled2 and has_sound)
        self.before2_spin.setValue(s.alert.before_sec2)
        # 앵커는 '기준' 버프라 수정·삭제·순서변경 불가 → 관련 위젯을 전부 비활성(회색)해
        # 못 누르는 걸 눈으로 알 수 있게 한다(＋ 새 버프 추가만 항상 가능).
        editable = not is_anchor
        for wdg in (self.display_check, self.show_duration, self.warn_gone_check,
                    self.alert_check,
                    self.name_edit, self.match_capture_btn, self.match_file_btn,
                    self.display_file_btn, self.display_clear_btn,
                    self.del_btn, self.up_btn, self.down_btn):
            wdg.setEnabled(editable)
        # 알림 하위 위젯(초·소리·2차)은 앵커여부 + 알림 켜짐 상태로 최종 결정.
        self._apply_alert_enabled(s.alert.enabled)
        if not is_anchor:  # 기준 버프는 위에서 전부 비활성
            self._apply_tracked(not s.hidden)
        self._loading = False

    def _apply_tracked(self, tracked: bool) -> None:
        """추적을 끈 동안 지속시간·사라짐 경고·알림은 흐리게(값은 그대로 보존 — 다시 켜면 그대로)."""
        for widget in (self.show_duration, self.warn_gone_check, self._alert_box):
            widget.setEnabled(tracked)

    def _on_alert_toggled(self, enabled: bool) -> None:
        self._apply_alert_enabled(enabled)
        if not enabled:
            self.sound_check.setChecked(False)
            self.alert2_check.setChecked(False)  # 1차 끄면 2차도 해제(→ 초기화)
        self._form_changed()

    def _on_alert2_toggled(self, _enabled: bool) -> None:
        # 체크 시 보이는 그대로(기본 5초 전) 등록, 해제 시 기본값 5로 초기화.
        if not self._loading and not self.alert2_check.isChecked():
            self.before2_spin.setValue(5)
        self._apply_alert_enabled(self.alert_check.isChecked())
        self._form_changed()

    def _apply_alert_enabled(self, enabled: bool) -> None:
        on = enabled and self._current != ANCHOR_ID
        for wdg in (self.before_spin, self.sound_check, self.alert2_check):
            wdg.setEnabled(on)
        # 2차 초 입력은 '종료 알림'과 '2차 알림'이 모두 켜졌을 때만
        self.before2_spin.setEnabled(on and self.alert2_check.isChecked())

    def _form_changed(self) -> None:
        if self._loading or self._current is None:
            return
        s = self._settings[self._current]
        s.hidden = not self.display_check.isChecked()  # '이 버프 추적' 끔(config 키는 hidden 그대로)
        self._apply_tracked(not s.hidden)
        item = self.buff_list.currentItem()
        if item is not None and item.data(Qt.ItemDataRole.UserRole) == self._current:
            self._style_item(item, self._current)
        s.show_duration = self.show_duration.isChecked()
        s.alert = config.AlertConfig(
            enabled=self.alert_check.isChecked(),
            before_sec=self.before_spin.value(),
            sound=self.sound_check.isChecked(),
            enabled2=self.alert2_check.isChecked(),
            before_sec2=self.before2_spin.value(),
            warn_gone=self.warn_gone_check.isChecked(),
        )
        self._save()
        self.tracking_changed.emit()

    # ---- 이름·아이콘 편집 ----
    def _save_name(self) -> None:
        if self._loading or self._name_id is None:
            return
        s = self._settings.get(self._name_id)
        if s is None:
            return
        new = self.name_edit.text().strip()
        if s.name == new:
            return
        s.name = new
        self._save()
        self._rebuild_list()
        self.tracking_changed.emit()

    def _pick_match_icon(self) -> None:
        bid = self._current
        if bid is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "매칭 아이콘 선택", "", "이미지 (*.png)"
        )
        if not path:
            return
        catalog_mod.set_match_icon(bid, Path(path))
        self._reload_catalog(select=bid)

    def _capture_match_icon(self) -> None:
        """화면에서 아이콘을 드래그로 집어(돋보기 지원) 매칭 아이콘으로 저장."""
        bid = self._current
        if bid is None or bid == ANCHOR_ID:
            return
        _capture_icon_to(self, bid, self._on_match_captured)

    def _on_match_captured(self, bid: str, tmp: Path, ok: bool) -> None:
        if not ok or not tmp.exists():
            return
        catalog_mod.set_match_icon(bid, tmp)
        self._reload_catalog(select=bid)

    def _pick_display_image(self) -> None:
        bid = self._current
        if bid is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "표시 이미지 선택", "", "이미지 (*.png)"
        )
        if not path:
            return
        catalog_mod.set_display_image(bid, Path(path))
        self._reload_catalog(select=bid)

    def _clear_display_image(self) -> None:
        bid = self._current
        if bid is None:
            return
        catalog_mod.clear_display_image(bid)
        self._reload_catalog(select=bid)

    def _set_slot(self, slot, path: Path | None, placeholder: str) -> None:
        pm = _pixmap(path, 40)
        if pm is not None:
            slot.setPixmap(pm)
        else:
            slot.setText(placeholder)
