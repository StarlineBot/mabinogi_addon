"""전투 보조 › 단축바 아래 구역 — 쿨타임 오버레이(쿨타임 명세 10절, **제작자 테스트**).

제작자(`feature_access.is_creator()`)에게만 보인다. 다른 사용자는 구역·관측·오버레이가 전혀 없다.

흐름(코드 → 동작):
- `스킬 추가` = 클릭 경계 자동 맞춤 선택창(단축바 칸만). 칸을 클릭하면 그 칸 사각형과 **그 줄의 페이지 숫자 모양**을 저장(최대 8칸).
- 관측은 단축바 공유 캡처의 **작업 스레드**에서 4~5회/초(0.22초): 등록 칸·페이지 상자를 덮는 사각형 하나를 찍어 칸마다
  `회색 바탕 + 가운데 숫자` 판정, 페이지 숫자가 다르면 '가려짐'. **바뀐 칸만** 화면 스레드로 넘긴다.
- 화면 스레드는 줄 상태(`tracker.cooldown_row`)를 갱신하고 오버레이에 바뀐 줄만 그린다. 칸 그림은 DWM 썸네일.
"""
from __future__ import annotations

import logging
import time
import uuid

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .. import config
from ..detect import cooldown as cd
from ..tracker.cooldown_row import HIDDEN, CooldownRow
from .widgets import checkbox, hint_label, switch

_log = logging.getLogger(__name__)
OBSERVE_INTERVAL = 0.22   # 관측 4~5회/초(9.1-2)
MAX_SLOTS = 8
SOUND_FILE = "상태지원 알림.mp3"


def observe(frame, origin, slots, last: dict, with_crops: bool):
    """작업 스레드: 공유 캡처 한 장(물리 사각형 origin에서 시작)에서 칸마다 상태. 바뀐 칸만 돌려준다(없으면 None).
    last는 이 함수만 쓰는 이전 상태(작업 스레드 안에서만 바뀐다)."""
    ox, oy = origin
    changes, crops = {}, {}
    for slot in slots:
        x, y, w, h = slot["rect"]
        cx, cy = x - ox, y - oy
        inside = cx >= 0 and cy >= 0  # 음수 인덱스는 numpy가 반대편에서 잘라 오므로 먼저 막는다
        cell = frame[cy:cy + h, cx:cx + w] if inside else frame[:0, :0]
        state = cd.classify(cell) if cell.shape[:2] == (h, w) else cd.UNKNOWN
        page_rect = slot.get("page_rect")
        if state != cd.UNKNOWN and page_rect and slot.get("page"):
            px, py, pw, ph = page_rect
            same = cd.same_page(frame, (px - ox, py - oy, pw, ph), slot["page"])
            if same is not True:  # 페이지가 다르거나 상자를 못 읽음 → 가려짐(알림 없음)
                state = HIDDEN
        if state == cd.UNKNOWN:
            state = HIDDEN
        if last.get(slot["id"]) != state:
            changes[slot["id"]] = state
            last[slot["id"]] = state
        if with_crops and state == cd.COOLING and cell.size:
            crops[slot["id"]] = cell.copy()
    if not changes and not crops:
        return None
    return {"changes": changes, "crops": crops}


class CooldownSection(QGroupBox):
    def __init__(self, watcher, parent=None) -> None:
        super().__init__("쿨타임 오버레이 (제작자 테스트)", parent)
        self._watcher = watcher
        self._cfg = config.load_cooldown()
        self.row = CooldownRow()
        self._paused = False
        self._shutting_down = False
        self._last: dict[str, str] = {}
        self._overlay = None
        self._notifier = None
        self._selector = None
        self._allowed = None

        v = QVBoxLayout(self)
        v.addWidget(hint_label("쓴 스킬이 사용 중인 동안 한 줄로 보여 주고, 다시 쓸 수 있게 되면 민트로 강조한 뒤 빼요."))
        top = QHBoxLayout()
        self.enable = switch("쿨타임 오버레이 사용")
        self.enable.setChecked(self._cfg["enabled"])
        self.enable.toggled.connect(self._on_enable)
        top.addWidget(self.enable)
        top.addStretch(1)
        v.addLayout(top)
        row = QHBoxLayout()
        self.add_btn = QPushButton("스킬 추가")
        self.add_btn.setToolTip("단축바 칸을 클릭해 등록해요(칸 테두리에 자동으로 맞춰요). 최대 8칸")
        self.add_btn.clicked.connect(self._on_add)
        row.addWidget(self.add_btn)
        self.sound_chk = checkbox("사용 가능해지면 알림음")
        self.sound_chk.setChecked(self._cfg["sound"])
        self.sound_chk.toggled.connect(lambda on: self._save(sound=on))
        row.addWidget(self.sound_chk)
        row.addStretch(1)
        v.addLayout(row)
        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(2)
        v.addLayout(self.list_box)
        opts = QHBoxLayout()
        opts.addWidget(QLabel("배율"))
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(50, 300)
        self.scale_spin.setSingleStep(10)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setValue(self._cfg["scale"])
        self.scale_spin.valueChanged.connect(self._on_scale)
        opts.addWidget(self.scale_spin)
        opts.addWidget(QLabel("불투명도"))
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(30, 100)
        self.opacity_spin.setSingleStep(5)
        self.opacity_spin.setSuffix(" %")
        self.opacity_spin.setValue(self._cfg["opacity"])
        self.opacity_spin.valueChanged.connect(self._on_opacity)
        opts.addWidget(self.opacity_spin)
        from .settings_layout import lock_button
        self.lock_btn = lock_button(self._cfg["locked"])
        self.lock_btn.clicked.connect(self._on_lock)
        opts.addWidget(self.lock_btn)
        opts.addStretch(1)
        v.addLayout(opts)
        self.status = hint_label("")
        v.addWidget(self.status)
        self._render_list()
        if not self.allowed():
            self.hide()  # 제작자가 아니면 처음부터 숨김(부모에 붙기 전이라 show는 하지 않는다)

        self._timer = QTimer(self)
        self._timer.setInterval(200)  # 보이기·강조 끝(가벼움) — 캡처·판정은 공유 캡처 작업 스레드
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---- 등록 ----------------------------------------------------------------------------------
    @property
    def slots(self) -> list[dict]:
        return self._cfg["slots"]

    def _save(self, **data) -> None:
        self._cfg.update(data)
        config.save_cooldown(data)

    def _render_list(self) -> None:
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        for slot in self.slots:
            line = QWidget()
            h = QHBoxLayout(line)
            h.setContentsMargins(0, 0, 0, 0)
            x, y, w, hh = slot["rect"]
            h.addWidget(QLabel(f"{slot['label']} · 칸 {w}×{hh} @ ({x},{y})" + ("" if slot.get("page") else " · 페이지 확인 없음")))
            h.addStretch(1)
            remove = QPushButton("－ 삭제")
            from .settings_layout import danger_style
            remove.setStyleSheet(danger_style())
            remove.clicked.connect(lambda _=False, sid=slot["id"]: self._remove(sid))
            h.addWidget(remove)
            self.list_box.addWidget(line)
        if not self.slots:
            self.list_box.addWidget(hint_label("등록한 스킬이 없어요. '스킬 추가'로 단축바 칸을 클릭해 주세요."))
        self.add_btn.setEnabled(len(self.slots) < MAX_SLOTS)

    def _on_add(self) -> None:
        from .region_selector import RegionSelector
        hwnd = None
        try:
            from ..system import dwm_thumbnail
            from ..system.window_watcher import DEFAULT_GAME_TITLES
            hwnd = dwm_thumbnail.find_game_window(config.load_game_exe(), DEFAULT_GAME_TITLES) or None
        except Exception:  # noqa: BLE001
            hwnd = None
        self._selector = RegionSelector(window_hwnd=hwnd, snap_kinds=("skill",))  # 단축바 칸만(click-snap 3절)
        self._snap_hit = False
        self._selector.snapped.connect(self._on_snapped)
        self._selector.selected.connect(self._on_selected)
        self._selector.start()

    def _on_selected(self, *_rect) -> None:
        if not self._snap_hit:  # 직접 드래그한 사각형은 받지 않는다(칸 테두리에 맞춘 것만)
            self.status.setText("단축바 칸 위에서 클릭해 주세요(민트 테두리가 보일 때).")

    def _on_snapped(self, target) -> None:
        self._snap_hit = True
        selector = self._selector
        if target is None or getattr(target, "kind", "") != "skill" or selector is None:
            return
        self.register(target, getattr(selector, "snapshot_bgr", None), selector.physical_origin())

    def register(self, target, frame, origin=(0, 0)) -> dict | None:
        """클릭 맞춤 대상(단축바 칸) → 등록. 그 줄 페이지 숫자 모양도 같은 스냅샷에서 저장(쿨타임 10.4)."""
        ox, oy = origin
        x, y, w, h = target.rect
        rect = [x + ox, y + oy, w, h]
        if any(s["rect"] == rect for s in self.slots):
            self.status.setText("이미 등록한 칸이에요.")
            return None
        if len(self.slots) >= MAX_SLOTS:
            self.status.setText(f"최대 {MAX_SLOTS}칸까지 등록할 수 있어요.")
            return None
        page_rect = page = None
        source, row = target.info.get("source"), target.info.get("row", 0)
        if frame is not None and source is not None:
            pr = cd.page_rect(frame, source, row)
            if pr is not None:
                page = cd.page_signature(frame, pr)
                page_rect = [pr[0] + ox, pr[1] + oy, pr[2], pr[3]]
        used = {s["label"] for s in self.slots}
        label = next(f"스킬 {n}" for n in range(1, MAX_SLOTS + 2) if f"스킬 {n}" not in used)
        slot = {"id": uuid.uuid4().hex[:8], "rect": rect, "page_rect": page_rect, "page": page, "label": label, "row": row}
        self._save(slots=self.slots + [slot])
        self._last.clear()
        self._render_list()
        self.status.setText(f"{label}을(를) 등록했어요." + ("" if page else " (페이지 숫자를 못 읽어 페이지 확인 없이 봐요)"))
        return slot

    def _remove(self, sid: str) -> None:
        self._save(slots=[s for s in self.slots if s["id"] != sid])
        self.row.prune([s["id"] for s in self.slots])
        self._last.clear()
        self._render_list()
        self._show_row()

    # ---- 옵션 ----------------------------------------------------------------------------------
    def _on_enable(self, on: bool) -> None:
        self._save(enabled=bool(on))
        self._tick()

    def _on_scale(self, value: int) -> None:
        self._save(scale=int(value))
        if self._overlay is not None:
            self._overlay.set_scale(value)

    def _on_opacity(self, value: int) -> None:
        self._save(opacity=int(value))
        if self._overlay is not None:
            self._overlay.set_opacity(value)

    def _on_lock(self) -> None:
        locked = not self._cfg["locked"]
        self._save(locked=locked)
        from .settings_layout import set_lock_text
        set_lock_text(self.lock_btn, locked)
        if self._overlay is not None:
            self._overlay.set_locked(locked)
            self._show_row()

    # ---- 관측·표시 ------------------------------------------------------------------------------
    def allowed(self) -> bool:
        """제작자만. 설정 파일 읽기라 1초 재사용(feature_access.Recheck) — 0.2초 타이머마다 읽지 않게."""
        if self._allowed is None:
            from .. import feature_access
            self._allowed = feature_access.Recheck(lambda: feature_access.is_creator())
        return bool(self._allowed())

    def _enabled(self) -> bool:
        return not (self._shutting_down or self._paused or not self._cfg["enabled"] or not self.slots or not self.allowed())

    def _game_active(self) -> bool:
        try:
            return bool(self._watcher.is_game_active())
        except Exception:  # noqa: BLE001
            return False

    def _running(self) -> bool:
        """관측(판정)은 게임이 앞일 때만."""
        return self._enabled() and self._game_active()

    def _dragging(self) -> bool:
        return self._overlay is not None and getattr(self._overlay, "_drag", None) is not None

    def _display_active(self) -> bool:
        """표시는 다른 오버레이 탭과 같은 규칙: 게임이 앞이거나, 우리 앱이 앞이고(구역이 보이거나·고정 해제 중이거나·끄는 중).
        오버레이를 누르면 같은 프로세스인 우리 창이 앞이 된다 — 그때 숨기면 끌기가 끊기고 다음 클릭은 게임으로 통과했다."""
        if self._game_active():
            return True
        try:
            self_active = bool(self._watcher.is_self_active())
        except Exception:  # noqa: BLE001
            self_active = False
        return self_active and (self.isVisible() or not self._cfg["locked"] or self._dragging())

    def _tick(self) -> None:
        from .skillbar_capture import shared
        capture = shared()
        if not getattr(self, "_connected", False):
            capture.delivered.connect(self._on_delivered)
            self._connected = True
        allowed = self.allowed()
        if self.isHidden() == allowed:  # 제작자가 아니면 구역 자체가 안 보인다(로그인이 바뀌면 다음 틱에 반영)
            self.setVisible(allowed)
        if not self._running():
            capture.clear("cooldown")  # 관측은 멈춘다(게임이 앞일 때만)
            if (self.row.row or self._last) and not (self._enabled() and self._display_active()):
                self.row.reset()  # 표시도 끝날 때만 줄을 비운다(우리 창이 잠깐 앞이면 그대로 둠)
                self._last.clear()
            if self._overlay is None or self._overlay.isVisible() != self._should_show():
                self._show_row()
            return
        slots = [dict(s) for s in self.slots]
        rects = [s["rect"] for s in slots] + [s["page_rect"] for s in slots if s.get("page_rect")]
        x0, y0 = min(r[0] for r in rects), min(r[1] for r in rects)
        x1, y1 = max(r[0] + r[2] for r in rects), max(r[1] + r[3] for r in rects)
        last = self._last
        from ..system import dwm_thumbnail
        crops = not dwm_thumbnail.available()  # 썸네일을 못 쓸 때만 그림을 넘긴다
        capture.set_request("cooldown", (x0, y0, x1 - x0, y1 - y0), OBSERVE_INTERVAL,
                            lambda frame: observe(frame, (x0, y0), slots, last, crops))
        if self.row.expire(time.monotonic()):
            self._show_row()
        elif self._overlay is None or self._overlay.isVisible() != self._should_show():
            self._show_row()

    def _on_delivered(self, name, payload) -> None:
        if name != "cooldown" or not self._running():
            return
        sound = self.row.update(payload["changes"], time.monotonic())
        pixmaps = None
        if payload.get("crops"):
            from .skillbar_mirror import _np_to_pixmap
            pixmaps = {sid: _np_to_pixmap(c) for sid, c in payload["crops"].items()}
        self._show_row(pixmaps)
        if sound and self._cfg["sound"]:
            self._play()

    def _should_show(self) -> bool:
        return self._enabled() and self._display_active() and (bool(self.row.row) or not self._cfg["locked"])

    def _ensure_overlay(self):
        if self._overlay is None:
            from .cooldown_overlay import CooldownOverlay
            ov = CooldownOverlay(self._cfg["scale"])
            ov.set_opacity(self._cfg["opacity"])
            ov.set_locked(self._cfg["locked"])
            pos = self._cfg.get("pos")
            if pos:
                ov.move(pos["x"], pos["y"])
            else:
                self._default_position(ov)
            ov.moved.connect(lambda: self._save(pos={"x": ov.x(), "y": ov.y()}))
            self._overlay = ov
        return self._overlay

    @staticmethod
    def _default_position(ov) -> None:
        """처음 위치: 화면 가운데 아래쪽(버프 오버레이 아래 근처) — 화면 좌표로 저장(10.1)."""
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            g = screen.geometry()
            ov.move(g.x() + g.width() // 2 - 60, g.y() + int(g.height() * 0.62))

    def _show_row(self, pixmaps=None) -> None:
        if not self._should_show():
            if self._overlay is not None:
                self._overlay.hide()
            return
        ov = self._ensure_overlay()
        ov.set_sources({s["id"]: s["rect"] for s in self.slots})
        ov.set_items([(sid, sid in self.row.until) for sid in self.row.row], pixmaps)
        if not ov.isVisible():
            ov.show()
            self._attach_game(ov)

    def _attach_game(self, ov) -> None:
        try:
            from ..system import dwm_thumbnail
            from ..system.window_watcher import DEFAULT_GAME_TITLES
            ov.set_game_window(dwm_thumbnail.find_game_window(config.load_game_exe(), DEFAULT_GAME_TITLES) or 0)
        except Exception:  # noqa: BLE001
            pass

    def _play(self) -> None:
        try:
            if self._notifier is None:
                from .notifier import SoundNotifier, sound_path
                self._notifier = SoundNotifier({"ready": sound_path(SOUND_FILE)}, volume=0.8)
            self._notifier.play("ready")
        except Exception:  # noqa: BLE001
            _log.warning("쿨타임 알림음 재생 실패", exc_info=True)

    # ---- 메인 연동 ----------------------------------------------------------------------------
    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        self._tick()

    def shutdown(self) -> None:
        self._shutting_down = True
        self._timer.stop()
        from .skillbar_capture import shared
        shared().clear("cooldown")
        if self._overlay is not None:
            self._overlay.close()
