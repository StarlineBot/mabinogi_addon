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
)

from .. import config
from .help_dialog import tab_header
from .skillbar_mirror import (
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
        self._enabled = cfg["enabled"]
        self._scale = cfg["scale"]
        self._anchor = cfg["anchor"]  # {x,y} | None
        self._chunks_cfg = cfg["chunks"]  # key -> {show,locked,pos,cells}
        self._paused = False
        self._sct = None
        self._overlays: dict[str, ChunkOverlay] = {}
        self._defs = {g.key: g for g in group_defs()}

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)
        v.addWidget(tab_header(
            "상단 단축바를 그룹(4칸)별로 떼어 원하는 곳에", HELP_TITLE, HELP_HTML, self
        ))
        self._beta_notice = hint_label(
            "🧪 베타 기능 — 설정 탭에서 Discord 로그인 후 사용할 수 있습니다."
        )
        self._beta_notice.setStyleSheet("color:#e67e22; font-weight:600;")
        v.addWidget(self._beta_notice)
        v.addWidget(hint_label(
            "'앵커 지정'으로 단축바 맨 왼쪽 위 첫 아이콘에 박스를 맞춰 클릭하세요."
            " 그 자리를 기준으로 12뭉(그룹)을 잘라 띄웁니다. 빈 칸은 뭉치에서 우클릭으로 숨김."
        ))

        row = QHBoxLayout()
        self.anchor_btn = QPushButton("앵커 지정")
        self.anchor_btn.setToolTip("단축바 첫 아이콘에 박스를 맞춰 클릭(돋보기)")
        self.anchor_btn.clicked.connect(self._on_anchor)
        row.addWidget(self.anchor_btn)
        self.anchor_label = hint_label("")
        row.addWidget(self.anchor_label, 1)
        v.addLayout(row)

        self.enable = checkbox("단축바 미러 사용")
        self.enable.setChecked(self._enabled)
        self.enable.toggled.connect(self._on_enable)
        v.addWidget(self.enable)

        ctl = QHBoxLayout()
        ctl.addWidget(QLabel("배율"))
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(50, 300)
        self.scale_spin.setSingleStep(10)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setValue(self._scale)
        self.scale_spin.valueChanged.connect(self._on_scale)
        ctl.addWidget(self.scale_spin)
        ctl.addStretch(1)
        self.lock_all_btn = QPushButton("전체 고정")
        self.lock_all_btn.clicked.connect(lambda: self._set_locked_all(True))
        self.unlock_all_btn = QPushButton("전체 해제")
        self.unlock_all_btn.clicked.connect(lambda: self._set_locked_all(False))
        ctl.addWidget(self.lock_all_btn)
        ctl.addWidget(self.unlock_all_btn)
        v.addLayout(ctl)

        # 프리셋(기본 배치)
        pr = QHBoxLayout()
        pr.addWidget(QLabel("프리셋"))
        for label, fn in (
            ("원래 배치(가로)", self._preset_original),
            ("2줄 세로", self._preset_two_rows),
            ("블록 분리", self._preset_blocks),
        ):
            b = QPushButton(label)
            b.clicked.connect(fn)
            pr.addWidget(b)
        v.addLayout(pr)
        self._preset_btns = [pr.itemAt(i).widget() for i in range(1, pr.count())]
        v.addStretch(1)

        self._gated = [
            self.anchor_btn, self.enable, self.scale_spin,
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
            self._preset_original()  # 첫 사용: 기본 배치 한 번 깔기

    def _cells_on(self, key: str) -> list[bool]:
        return self._chunks_cfg.get(key, {}).get("cells", [True] * 4)

    def _active(self) -> bool:
        return self._watcher.is_game_active() or (
            self._watcher.is_self_active() and self.isVisible()
        )

    def _apply_visibility(self) -> None:
        if not self._enabled or self._paused or not self._logged_in():
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
            not self._enabled or self._paused or not self._logged_in()
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
        self._selector.selected.connect(self._on_anchor_selected)
        self._selector.start()

    def _on_anchor_selected(self, x: int, y: int, _w: int, _h: int) -> None:
        self._anchor = {"x": x, "y": y}
        self._update_anchor_label()
        self._save()

    def _update_anchor_label(self) -> None:
        if self._anchor:
            self.anchor_label.setText(
                f"앵커: {self._anchor['x']},{self._anchor['y']}  ✔"
            )
            self.anchor_label.setStyleSheet("color:#2ecc71;")
        else:
            self.anchor_label.setText("앵커 미지정 — 첫 아이콘에 맞춰 클릭하세요")
            self.anchor_label.setStyleSheet("color:#8a8f98;")

    # ---- 설정 변경 ----
    def _on_enable(self, checked: bool) -> None:
        self._enabled = checked
        self._apply_visibility()
        self._save()

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

    def _preset_original(self) -> None:
        # 원본 배치(가로) 그대로, 큰 간격만 줄여 화면 하단 중앙 근처에.
        ox, oy, ow, oh = self._screen_origin()
        s = self._scale / 100.0
        gw = round(GROUP_W * s)
        gap = round(14 * s)
        row_gap = round((ICON + 10) * s)
        base_x = ox + ow // 2 - (3 * gw + 2 * gap) - gap  # 두 블록 가로로
        base_y = oy + oh - round((ICON * 2 + 14) * s) - 60
        pos = {}
        col_x = 0
        for bi in range(2):
            for ci in range(3):
                for ri in range(2):
                    key = f"b{bi}r{ri}c{ci}"
                    x = base_x + col_x * (gw + gap) + bi * gap * 2
                    y = base_y + ri * row_gap
                    pos[key] = (x, y)
                col_x += 1
        self._place(pos)

    def _preset_two_rows(self) -> None:
        # 12뭉을 6×2(윗줄 블록1, 아랫줄 블록2)로 세로 두 줄.
        ox, oy, _ow, oh = self._screen_origin()
        s = self._scale / 100.0
        gw = round(GROUP_W * s)
        gap = round(10 * s)
        base_x = ox + 40
        base_y = oy + oh - round((ICON * 2 + 20) * s) - 60
        pos = {}
        for bi in range(2):
            n = 0
            for ri in range(2):
                for ci in range(3):
                    key = f"b{bi}r{ri}c{ci}"
                    pos[key] = (base_x + n * (gw + gap), base_y + bi * round((ICON + 12) * s))
                    n += 1
        self._place(pos)

    def _preset_blocks(self) -> None:
        # 블록별로 두 덩이(각 블록 = 3그룹×2줄을 모아 한 구역).
        ox, oy, _ow, oh = self._screen_origin()
        s = self._scale / 100.0
        gw = round(GROUP_W * s)
        gap = round(8 * s)
        rg = round((ICON + 8) * s)
        base_y = oy + oh - rg * 2 - 60
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
        for key, ov in self._overlays.items():
            c = self._chunks_cfg.setdefault(key, {})
            c["locked"] = ov.locked
            c["pos"] = {"x": ov.x(), "y": ov.y()}
        config.save_skillbar(
            {
                "enabled": self._enabled,
                "scale": self._scale,
                "anchor": self._anchor,
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
        self._timer.stop()
        for ov in self._overlays.values():
            ov.close()
