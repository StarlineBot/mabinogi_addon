"""전투 보조 › 단축바 아래 구역 — 쿨타임 오버레이(쿨타임 명세 10절, **베타** — 0.44.0부터 모든 사용자, 기본 꺼짐).

흐름(코드 → 동작):
- `스킬 추가` = 클릭 경계 자동 맞춤 선택창(단축바 칸만). 칸을 클릭하면 그 칸 사각형과 **그 줄의 페이지 숫자 모양**을 저장(세트당 최대 8칸).
- 관측은 단축바 공유 캡처의 **작업 스레드**에서 4~5회/초(0.22초): 등록 칸·페이지 상자를 덮는 사각형 하나를 찍어 칸마다
  `회색 바탕 + 가운데 숫자` 판정, 페이지 숫자가 다르면 '가려짐'. **바뀐 칸만** 화면 스레드로 넘긴다.
- 화면 스레드는 줄 상태(`tracker.cooldown_row`)를 갱신하고 오버레이에 바뀐 줄만 그린다. 칸 그림은 DWM 썸네일.
"""
from __future__ import annotations

import logging
import time
import uuid

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .. import config
from ..detect import cooldown as cd
from ..tracker.cooldown_row import HIDDEN, CooldownRow

PAGE_DIFF = "page"  # 페이지 숫자 모양이 저장한 것과 다름(가려짐과 같이 줄에서 빼되, 목록엔 따로 알림)
PAGE_GUIDE = ("등록한 단축바 페이지에서만 보여요. Shift·변신 등으로 페이지가 바뀌면 숨겨요. "
              "다른 페이지에서도 보려면 그 페이지에서 한 번 더 등록하세요.")
PAGE_HIDDEN_TEXT = "다른 페이지라 숨김(Shift·변신 등)"
PAGE_HIDDEN_TIP = "이 페이지에서도 보려면 지금 한 번 더 등록하세요"
PAGE_WARN_SECONDS = 3.0  # 이만큼 계속 다르면 목록에 '다른 페이지라 숨김'(실제로 페이지를 넘긴 정상 상황에도 뜨므로 재등록 안내는 하지 않음)
STATE_TEXT = {cd.COOLING: "사용 중", cd.READY: "사용 가능", HIDDEN: "가려짐", PAGE_DIFF: "가려짐(페이지 다름)",
              cd.UNAVAILABLE: "사용 불가(탈것 등)"}
UNAVAILABLE_HOLD = 3.0  # '사용 중' 칸이 어둡게(사용 불가처럼) 보여도 이 시간까지는 사용 중 유지 — 전투 중 스킬을 쓰는 동안 칸이 어두워져
                        # 쿨 숫자가 흰 글자 기준에 못 미쳐 '사용 가능 → 사용 불가'로 읽히면 줄에서 빠졌다 붙었다(QA 5a9f431, 후보 #200 app.log)
COOLING_CONFIRM = 2  # '사용 중'은 연속 관측 이만큼부터 인정(약 0.44초) — 한 프레임 오판으로 줄·강조가 생기지 않게
from .widgets import checkbox, hint_label, switch

_log = logging.getLogger(__name__)
OBSERVE_INTERVAL = 0.22   # 관측 4~5회/초(9.1-2)
MAX_SLOTS = 8  # 세트당 칸 상한(제작자 시험 #194, 11-05 — 예전엔 세트 합계 8칸이라 세트 2가 3칸에서 막힘). 전체 = MAX_SLOTS × MAX_SETS
MAX_SETS = 4  # 세트(사용자 11-05) — 세트마다 오버레이 하나, 따로 두는 것은 위치만
# 쿨타임 전용 효과음 자리(11-05: 상태지원 음성 재사용을 뺌). 파일은 나중에 assets/sounds/에 이 이름으로 넣으면 바로 쓰인다.
# 파일이 없으면 알림음 체크 칸을 숨기고 소리를 내지 않는다(다른 알림음으로 대신하지 않음).
SOUND_FILE = "쿨타임 끝.mp3"


def sound_available() -> bool:
    from .notifier import sound_path
    return sound_path(SOUND_FILE).exists()


ICON_DIR_NAME = "cooldown_icons"
LIST_ICON = 28  # 목록 줄 아이콘 크기(px)


def icon_dir():
    from .. import paths
    return paths.user_data_dir() / ICON_DIR_NAME


def icon_path(sid: str):
    return icon_dir() / f"{sid}.png"


def save_icon(sid: str, cell) -> bool:
    """칸 그림을 목록 아이콘으로 저장(사용자 데이터 폴더 PNG, 40px 남짓 — 등록 순간과 처음 '사용 가능' 관측 때 한 번)."""
    from .. import image_io
    try:
        icon_dir().mkdir(parents=True, exist_ok=True)
        return bool(image_io.imwrite(icon_path(sid), cell))
    except OSError:
        return False


def _page_state(frame, ox, oy, slot) -> str | None:
    """페이지·단축바 보임 확인 → None(그대로 판정) | PAGE_DIFF | HIDDEN.
    - 그 줄 두 선택기 자리 모두 상자가 아니면 단축바가 안 보이는 화면(로그인·캐릭터 선택·로딩) → 그 줄 모든 칸 가려짐(키 없는 블록 칸 포함).
      둘 다 상자처럼 보일 때(애매)만 비교하지 않는다(453e71d 회귀: None을 '비교 안 함'으로 둬 장면을 칸으로 읽고 민트 강조가 떴다).
    - 칸이 '지금 키를 쓰는 단축바'에 있고 그 단축바가 등록 때와 같을 때만 페이지를 비교(제작자 11-06). 키 없는 단축바 칸은 페이지가 없어 비교하지 않는다.
    - 예전 등록분(page_rects 없음)은 저장 자리만 비교하고, 상자를 못 읽으면 가려짐(0.43.0 동작)."""
    def local(rect):
        px, py, pw, ph = rect
        return (px - ox, py - oy, pw, ph)
    signature = slot.get("page")
    rects = slot.get("page_rects")
    if rects:
        seen = cd.selectors_seen(frame, {int(b): local(r) for b, r in rects.items()})
        if not seen:
            return HIDDEN
        page_block = slot.get("page_block")
        if (not signature or len(seen) != 1 or page_block is None or seen[0] != page_block
                or slot.get("block") != page_block):
            return None
        return PAGE_DIFF if cd.same_page(frame, local(rects[str(page_block)]), signature) is False else None
    page_rect = slot.get("page_rect")
    if not signature or not page_rect:
        return None
    if not _in_key_block(slot["rect"], page_rect):
        return None  # 예전 등록분: 선택기가 있는 단축바(키 블록) 밖 칸은 페이지가 없다 — 비교하지 않음(QA f835a02)
    same = cd.same_page(frame, local(page_rect), signature)
    return HIDDEN if same is None else PAGE_DIFF if same is False else None


KEY_BLOCK_SPAN = 640  # 선택기 왼쪽으로 키 블록 칸이 있는 범위(상자 폭 15 기준 px) — 가운데 선택 1196: 칸 622~1170, 왼쪽 선택 576: 칸 2~550


def _in_key_block(cell_rect, page_rect) -> bool:
    """예전 등록분(page_rects 없음): 칸이 저장한 선택기 자리의 키 블록 범위(선택기 x − 640·s ≤ 칸 x < 선택기 x) 안인가."""
    sx, _sy, sw, _sh = page_rect
    s = sw / 15.0
    return sx - KEY_BLOCK_SPAN * s <= cell_rect[0] < sx


def _with_arrows(rect):
    """선택기 상자 + 양옆 화살표 자리(cd.selectors_seen이 보는 범위) — 공유 캡처가 화살표까지 찍게."""
    x, y, w, h = rect
    span = max(1, round(cd.ARROW_SPAN * w / 15.0)) + 1
    return [x - span, y, w + 2 * span, h]


def _reference(slot, refs: dict):
    """칸의 '사용 가능' 아이콘 기준(채도·밝기 평균) — 작업 스레드에서 한 번 읽어 캐시(매 관측 파일 읽기 금지). 아이콘이 아직 없으면 None."""
    sid = slot["id"]
    if not slot.get("icon_ok"):
        return None
    if sid not in refs:
        import cv2

        from .. import image_io
        try:
            icon = image_io.imread(icon_path(sid), cv2.IMREAD_COLOR)
        except Exception:  # noqa: BLE001
            icon = None
        refs[sid] = cd.mean_sv(icon)
    return refs[sid]


def observe(frame, origin, slots, last: dict, with_crops: bool, need_icon=frozenset(), now: float | None = None):
    """작업 스레드: 공유 캡처 한 장(물리 사각형 origin에서 시작)에서 칸마다 상태. 바뀐 칸만 돌려준다(없으면 None).
    last는 이 함수만 쓰는 이전 상태(작업 스레드 안에서만 바뀐다).
    need_icon: 목록 아이콘을 아직 '사용 가능' 그림으로 저장하지 않은 칸 — 사용 가능으로 보이면 여기서(작업 스레드) 저장하고 icons에 알린다.
    페이지 모양은 등록 스냅샷 그대로 쓴다 — 다시 저장하지 않는다(QA 5c01ccf: 위 줄은 Shift를 누르는 동안 2페이지가 보여 그 순간 덮어쓰면 평소 계속 숨김.
    쿨 중 등록 문제의 원인은 상자 모서리 픽셀로 확정 — 등록 스냅샷의 페이지 모양은 쿨 여부와 무관)."""
    ox, oy = origin
    changes, crops, icons = {}, {}, []
    streak = last.setdefault("_cooling_streak", {})  # 작업 스레드 전용 보조 값(칸 상태와 같은 사전에 둔다 — 지우면 함께 초기화)
    refs = last.setdefault("_icon_ref", {})
    dim_since = last.setdefault("_dim_since", {})  # 사용 중 칸이 어둡게 보이기 시작한 시각
    now = time.monotonic() if now is None else now
    for slot in slots:
        x, y, w, h = slot["rect"]
        cx, cy = x - ox, y - oy
        inside = cx >= 0 and cy >= 0  # 음수 인덱스는 numpy가 반대편에서 잘라 오므로 먼저 막는다
        cell = frame[cy:cy + h, cx:cx + w] if inside else frame[:0, :0]
        state = cd.classify(cell) if cell.shape[:2] == (h, w) else cd.UNKNOWN
        if state != cd.UNKNOWN:
            page = _page_state(frame, ox, oy, slot)
            if page is not None:
                state = page  # 페이지 다름 → 줄에서 빼고 목록에 따로 / 단축바 안 보임 → 가려짐
        if state == cd.UNKNOWN:
            state = HIDDEN
        if state == cd.READY and cd.is_dimmed(cell, _reference(slot, refs)):
            state = cd.UNAVAILABLE  # 탈것 등으로 칸이 어두움 — 가려짐처럼 줄에서 빼고 강조·알림 없음
        if state == cd.UNAVAILABLE and last.get(slot["id"]) == cd.COOLING:
            if now - dim_since.setdefault(slot["id"], now) < UNAVAILABLE_HOLD:
                continue  # 사용 중 유지(상태 변화 없음) — 3초 넘게 이어지면 그때 사용 불가
        else:
            dim_since.pop(slot["id"], None)
        streak[slot["id"]] = streak.get(slot["id"], 0) + 1 if state == cd.COOLING else 0
        if state == cd.COOLING and streak[slot["id"]] < COOLING_CONFIRM:
            continue  # 한 번만 '사용 중' → 아직 인정하지 않고 직전 상태 그대로(다음 관측에서 확인)
        if last.get(slot["id"]) != state:
            changes[slot["id"]] = state
            last[slot["id"]] = state
        if with_crops and state == cd.COOLING and cell.size:
            crops[slot["id"]] = cell.copy()
        if slot["id"] in need_icon and state == cd.READY and cell.size and save_icon(slot["id"], cell.copy()):
            icons.append(slot["id"])
            need_icon = need_icon - {slot["id"]}
            refs[slot["id"]] = cd.mean_sv(cell)  # 새 기준(다음 관측부터 icon_ok로 넘어온다)
    if not changes and not crops and not icons:
        return None
    return {"changes": changes, "crops": crops, "icons": icons}


class CooldownSection(QGroupBox):
    def __init__(self, watcher, parent=None) -> None:
        super().__init__("쿨타임 오버레이 (베타)", parent)
        self._watcher = watcher
        self._cfg = config.load_cooldown()
        self.row = CooldownRow()
        self._paused = False
        self._shutting_down = False
        self._last: dict[str, str] = {}
        self._overlays: dict = {}  # 세트 번호 → CooldownOverlay
        self._notifier = None
        self._selector = None

        v = QVBoxLayout(self)
        v.addWidget(hint_label("쓴 스킬이 사용 중인 동안 한 줄로 보여 주고, 다시 쓸 수 있게 되면 민트로 강조한 뒤 빼요."))
        v.addWidget(hint_label(PAGE_GUIDE))
        top = QHBoxLayout()
        self.enable = switch("쿨타임 오버레이 사용")
        self.enable.setChecked(self._cfg["enabled"])
        self.enable.toggled.connect(self._on_enable)
        top.addWidget(self.enable)
        top.addStretch(1)
        from .feature_copy import HELP
        from .help_dialog import help_button
        top.addWidget(help_button("쿨타임 오버레이 사용법", HELP["쿨타임 오버레이"], self))
        v.addLayout(top)
        row = QHBoxLayout()
        self.set_combo = QComboBox()
        self.set_combo.addItems([f"세트 {n}" for n in range(1, MAX_SETS + 1)])
        self.set_combo.setToolTip("등록할 칸을 넣을 세트 — 세트마다 오버레이가 따로 떠요(위치만 따로, 크기·투명도·고정은 공통)")
        self.set_combo.currentIndexChanged.connect(lambda _i: self._render_list())  # 고른 세트의 칸만 목록에
        row.addWidget(self.set_combo)
        self.add_btn = QPushButton("스킬 추가")
        self.add_btn.setToolTip("단축바 칸을 클릭해 등록해요(칸 테두리에 자동으로 맞춰요). 세트마다 최대 8칸")
        self.add_btn.clicked.connect(self._on_add)
        row.addWidget(self.add_btn)
        self.sound_chk = checkbox("사용 가능해지면 알림음")
        self.sound_chk.setChecked(self._cfg["sound"])
        self.sound_chk.toggled.connect(lambda on: self._save(sound=on))
        row.addWidget(self.sound_chk)
        self.sound_chk.setVisible(sound_available())  # 효과음 파일을 넣기 전까지는 숨김
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
        """고른 세트의 칸만: 스킬 아이콘(28px) + 이름 + 삭제. 위치 숫자는 마우스를 올리면(툴팁)."""
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        set_no = self.set_combo.currentIndex() + 1
        mine = [s for s in self.slots if s.get("set", 1) == set_no]
        from .settings_layout import danger_style
        for slot in mine:
            line = QWidget()
            h = QHBoxLayout(line)
            h.setContentsMargins(0, 0, 0, 0)
            x, y, w, hh = slot["rect"]
            tip = f"칸 {w}×{hh} @ ({x},{y})" + ("" if slot.get("page") else " · 페이지 확인 없음")
            if sum(1 for s in self.slots if s["rect"] == slot["rect"]) > 1:
                tip += " · 같은 자리·다른 페이지"
            icon = QLabel()
            icon.setFixedSize(LIST_ICON, LIST_ICON)
            icon.setPixmap(self._list_icon(slot["id"]))
            icon.setToolTip(tip)
            h.addWidget(icon)
            name = QLabel(slot["label"])
            name.setToolTip(tip)
            h.addWidget(name)
            state = QLabel(self.state_text(slot["id"]))
            state.setStyleSheet("color:palette(mid);")  # 페이지를 넘긴 정상 상황에도 뜨므로 경고색은 쓰지 않음
            if state.text() == PAGE_HIDDEN_TEXT:
                state.setToolTip(PAGE_HIDDEN_TIP)
            state.setObjectName("cooldownState")
            h.addWidget(state)
            h.addStretch(1)
            remove = QPushButton("－ 삭제")
            remove.setStyleSheet(danger_style())
            remove.clicked.connect(lambda _=False, sid=slot["id"]: self._remove(sid))
            h.addWidget(remove)
            line.setToolTip(tip)
            self.list_box.addWidget(line)
        if not mine:
            self.list_box.addWidget(hint_label(f"세트 {set_no}에 등록한 스킬이 없어요. '스킬 추가'로 단축바 칸을 클릭해 주세요."))
        self._update_add_button()

    @staticmethod
    def _list_icon(sid: str):
        """저장한 칸 그림(없으면 빈 칸 그림)."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
        path = icon_path(sid)
        pix = QPixmap(str(path)) if path.exists() else QPixmap()
        if not pix.isNull():
            return pix.scaled(LIST_ICON, LIST_ICON, Qt.AspectRatioMode.IgnoreAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        empty = QPixmap(LIST_ICON, LIST_ICON)
        empty.fill(QColor(0, 0, 0, 0))
        p = QPainter(empty)
        p.setPen(QPen(QColor(150, 150, 150, 180), 1, Qt.PenStyle.DashLine))
        p.drawRect(1, 1, LIST_ICON - 3, LIST_ICON - 3)
        p.end()
        return empty

    def _count(self, set_no: int) -> int:
        return sum(1 for s in self.slots if s.get("set", 1) == set_no)

    def _update_add_button(self) -> None:
        """추가 버튼은 '고른 세트'가 가득일 때만 끈다(세트마다 8칸)."""
        self.add_btn.setEnabled(self._count(self.set_combo.currentIndex() + 1) < MAX_SLOTS)

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
        set_no = self.set_combo.currentIndex() + 1
        if self._count(set_no) >= MAX_SLOTS:
            self.status.setText(f"이 세트는 최대 {MAX_SLOTS}칸까지 등록할 수 있어요.")
            return None
        page_rect = page = page_block = None
        page_rects = kb = None
        source, row, block = target.info.get("source"), target.info.get("row", 0), target.info.get("block")
        if frame is not None and source is not None:
            # 페이지는 '키를 쓰는 단축바'에만 있다 — 그 줄 선택기 위치로 키 블록을 정하고, 칸이 키 블록일 때만 페이지 모양 저장
            rects = cd.selector_rects(source, row)
            page_rects = {str(b): [r[0] + ox, r[1] + oy, r[2], r[3]] for b, r in rects.items()}
            kb = cd.key_block(frame, rects)
            if kb is not None and kb == block:
                page = cd.page_signature(frame, rects[kb])
                if page is not None:
                    page_rect, page_block = page_rects[str(kb)], kb
        if self._duplicate(rect, page, frame, rects[kb] if page is not None else None):
            self.status.setText("이미 등록한 칸이에요.")
            return None
        used = {s["label"] for s in self.slots}
        label = next(f"스킬 {n}" for n in range(1, MAX_SLOTS * MAX_SETS + 2) if f"스킬 {n}" not in used)  # 전체에서 겹치지 않게
        cell = frame[y:y + h, x:x + w] if frame is not None else None
        slot = {"id": uuid.uuid4().hex[:8], "rect": rect, "page_rect": page_rect, "page": page, "label": label, "row": row,
                "set": set_no, "icon_ok": False, "block": block, "page_block": page_block, "page_rects": page_rects}
        if cell is not None and cell.shape[:2] == (h, w):  # 등록 스냅샷에서 칸을 잘라 목록 아이콘으로(처음 '사용 가능'일 때 한 번 더)
            save_icon(slot["id"], cell.copy())
        self._save(slots=self.slots + [slot])
        self._last.clear()
        self._render_list()
        keyless = page is None and kb is not None and kb != block  # 선택기는 읽었는데 칸이 키 없는 단축바
        note = "" if page else (" (페이지가 없는 단축바라 페이지 확인 없이 봐요)" if keyless
                                else " (페이지 숫자를 못 읽어 페이지 확인 없이 봐요)")
        self.status.setText(f"{label}을(를) 세트 {set_no}에 등록했어요." + note)
        _log.info("쿨타임 칸 등록: %s(세트 %d) 칸 %s 페이지 %s", label, set_no, rect, "있음" if page else "없음")
        return slot

    def _duplicate(self, rect, page, frame, local_page_rect) -> bool:
        """같은 자리·같은 페이지면 중복. 같은 자리라도 페이지 숫자가 다르면(변신·Shift 페이지) 따로 등록할 수 있다(사용자 11-06)."""
        for other in (s for s in self.slots if s["rect"] == rect):
            if not page or not other.get("page"):
                return True  # 페이지를 모르면 구분할 수 없음
            if cd.same_page(frame, local_page_rect, other["page"]) is not False:
                return True
        return False

    # ---- 칸 상태(목록 표시·app.log) ----------------------------------------------------------
    def _name_of(self, sid: str) -> str:
        slot = next((s for s in self.slots if s["id"] == sid), None)
        return f"{slot['label']}(세트 {slot.get('set', 1)})" if slot else sid

    def _note_states(self, changes: dict) -> None:
        """관측이 알린 칸 상태 변화 → 목록 상태 글자, 상태가 바뀔 때만 app.log 한 줄(가려짐을 조용히 넘기지 않게)."""
        if not changes:
            return
        now = time.monotonic()
        states = self.__dict__.setdefault("_states", {})
        since = self.__dict__.setdefault("_page_since", {})
        for sid, state in changes.items():
            before = states.get(sid)
            states[sid] = state
            if state == PAGE_DIFF:
                since.setdefault(sid, now)
            else:
                since.pop(sid, None)
            if before != state:
                _log.info("쿨타임 칸 상태: %s %s → %s", self._name_of(sid), STATE_TEXT.get(before, "처음"),
                          STATE_TEXT.get(state, state))
        self._render_list()

    def state_text(self, sid: str) -> str:
        state = self.__dict__.get("_states", {}).get(sid)
        if state == PAGE_DIFF and time.monotonic() - self.__dict__.get("_page_since", {}).get(sid, time.monotonic()) >= PAGE_WARN_SECONDS:
            return PAGE_HIDDEN_TEXT
        return STATE_TEXT.get(state, "")

    def _remove(self, sid: str) -> None:
        self._save(slots=[s for s in self.slots if s["id"] != sid])
        try:
            icon_path(sid).unlink(missing_ok=True)
        except OSError:
            pass
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
        for ov in self._overlays.values():
            ov.set_scale(value)

    def _on_opacity(self, value: int) -> None:
        self._save(opacity=int(value))
        for ov in self._overlays.values():
            ov.set_opacity(value)

    def _on_lock(self) -> None:
        locked = not self._cfg["locked"]
        self._save(locked=locked)
        from .settings_layout import set_lock_text
        set_lock_text(self.lock_btn, locked)
        for ov in self._overlays.values():
            ov.set_locked(locked)
        self._show_row()

    # ---- 관측·표시 ------------------------------------------------------------------------------

    def _enabled(self) -> bool:
        return not (self._shutting_down or self._paused or not self._cfg["enabled"] or not self.slots)

    def _game_active(self) -> bool:
        try:
            return bool(self._watcher.is_game_active())
        except Exception:  # noqa: BLE001
            return False

    def _running(self) -> bool:
        """관측(판정)은 게임이 앞일 때만."""
        return self._enabled() and self._game_active()

    @property
    def _overlay(self):
        """1세트 오버레이(예전 한 개짜리와 같은 자리 — 테스트·호환)."""
        return self._overlays.get(1)

    def _dragging(self) -> bool:
        return any(getattr(ov, "_drag", None) is not None for ov in self._overlays.values())

    def _set_of(self) -> dict[str, int]:
        return {s["id"]: s.get("set", 1) for s in self.slots}

    def _sets(self) -> list[int]:
        """칸이 있는 세트(칸 없는 세트는 오버레이를 띄우지 않는다)."""
        return sorted({s.get("set", 1) for s in self.slots})

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
        if not self._running():
            capture.clear("cooldown")  # 관측은 멈춘다(게임이 앞일 때만)
            if (self.row.row or self._last) and not (self._enabled() and self._display_active()):
                self.row.reset()  # 표시도 끝날 때만 줄을 비운다(우리 창이 잠깐 앞이면 그대로 둠)
                self._last.clear()
            if self._needs_refresh():
                self._show_row()
            return
        slots = [dict(s) for s in self.slots]
        selectors = ([s["page_rect"] for s in slots if s.get("page_rect")]
                     + [r for s in slots for r in (s.get("page_rects") or {}).values()])  # 키 블록을 정하려고 두 선택기 자리 모두 찍는다
        rects = [s["rect"] for s in slots] + [_with_arrows(r) for r in selectors]  # 선택기는 양옆 ◀▶ 화살표까지
        x0, y0 = min(r[0] for r in rects), min(r[1] for r in rects)
        x1, y1 = max(r[0] + r[2] for r in rects), max(r[1] + r[3] for r in rects)
        last = self._last
        from ..system import dwm_thumbnail
        crops = not dwm_thumbnail.available()  # 썸네일을 못 쓸 때만 그림을 넘긴다
        need_icon = frozenset(s["id"] for s in slots if not s.get("icon_ok"))
        capture.set_request("cooldown", (x0, y0, x1 - x0, y1 - y0), OBSERVE_INTERVAL,
                            lambda frame: observe(frame, (x0, y0), slots, last, crops, need_icon))
        if self.row.expire(time.monotonic()):
            self._show_row()
        elif self._needs_refresh():
            self._show_row()
        since = self.__dict__.get("_page_since", {})
        flagged = self.__dict__.setdefault("_page_flagged", set())
        due = {sid for sid, t0 in since.items() if time.monotonic() - t0 >= PAGE_WARN_SECONDS}
        if due != flagged & set(since):  # 페이지 다름이 3초 넘게 이어진 칸 → 목록에 '다른 페이지라 숨김'(한 번만 다시 그림)
            flagged.clear()
            flagged.update(due)
            if due:
                self._render_list()

    def _on_delivered(self, name, payload) -> None:
        if name != "cooldown" or not self._running():
            return
        if payload.get("icons"):  # 작업 스레드가 '사용 가능' 그림으로 아이콘을 다시 저장함 → 표시만 해 두고 목록 새로
            done = set(payload["icons"])
            self._save(slots=[{**s, "icon_ok": True} if s["id"] in done else s for s in self.slots])
            self._render_list()
        self._note_states(payload.get("changes") or {})
        before = set(self.row.until)
        sound = self.row.update(payload["changes"], time.monotonic())
        pixmaps = None
        if payload.get("crops"):
            from .skillbar_mirror import _np_to_pixmap
            pixmaps = {sid: _np_to_pixmap(c) for sid, c in payload["crops"].items()}
        self._show_row(pixmaps)
        sets = self._set_of()
        for sid in set(self.row.until) - before:  # 방금 사용 가능해진 칸 → 자기 세트 오버레이 안에서 한 번 커졌다 돌아오기
            ov = self._overlays.get(sets.get(sid, 1))
            if ov is not None:
                ov.pop(sid)
        if sound and self._cfg["sound"]:
            self._play()

    def _should_show(self, set_no: int | None = None) -> bool:
        """그 세트(없으면 아무 세트나)를 띄울지 — 표시 조건은 세트마다 같다. 칸 없는 세트는 띄우지 않는다."""
        if not (self._enabled() and self._display_active()):
            return False
        sets = self._sets() if set_no is None else [set_no]
        of = self._set_of()
        for n in sets:
            if n in self._sets() and (not self._cfg["locked"] or any(of.get(sid) == n for sid in self.row.row)):
                return True
        return False

    def _needs_refresh(self) -> bool:
        for n in range(1, MAX_SETS + 1):
            ov = self._overlays.get(n)
            want = self._should_show(n)
            if (ov is None and want) or (ov is not None and ov.isVisible() != want):
                return True
        return False

    def _ensure_overlay(self, set_no: int = 1):
        ov = self._overlays.get(set_no)
        if ov is None:
            from .cooldown_overlay import CooldownOverlay
            ov = CooldownOverlay(self._cfg["scale"], set_no)
            ov.set_opacity(self._cfg["opacity"])
            ov.set_locked(self._cfg["locked"])
            pos = self._cfg.get("positions", {}).get(set_no)
            if pos:
                ov.move(pos["x"], pos["y"])
            else:
                self._default_position(ov, set_no)
            ov.moved.connect(lambda n=set_no, o=ov: self._save_position(n, o))
            self._overlays[set_no] = ov
        return ov

    def _save_position(self, set_no: int, ov) -> None:
        positions = dict(self._cfg.get("positions") or {})
        positions[set_no] = {"x": ov.x(), "y": ov.y()}
        self._cfg["positions"] = positions
        config.save_cooldown({"setPos": {str(n): p for n, p in positions.items() if p}})

    @staticmethod
    def _default_position(ov, set_no: int = 1) -> None:
        """처음 위치: 화면 가운데 아래쪽, 세트마다 조금씩 아래로 — 화면 좌표로 저장(10.1)."""
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            g = screen.geometry()
            ov.move(g.x() + g.width() // 2 - 60, g.y() + int(g.height() * 0.62) + (set_no - 1) * 70)

    def _show_row(self, pixmaps=None) -> None:
        of = self._set_of()
        sources = {s["id"]: s["rect"] for s in self.slots}
        for n in range(1, MAX_SETS + 1):
            if not self._should_show(n):
                ov = self._overlays.get(n)
                if ov is not None:
                    ov.hide()
                continue
            ov = self._ensure_overlay(n)
            ov.set_sources({sid: r for sid, r in sources.items() if of.get(sid) == n})
            ov.set_items([(sid, sid in self.row.until) for sid in self.row.row if of.get(sid) == n], pixmaps)
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
        if not sound_available():
            return
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
        for ov in self._overlays.values():
            ov.close()
