"""단축바 미러 탭(베타) — 상단 단축바를 그룹(4칸) 12뭉으로 떼어 원하는 곳에 배치.

게임 상단 단축바의 첫 아이콘 좌상단(앵커)만 지정하면, 고정 격자로 12개 그룹을 잘라
각각 독립 오버레이(간격 투명)로 띄운다. 프리셋으로 기본 배치를 제공하고, 각 뭉치는
드래그로 옮기고 고정할 수 있다. 빈 칸은 우클릭으로 숨긴다.

베타 기능이라 디스코드 로그인 사용자에게만 보인다.
"""

from __future__ import annotations

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
    slice_group,
)
from .widgets import checkbox, hint_label

ANCHOR_BOX = (40, 40)  # 첫 아이콘(1칸) 크기 — 이 박스를 첫 아이콘에 맞춰 클릭
# 프리셋 배치 하한: 화면 높이의 이 비율 지점이 '스택 바닥'의 하한(그 아래 보스 체력바·
# 액션바 영역은 비운다). 실측 보스 체력바 top ≈ 0.84 → 그 바로 위까지 타이트하게.
SAFE_BOTTOM_RATIO = 0.84

HELP_TITLE = "단축바 미러 사용법(베타)"
HELP_HTML = """
<h3>단축바 미러란?</h3>
<p>게임 상단 단축바를 <b>그룹(4칸) 단위로 떼어</b> 원하는 위치(캐릭터 근처 등)에
띄웁니다. 아이콘만 복제하고 <b>사이 간격은 투명</b>이라 깔끔합니다. (읽기만 함)</p>
<h3>사용 순서</h3>
<ol>
<li><b>앵커 지정</b> — 단축바 <b>맨 왼쪽 위 첫 아이콘</b>에 박스를 맞춰 클릭하세요.
그 자리를 기준으로 12뭉이 자동으로 잘립니다.</li>
<li><b>프리셋</b>으로 기본 배치를 깔고, 각 뭉치를 드래그로 옮깁니다. 고정하면 잠기고
클릭도 통과합니다. <b>빈 칸은 우클릭으로 숨김</b>.</li>
</ol>
"""


class SkillbarTab(QWidget):
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
        v.addWidget(QLabel("단축바"))
        v.setSpacing(10)
        v.addWidget(tab_header(
            "게임 원본 단축바를 그룹별로 복제해 원하는 위치에 표시합니다.", HELP_TITLE, HELP_HTML, self
        ))
        self._beta_notice = hint_label(
            "🧪 개발 중인 기능 — 설정 탭에서 Discord 로그인 후 가장 먼저 써볼 수 있어요."
        )
        self._beta_notice.setStyleSheet("color:#e67e22; font-weight:600;")
        v.addWidget(self._beta_notice)
        v.addWidget(hint_label(
            "원본 단축바를 보이게 한 뒤 자동 찾기를 실행하세요."
            " 직접 지정할 때는 맨 왼쪽 위 첫 칸에 맞추세요. 빈 칸은 오버레이에서 우클릭해 숨길 수 있습니다."
        ))

        row = QHBoxLayout()
        self.anchor_btn = QPushButton("직접 지정")
        self.anchor_btn.setToolTip("단축바 첫 아이콘에 박스를 맞춰 클릭(돋보기)")
        self.anchor_btn.clicked.connect(self._on_anchor)
        v.addWidget(QLabel("판독 영역 · 원본 첫 칸"))
        self.anchor_label = hint_label("")
        v.addWidget(self.anchor_label)
        self.auto_find_btn = QPushButton("자동 찾기")
        self.auto_find_btn.setToolTip("원본 단축바 전체 격자를 확인해 첫 칸 지정 — Discord 베타")
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
        self.lock_all_btn = QPushButton("전체 잠금")
        self.lock_all_btn.clicked.connect(lambda: self._set_locked_all(True))
        self.unlock_all_btn = QPushButton("전체 잠금 해제")
        self.unlock_all_btn.clicked.connect(lambda: self._set_locked_all(False))
        ctl.addWidget(self.lock_all_btn)
        ctl.addWidget(self.unlock_all_btn)
        display_layout.addLayout(ctl)

        # 프리셋(기본 배치)
        pr = QHBoxLayout()
        display_layout.addWidget(QLabel("기본 배치"))
        for label, fn in (
            ("중앙 하단(기본)", self._preset_default),
            ("중앙 2단", self._preset_two_tier),
            ("블록 분리", self._preset_blocks),
        ):
            b = QPushButton(label)
            b.clicked.connect(fn)
            pr.addWidget(b)
        display_layout.addLayout(pr)
        self._preset_btns = [pr.itemAt(i).widget() for i in range(pr.count())]
        v.addStretch(1)

        self._gated = [
            self.anchor_btn, self.auto_find_btn, self.view_region_btn, self.scale_spin,
            self.lock_all_btn, self.unlock_all_btn, *self._preset_btns,
        ]
        self._update_anchor_label()
        self._apply_login_gate()
        self._timer = QTimer(self)
        self._timer.setInterval(120)  # 쿨타임 숫자가 빨리 반영되게 약간 빠르게
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---- 베타 게이팅 ----
    @staticmethod
    def _logged_in() -> bool:
        return config.load_discord_user() is not None

    def _apply_login_gate(self) -> None:
        ok = self._logged_in()
        self._beta_notice.setVisible(not ok)
        for w in self._gated:
            w.setEnabled(ok)
        self.auto_find_btn.setEnabled(ok and not self._autofind_busy)
        self.view_region_btn.setEnabled(ok and self._anchor is not None and not self._shutting_down)

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
        if self._anchor is None or self._paused or not self._logged_in():
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
    def _tick(self) -> None:
        self._apply_login_gate()
        self._apply_visibility()
        if (
            self._paused or not self._logged_in()
            or self._anchor is None or not self._active()
        ):
            return
        from .dpi import to_physical

        px, py, pw, ph = to_physical(
            {"x": self._anchor["x"], "y": self._anchor["y"], "w": SRC_W, "h": SRC_H}
        )
        frame = self._grab_rect(px, py, pw, ph)
        if frame is None:
            return
        # 물리픽셀 캡처를 논리 기준 격자(SRC_W×SRC_H)로 맞춰 슬라이싱(150% 보정).
        if frame.shape[1] != SRC_W or frame.shape[0] != SRC_H:
            import cv2

            frame = cv2.resize(frame, (SRC_W, SRC_H), interpolation=cv2.INTER_AREA)
        for key, ov in self._overlays.items():
            if not ov.isVisible():
                continue
            ov.set_cells(slice_group(frame, self._defs[key], self._cells_on(key)))

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
        self._anchor = {"x": x, "y": y}
        self._update_anchor_label()

    def _region_cleared(self):
        self._anchor = None
        for mark in getattr(self,"_source_marks",[]):
            mark.close()
        for overlay in self._overlays.values():
            overlay.set_cells([None] * CELLS)
        self._update_anchor_label()
        self._apply_visibility()

    def _flash_source(self):
        if not self._anchor or self._shutting_down or not self._logged_in():
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
        if self._anchor:
            self.anchor_label.setText(
                f"등록됨 · {self._anchor['x']},{self._anchor['y']}"
            )
            self.anchor_label.setStyleSheet("color:#2ecc71;")
        else:
            self.anchor_label.setText("앵커 미지정 — 첫 아이콘에 맞춰 클릭하세요")
            self.anchor_label.setStyleSheet("color:#8a8f98;")

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

    def _toggle_cell(self, key: str, i: int) -> None:
        cells = list(self._cells_on(key))
        cells[i] = not cells[i]
        self._chunks_cfg.setdefault(key, {})["cells"] = cells
        self._save()

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
        config.save_skillbar(
            {
                "scale": self._scale,
                "anchor": self._anchor,
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

    def shutdown(self) -> None:
        self._shutting_down = True
        for mark in getattr(self,"_source_marks",[]):
            mark.close()
            mark.deleteLater()
        if self._autofind_highlight is not None:
            self._autofind_highlight.close()
        self._timer.stop()
        for ov in self._overlays.values():
            ov.close()
