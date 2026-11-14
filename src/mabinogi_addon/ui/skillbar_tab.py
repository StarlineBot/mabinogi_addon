"""단축바 미러 탭(베타) — 상단 단축바를 그룹(4칸) 12뭉으로 떼어 원하는 곳에 배치.

게임 상단 단축바의 첫 아이콘 좌상단(앵커)만 지정하면, 고정 격자로 12개 그룹을 잘라
각각 독립 오버레이(간격 투명)로 띄운다. 프리셋으로 기본 배치를 제공하고, 각 뭉치는
드래그로 옮기고 고정할 수 있다. 빈 칸은 우클릭으로 숨긴다.

기본 복제와 자동 찾기는 로그인 없이 사용할 수 있다.
"""

from __future__ import annotations

from .. import perf_meter
import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QGroupBox,
)

from .palette import color
from .settings_layout import set_lock_text
from .. import config
from .help_dialog import tab_header
from .skillbar_mirror import (
    CELLS,
    GROUP_W,
    ICON,
    SRC_H,
    SRC_W,
    ChunkOverlay,
    group_defs,
    slice_group_np,
)
MIRROR_INTERVAL = 0.12  # 기존 120ms 그대로(표시용) — 캡처는 공유 작업 스레드
from .widgets import checkbox, hint_label

ANCHOR_BOX = (40, 40)  # 첫 아이콘(1칸) 크기 — 이 박스를 첫 아이콘에 맞춰 클릭
# 프리셋 배치 하한: 화면 높이의 이 비율 지점이 '스택 바닥'의 하한(그 아래 보스 체력바·
# 액션바 영역은 비운다). 실측 보스 체력바 top ≈ 0.84 → 그 바로 위까지 타이트하게.
SAFE_BOTTOM_RATIO = 0.84

from .feature_copy import HELP

HELP_TITLE = '단축바 사용법'
HELP_HTML = HELP['단축바']


class SkillbarTab(QWidget):
    from .. import autofind_regions as _afr
    _anchor = _afr.region_property("skillbar", "_anchor")  # 자동 찾기 v2: 읽기 = 쓸 자리, 쓰기 = 저장 자리
    def __init__(self, watcher) -> None:
        super().__init__()
        self._watcher = watcher
        cfg = config.load_skillbar()
        self._scale = cfg["scale"]
        self._anchor = cfg["anchor"]  # {x,y} | None
        self._center_top_y = cfg["center_top"]  # 중앙 2단 윗단 top y(사용자 하한)
        self._chunks_cfg = cfg["chunks"]  # key -> {show,locked,pos,cells}
        self._paused = False
        self._sct = None
        self._autofind_busy = False
        self._shutting_down = False
        self._autofind_highlight = None
        self._overlays: dict[str, ChunkOverlay] = {}
        self._defs = {g.key: g for g in group_defs()}

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)
        v.addWidget(tab_header(
            "게임 원본 단축바를 그룹별로 복제해 원하는 위치에 표시해요.", HELP_TITLE, HELP_HTML, self
        ))
        self._beta_notice = hint_label("")
        self._beta_notice.hide()
        # 영역 묶음(명세 13.5 — 11절 접기를 단축바에도): 지정 전 '영역 지정' 상자 / 지정 후 '✓ 영역 지정됨' + '영역 다시 지정 ▸'
        outer = v
        v.addWidget(QLabel("판독 영역 · 원본 첫 칸"))
        region_body = QWidget()
        v = QVBoxLayout(region_body)
        v.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.anchor_btn = QPushButton("직접 지정")
        self.anchor_btn.setToolTip("단축바 첫 아이콘에 박스를 맞춰 클릭(돋보기)")
        self.anchor_btn.clicked.connect(self._on_anchor)
        self.anchor_label = hint_label("")
        v.addWidget(self.anchor_label)
        self.auto_find_btn = QPushButton("자동 찾기")
        self.auto_find_btn.setToolTip("원본 단축바 전체 격자를 확인해 첫 칸 지정")
        self.auto_find_btn.clicked.connect(self._on_auto_find)
        row.addWidget(self.auto_find_btn)
        row.addWidget(self.anchor_btn)
        self.view_region_btn = QPushButton("지정 영역 보기")
        self.view_region_btn.clicked.connect(self._flash_source)
        row.addWidget(self.view_region_btn)
        from .region_registration import clear_button
        self.clear_region_btn = clear_button(self, "skillbar", self._region_cleared)
        row.addStretch()
        row.addWidget(self.clear_region_btn)
        v.addLayout(row)
        self.region_guide = hint_label("원본 단축바를 보이게 한 뒤 자동 찾기 · 직접 지정은 맨 왼쪽 위 첫 칸에 맞추세요.")
        v.addWidget(self.region_guide)
        from .region_section import RegionSection
        self.region_section = RegionSection(region_body, unset_text="지정하면 단축바를 그룹별로 원하는 위치에 보여줘요")
        self.region_section.set_guide(self.region_guide, "단축바 위치는 앱이 알아서 찾아요. 틀리면 원본 단축바를 보이게 한 뒤 '직접 지정'으로 맨 왼쪽 위 첫 칸에 맞추면 고정돼요.")  # 자동 찾기 켜짐: v3 안내(QA 0429c66 4)
        v = outer
        v.addWidget(self.region_section)

        # 표시(명세 13.5): 표시 배율 … [전체 위치 잠금됨] / 기본 배치 [중앙 하단(기본)] [중앙 2단] [블록 분리] / 안내 한 줄
        display_group = QGroupBox("표시")
        display_layout = QVBoxLayout(display_group)
        v.addWidget(display_group)
        ctl = QHBoxLayout()
        ctl.addWidget(QLabel("표시 배율"))
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(50, 300)
        self.scale_spin.setSingleStep(10)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setValue(self._scale)
        self.scale_spin.valueChanged.connect(self._on_scale)
        ctl.addWidget(self.scale_spin)
        ctl.addStretch(1)
        from .settings_layout import lock_button
        self.lock_all_btn = lock_button(every=True)  # 전체 잠금·전체 잠금 해제 두 버튼 → 상태형 하나
        self.lock_all_btn.clicked.connect(self._set_locked_all)
        ctl.addWidget(self.lock_all_btn)
        display_layout.addLayout(ctl)

        pr = QHBoxLayout()
        pr.addWidget(QLabel("기본 배치"))
        for label, fn in (
            ("중앙 하단(기본)", self._preset_default),
            ("중앙 2단", self._preset_two_tier),
            ("블록 분리", self._preset_blocks),
        ):
            b = QPushButton(label)
            b.clicked.connect(fn)
            pr.addWidget(b)
        pr.addStretch(1)
        display_layout.addLayout(pr)
        display_layout.addWidget(hint_label("빈칸은 오버레이에서 우클릭하거나 아래 묶음 목록에서 숨길 수 있어요."))
        self._preset_btns = [pr.itemAt(i).widget() for i in range(1, pr.count()) if pr.itemAt(i).widget() is not None]
        # 묶음 목록(0.49.0, 사용자 결정 11-14): 커스텀 오버레이처럼 탭에서 12묶음·칸 숨기기/되살리기
        from .skillbar_groups import SkillbarGroupsSection
        self._thumbs: dict = {}  # key -> 지금 단축바 아이콘 4칸(QPixmap|None)
        self._thumbs_at = 0.0
        self.groups = SkillbarGroupsSection(self._defs)
        self.groups.toggle_cell.connect(self._toggle_cell)
        self.groups.toggle_show.connect(self._set_show)
        self.groups.toggle_lock.connect(self._set_lock)
        v.addWidget(self.groups)
        self.groups.refresh(self._chunks_cfg, self._thumbs)
        from .cooldown_section import CooldownSection
        self.cooldown = CooldownSection(watcher)  # 쿨타임 오버레이(베타, 쿨타임 명세 10절) — 0.44.0부터 모든 사용자
        v.addWidget(self.cooldown)
        v.addStretch(1)

        self._gated = [
            self.anchor_btn, self.auto_find_btn, self.view_region_btn, self.scale_spin,
            self.lock_all_btn, *self._preset_btns,
        ]
        self._update_anchor_label()
        self._sync_lock_all()
        self._apply_login_gate()
        self._timer = QTimer(self)
        self._timer.setInterval(120)  # 쿨타임 숫자가 빨리 반영되게 약간 빠르게
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---- 베타 게이팅 ----
    @staticmethod
    def _logged_in() -> bool:
        from .. import feature_access
        return feature_access.is_logged_in()

    def _apply_login_gate(self) -> None:
        ok = self._logged_in()
        self._beta_notice.hide()
        for w in self._gated:
            w.setEnabled(not self._shutting_down)
        self.auto_find_btn.setEnabled(not self._autofind_busy)
        self.view_region_btn.setEnabled(self._anchor is not None and not self._shutting_down)

    # ---- 오버레이 ----
    def _ensure_overlays(self) -> None:
        if self._overlays:
            return
        for key, gd in self._defs.items():
            ov = ChunkOverlay(gd, scale=self._scale / 100.0)
            ov.moved.connect(self._save)
            ov.cell_toggled.connect(lambda i, k=key: self._toggle_cell(k, i))
            c = self._chunks_cfg.get(key, {})
            pos = c.get("pos")
            if pos:
                ov.move(int(pos["x"]), int(pos["y"]))
            ov.set_locked(bool(c.get("locked", False)))
            ov.set_hidden(self._cells_on(key))
            self._overlays[key] = ov
        if not any(self._chunks_cfg.get(k, {}).get("pos") for k in self._defs):
            self._initializing_layout = True
            try:
                self._preset_default()
            finally:
                self._initializing_layout = False

    def _cells_on(self, key: str) -> list[bool]:
        return self._chunks_cfg.get(key, {}).get("cells", [True] * 4)

    def _active(self) -> bool:
        return self._watcher.is_game_active() or (
            self._watcher.is_self_active() and self.isVisible()
        )

    def _apply_visibility(self) -> None:
        if self._anchor is None or self._paused or self._shutting_down:
            for ov in self._overlays.values():
                ov.hide()
            return
        self._ensure_overlays()
        show = self._active() and self._anchor is not None
        for key, ov in self._overlays.items():
            if show and self._chunks_cfg.get(key, {}).get("show", True):
                if not ov.isVisible():
                    ov.show()
            else:
                ov.hide()

    # ---- 읽기 루프 ----
    @perf_meter.timed("단축바 미러")  # 앱 CPU 절감 1단계: 기능별 처리 시간(측정만)
    def _tick(self) -> None:
        self._apply_login_gate()
        self._apply_visibility()
        if (
            self._paused or self._shutting_down
            or self._anchor is None or not self._active()
        ):
            if getattr(self, "_capture_connected", False):
                self._capture().clear("mirror")  # 안 보일 땐 찍지 않는다
            return
        from .dpi import to_physical

        rect = to_physical(
            {"x": self._anchor["x"], "y": self._anchor["y"], "w": SRC_W, "h": SRC_H}
        )
        # 쿨타임 명세 9.1: 캡처·크기 조정·자르기는 공유 캡처의 작업 스레드에서(화면 스레드는 칸 그림만 바꾼다).
        keys = [key for key, ov in self._overlays.items() if ov.isVisible()]
        if self.groups.isVisible():  # 묶음 목록이 보이면 꺼 둔 묶음의 아이콘도(목록 칸 그림)
            keys = list(self._defs)
        if not keys:
            self._capture().clear("mirror")
            return
        defs = self._defs
        every = [True] * CELLS  # 4칸 모두 자른다 — 숨긴 칸은 오버레이가 안 그림(잠금 해제면 흐린 자리), 목록은 흐리게

        def crop(frame):  # 작업 스레드
            if frame.shape[1] != SRC_W or frame.shape[0] != SRC_H:  # 물리픽셀 → 논리 격자(150% 보정)
                import cv2
                frame = cv2.resize(frame, (SRC_W, SRC_H), interpolation=cv2.INTER_AREA)
            return {key: slice_group_np(frame, defs[key], every) for key in keys}
        self._capture().set_request("mirror", rect, MIRROR_INTERVAL, crop, grab=self._grab_rect)

    def _capture(self):
        from .skillbar_capture import shared
        capture = shared()
        if not getattr(self, "_capture_connected", False):
            capture.delivered.connect(self._on_captured)
            self._capture_connected = True
        return capture

    def _on_captured(self, name, data) -> None:
        if name != "mirror" or self._shutting_down or self._paused:
            return
        import time

        from .skillbar_mirror import _np_to_pixmap
        thumbs_due = self.groups.isVisible() and time.monotonic() - self._thumbs_at >= 1.0  # 목록 칸 그림은 1초에 한 번
        for key, crops in data.items():
            ov = self._overlays.get(key)
            pms = None
            if ov is not None and ov.isVisible():
                pms = [None if c is None else _np_to_pixmap(c) for c in crops]
                ov.set_cells(pms)
            if thumbs_due:
                self._thumbs[key] = pms or [None if c is None else _np_to_pixmap(c) for c in crops]
        if thumbs_due:
            self._thumbs_at = time.monotonic()
            self.groups.refresh(self._chunks_cfg, self._thumbs)

    # ---- 앵커 지정 ----
    def _on_anchor(self) -> None:
        from .region_selector import RegionSelector

        hwnd = None
        try:
            from ..system import dwm_thumbnail
            from ..system.window_watcher import DEFAULT_GAME_TITLES

            hwnd = dwm_thumbnail.find_game_window(
                config.load_game_exe(), DEFAULT_GAME_TITLES
            ) or None
        except Exception:  # noqa: BLE001
            hwnd = None
        self._selector = RegionSelector(fixed_size=ANCHOR_BOX, window_hwnd=hwnd)
        from .region_registration import connect_selection
        connect_selection(self, self._selector, self._on_anchor_selected)
        self._selector.start()

    def _on_anchor_selected(self, x: int, y: int, _w: int, _h: int) -> None:
        config.save_skillbar({"anchor": {"x": x, "y": y}})
        self._afr.user_set("skillbar")  # 직접 지정 고정(다음 실행에도) + 그 기능 사용 켬
        self._anchor = {"x": x, "y": y}
        self._update_anchor_label()

    def _region_cleared(self):
        self._afr.auto_return("skillbar")  # 지정 해제 = 직접 지정 고정 풀기
        self._anchor = None
        for mark in getattr(self,"_source_marks",[]):
            mark.close()
        for overlay in self._overlays.values():
            overlay.set_cells([None] * CELLS)
        self._thumbs.clear()
        self.groups.refresh(self._chunks_cfg, self._thumbs)
        self._update_anchor_label()
        self._apply_visibility()

    def _flash_source(self):
        if not self._anchor or self._shutting_down:
            return
        from .region_highlight import RegionHighlight
        for mark in getattr(self,"_source_marks",[]):
            mark.close()
            mark.deleteLater()
        x,y = self._anchor["x"],self._anchor["y"]
        self._source_marks = []
        for w,h,title in ((SRC_W,SRC_H,"복제 원본 전체 · 12개 그룹"),(ICON,ICON,"기준 첫 칸")):
            mark = RegionHighlight()
            mark.flash(x,y,w,h,"단축바 원본",title)
            self._source_marks.append(mark)

    def _on_auto_find(self) -> None:
        from .autofind_confirm import confirm_autofind
        confirm_autofind(self, "skillbar", "원본 단축바 12개 그룹",
                         self._on_anchor_selected,
                         compatible=lambda box: abs(box[2] - SRC_W) <= 1 and abs(box[3] - SRC_H) <= 1)

    def _update_anchor_label(self) -> None:
        self.clear_region_btn.setEnabled(self._anchor is not None)
        if self._anchor:
            self.anchor_label.setText(
                f"등록됨 · {self._anchor['x']},{self._anchor['y']}"
            )
            self.anchor_label.setStyleSheet(f"color:{color('ok')};")
        else:
            self.anchor_label.setText("원본 첫 칸 미지정 — 맨 왼쪽 위 첫 칸에 맞춰 클릭해 주세요.")
            self.anchor_label.setStyleSheet(f"color:{color('muted')};")
        section = self.region_section  # 영역 묶음(명세 13.5): 지정 후 한 줄 요약 + 접힘, 막 지정했으면 펼침
        registered = self._anchor is not None
        section.set_registered(registered, just_set=registered and not section.registered
                               and getattr(self, "_region_ready", False))
        self.anchor_label.setVisible(registered)
        section.set_summary("✓ 영역 지정됨")
        self._region_ready = True

    # ---- 설정 변경 ----
    def _on_scale(self, value: int) -> None:
        self._scale = value
        for ov in self._overlays.values():
            ov.set_scale(value / 100.0)
        self._save()

    def _set_locked_all(self, locked: bool) -> None:
        self._ensure_overlays()
        for key, ov in self._overlays.items():
            ov.set_locked(locked)
            self._chunks_cfg.setdefault(key, {})["locked"] = locked
        self._save()
        self.groups.refresh(self._chunks_cfg, self._thumbs)

    def _sync_lock_all(self) -> None:
        """모든 묶음이 잠겼으면 '전체 위치 잠금됨', 하나라도 풀리면 '전체 위치 잠금'."""
        locked = all(self._chunks_cfg.get(key, {}).get("locked", False) for key in self._defs)
        self.lock_all_btn.setChecked(locked)
        set_lock_text(self.lock_all_btn, locked)

    def _toggle_cell(self, key: str, i: int) -> None:
        """칸 숨김 ↔ 보임 — 오버레이 우클릭·묶음 목록 둘 다 여기(같은 chunks.<key>.cells, 바로 서로 맞춤)."""
        cells = list(self._cells_on(key))
        cells[i] = not cells[i]
        self._chunks_cfg.setdefault(key, {})["cells"] = cells
        ov = self._overlays.get(key)
        if ov is not None:
            ov.set_hidden(cells)
        self._save()
        self.groups.refresh(self._chunks_cfg, self._thumbs)

    def _set_show(self, key: str, on: bool) -> None:
        """묶음 표시 끔/켬(chunks.<key>.show) — 끄면 그 오버레이를 숨긴다."""
        self._chunks_cfg.setdefault(key, {})["show"] = bool(on)
        self._save()
        self._apply_visibility()
        self.groups.refresh(self._chunks_cfg, self._thumbs)

    def _set_lock(self, key: str, locked: bool) -> None:
        self._ensure_overlays()
        ov = self._overlays.get(key)
        if ov is not None:
            ov.set_locked(bool(locked))
        self._chunks_cfg.setdefault(key, {})["locked"] = bool(locked)
        self._save()
        self.groups.refresh(self._chunks_cfg, self._thumbs)

    # ---- 프리셋(기본 배치) ----
    def _screen_origin(self) -> tuple[int, int, int, int]:
        s = QGuiApplication.primaryScreen()
        g = s.geometry() if s else None
        return (g.x(), g.y(), g.width(), g.height()) if g else (0, 0, 1920, 1080)

    def _place(self, positions: dict[str, tuple[int, int]]) -> None:
        self._ensure_overlays()
        for key, (x, y) in positions.items():
            ov = self._overlays.get(key)
            if ov is not None:
                ov.move(x, y)
                self._chunks_cfg.setdefault(key, {})["pos"] = {"x": x, "y": y}
        self._save()

    def _center_base_y(self, total_h: int) -> int:
        """중앙 계열 프리셋의 윗줄 top y — 보스 체력바 영역(하단) 위로 clamp.

        하한(최소 높이): 화면 하단 ~16%는 보스 체력바·액션바 영역 → 스택 바닥이 그 위로.
        사용자가 더 위로 맞춰 둔 값(_center_top_y)이 있으면 그걸 쓰되, 하한보다 아래로는
        절대 안 내려가게 clamp(보스 체력바 가림 방지).
        """
        _ox, oy, _ow, oh = self._screen_origin()
        default_top = oy + round(oh * SAFE_BOTTOM_RATIO) - total_h
        top = default_top if self._center_top_y is None else min(
            self._center_top_y, default_top
        )
        return max(oy + 40, top)

    def _preset_default(self) -> None:
        """기본 — 상단 단축바 '그대로'(가로 2줄)를 화면 중앙 하단에.

        두 블록을 가로로 나란히(블록1 3그룹 + 블록 간격 + 블록2 3그룹 = 6그룹) 2줄로.
        """
        ox, _oy, ow, _oh = self._screen_origin()
        s = self._scale / 100.0
        gw = round(GROUP_W * s)
        gcol = round(10 * s)  # 그룹 사이 가로 간격
        bcol = round(40 * s)  # 블록 사이 가로 간격(원본처럼 넓게)
        rgap = round((ICON + 8) * s)  # 줄 간격
        total_h = rgap + round(ICON * s)  # 2줄 높이
        row_w = 6 * gw + 4 * gcol + bcol
        x0 = ox + ow // 2 - row_w // 2
        base_y = self._center_base_y(total_h)
        pos = {}
        for bi in range(2):
            for ci in range(3):
                col = bi * 3 + ci
                x = x0 + col * (gw + gcol) + bi * bcol
                for ri in range(2):
                    pos[f"b{bi}r{ri}c{ci}"] = (x, base_y + ri * rgap)
        self._center_top_y = base_y
        self._place(pos)

    def _preset_two_tier(self) -> None:
        """중앙 2단 — 두 블록을 위아래로 쌓아(각 블록 3그룹×2줄 → 총 4줄) 중앙 하단에."""
        ox, _oy, ow, _oh = self._screen_origin()
        s = self._scale / 100.0
        gw = round(GROUP_W * s)
        gcol = round(10 * s)
        rgap = round((ICON + 8) * s)
        bgap = round(6 * s)  # 블록(단) 사이 세로 간격(두 덩이 사이 — 좁게)
        total_h = 4 * rgap + bgap
        row_w = 3 * gw + 2 * gcol
        x0 = ox + ow // 2 - row_w // 2
        base_y = self._center_base_y(total_h)
        pos = {}
        for bi in range(2):
            for ri in range(2):
                tier = bi * 2 + ri
                y = base_y + tier * rgap + (bgap if bi == 1 else 0)
                for ci in range(3):
                    pos[f"b{bi}r{ri}c{ci}"] = (x0 + ci * (gw + gcol), y)
        self._center_top_y = base_y
        self._place(pos)

    def _preset_blocks(self) -> None:
        # 블록별로 두 덩이(각 블록 = 3그룹×2줄을 모아 한 구역).
        ox, oy, _ow, oh = self._screen_origin()
        s = self._scale / 100.0
        gw = round(GROUP_W * s)
        gap = round(8 * s)
        rg = round((ICON + 8) * s)
        base_y = oy + round(oh * SAFE_BOTTOM_RATIO) - rg * 2  # 하단 보스바 영역 비우기
        pos = {}
        for bi in range(2):
            bx = ox + 40 + bi * (3 * (gw + gap) + 60)
            for ri in range(2):
                for ci in range(3):
                    key = f"b{bi}r{ri}c{ci}"
                    pos[key] = (bx + ci * (gw + gap), base_y + ri * rg)
        self._place(pos)

    # ---- 저장/캡처 ----
    def _save(self) -> None:
        if getattr(self, "_initializing_layout", False):
            return
        tops = []
        for key, ov in self._overlays.items():
            c = self._chunks_cfg.setdefault(key, {})
            c["locked"] = ov.locked
            c["pos"] = {"x": ov.x(), "y": ov.y()}
            tops.append(ov.y())
        # 사용자가 드래그로 맞춘 '가장 위 뭉치'의 top을 중앙 2단 하한으로 기억한다
        # (다음에 '중앙 하단' 눌러도 그 높이보다 아래로 안 내려가게).
        if tops:
            self._center_top_y = min(tops)
        self._sync_lock_all()
        config.save_skillbar(
            {
                "scale": self._scale,
                "anchor": self._afr.saved_of(self, "_anchor"),  # 찾은 자리가 아니라 저장 자리
                "centerTopY": self._center_top_y,
                "chunks": self._chunks_cfg,
            }
        )

    def _grab_rect(self, x: int, y: int, w: int, h: int):
        try:
            if self._sct is None:
                import mss

                self._sct = mss.mss()
            shot = self._sct.grab({"left": x, "top": y, "width": w, "height": h})
            return np.frombuffer(shot.bgra, dtype=np.uint8).reshape(
                shot.height, shot.width, 4
            )[:, :, :3]
        except Exception:  # noqa: BLE001
            return None

    # ---- 메인 연동 ----
    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self._apply_visibility()
        self.cooldown.set_paused(paused)

    def shutdown(self) -> None:
        self._shutting_down = True
        if getattr(self, "_capture_connected", False):
            self._capture().clear("mirror")
        cooldown = getattr(self, "cooldown", None)
        if cooldown is not None:
            cooldown.shutdown()
        for mark in getattr(self,"_source_marks",[]):
            mark.close()
            mark.deleteLater()
        if self._autofind_highlight is not None:
            self._autofind_highlight.close()
        self._timer.stop()
        for ov in self._overlays.values():
            ov.close()
