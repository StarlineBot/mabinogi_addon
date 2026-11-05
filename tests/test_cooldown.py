"""쿨타임 오버레이(쿨타임 명세 10절) — 판정·페이지 번호(tests/data 실화면)·줄 상태·공유 캡처·구역(제작자 전용)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon.detect import cooldown as cd
from mabinogi_addon.detect.click_targets import Target, skill_cells
from mabinogi_addon.detect.skillbar_anchor import locate_skillbar
from mabinogi_addon.tracker.cooldown_row import COOLING, HIDDEN, READY, CooldownRow

_app = QApplication.instance() or QApplication([])
DATA = Path(__file__).parent / "data"


def _read(name):
    return cv2.imdecode(np.fromfile(str(DATA / name), np.uint8), cv2.IMREAD_COLOR)


_cache = {}


def _screen(name):
    if name not in _cache:
        frame = _read(name)
        box = locate_skillbar(frame)
        cells = {(t.info["block"], t.info["row"], t.info["group"], t.info["slot"]): t for t in skill_cells(box)}
        _cache[name] = (frame, box, cells)
    return _cache[name]


def _classify(name, key):
    frame, _box, cells = _screen(name)
    x, y, w, h = cells[key].rect
    return cd.classify(frame[y:y + h, x:x + w])


# ---- 사용 중 판정 -------------------------------------------------------------------------------
@pytest.mark.parametrize("name,cooling", [
    ("image01.png", {(0, 1, 1, 0), (1, 1, 2, 1)}),
    ("2026-10-30_windowed_wireweb_1.png", {(0, 0, 0, 0), (0, 0, 1, 0), (1, 0, 0, 0)}),
    ("2026-10-30_windowed_wireweb_2.png", {(0, 0, 0, 0), (0, 0, 1, 0), (0, 0, 1, 3), (0, 1, 1, 0), (1, 0, 0, 0)}),
    ("mabinogi_2026_10_30_214648.png", {(0, 1, 0, 0), (0, 1, 0, 1)}),
    # 제작자 실게임 11-05: 아래부터 차오르는 밝은 게이지 + 가운데 숫자 — 예전 밝기 게이트는 47·21만 잡았다
    ("스크린샷 2026-11-05 203318.png", {(1, 0, 0, 1), (1, 0, 0, 2), (1, 1, 0, 3), (1, 1, 1, 2), (1, 1, 2, 1)}),  # 47·17·21·4·5
    ("스크린샷 2026-11-05 203332.png", {(1, 0, 0, 1), (1, 0, 0, 2), (1, 1, 0, 3), (1, 1, 2, 1)}),  # 31·2·6·7
])
def test_cooling_cells_exactly(name, cooling):
    _frame, _box, cells = _screen(name)
    found = {k for k in cells if _classify(name, k) == cd.COOLING}
    assert found == cooling  # 나머지(아이콘·귀퉁이 수량·단축키 글자만 있는 칸)는 사용 가능


def test_digit_over_bright_flash_stays_cooling():
    """0.x초 하얀 번쩍임으로 칸 위쪽까지 밝아도 숫자(검은 테두리)가 남아 있으면 사용 중."""
    frame, _box, cells = _screen("스크린샷 2026-11-05 203332.png")
    x, y, w, h = cells[(1, 0, 0, 2)].rect  # '2' — 위쪽 띠 밝기 196
    cell = frame[y:y + h, x:x + w]
    assert cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)[: h // 3, :, 2].mean() > 150
    assert cd.classify(cell) == cd.COOLING


def test_old_false_positives_are_ready():
    """예전 평균 밝기 판정의 오탐: 나눔고딕 1080 흑백 날개 아이콘(흰 곡선 조각)."""
    name = "2026-11-03_나눔고딕_1080_시간없는목록.png"
    _frame, _box, cells = _screen(name)
    assert _classify(name, (1, 0, 1, 0)) == cd.READY and _classify(name, (1, 0, 1, 3)) == cd.READY


def test_too_small_or_missing_cell_is_unknown():
    assert cd.classify(None) == cd.UNKNOWN
    assert cd.classify(np.zeros((10, 10, 3), np.uint8)) == cd.UNKNOWN


def test_bright_cell_is_ready_and_dark_blank_is_ready():
    assert cd.classify(np.full((40, 40, 3), 200, np.uint8)) == cd.READY
    assert cd.classify(np.full((40, 40, 3), 60, np.uint8)) == cd.READY  # 회색 바탕이라도 숫자가 없으면


# ---- 페이지 번호 ----------------------------------------------------------------------------------
def test_page_box_found_on_both_rows_and_rows_differ():
    frame, box, _cells = _screen("image01.png")
    r0, r1 = cd.page_rect(frame, box, 0), cd.page_rect(frame, box, 1)
    assert r0 == (584, 55, 15, 16) and r1 == (584, 104, 15, 16)
    s0 = cd.page_signature(frame, r0)
    assert s0 and s0.startswith("15x16:")
    assert cd.same_page(frame, r0, s0) is True
    assert cd.same_page(frame, r1, s0) is False  # 윗줄·아랫줄 페이지가 다름


@pytest.mark.parametrize("other", ["image02.png", "image03.png", "image04.png"])
def test_same_page_across_screens(other):
    f1, b1, _ = _screen("image01.png")
    f2, b2, _ = _screen(other)
    for row in (0, 1):
        sig = cd.page_signature(f1, cd.page_rect(f1, b1, row))
        assert cd.same_page(f2, cd.page_rect(f2, b2, row), sig) is True
        assert cd.same_page(f2, cd.page_rect(f2, b2, 1 - row), sig) is False


def test_unreadable_page_box_is_none_and_no_signature_passes():
    frame, box, _ = _screen("image01.png")
    sig = cd.page_signature(frame, cd.page_rect(frame, box, 0))
    blank = np.full_like(frame, 128)
    assert cd.same_page(blank, (584, 55, 15, 16), sig) is None  # 가려짐
    assert cd.same_page(blank, (584, 55, 15, 16), None) is True  # 페이지를 저장 못 한 칸은 확인 안 함
    assert cd.page_rect(blank, box, 0) is None


# ---- 줄 상태 ------------------------------------------------------------------------------------
def test_row_order_highlight_sound_and_removal():
    row = CooldownRow(highlight=1.0)
    assert row.update({"a": READY, "b": READY}, 0) is False  # 처음부터 사용 가능 → 강조 없음
    row.update({"b": COOLING}, 1)
    row.update({"a": COOLING}, 2)
    assert row.row == ["b", "a"]  # 쓴 순서
    assert row.update({"b": READY}, 3) is True and row.until == {"b": 4.0}
    assert row.row == ["b", "a"]  # 강조 중엔 자리 유지
    assert row.expire(4.0) is True and row.row == ["a"]  # 빠지고 당겨짐


def test_two_ready_at_once_one_sound_and_recool_cancels_highlight():
    row = CooldownRow()
    row.update({"a": READY, "b": READY}, 0)
    row.update({"a": COOLING, "b": COOLING}, 1)
    assert row.update({"a": READY, "b": READY}, 2) is True  # 소리는 한 번(호출당)
    row.update({"a": COOLING}, 2.5)  # 강조 중 다시 사용
    assert "a" not in row.until and row.row == ["b", "a"]


def test_hidden_or_page_change_drops_without_highlight():
    row = CooldownRow()
    row.update({"a": COOLING}, 0)
    assert row.update({"a": HIDDEN}, 1) is False and row.row == []
    row.update({"a": READY}, 2)  # 다시 보였을 때 이미 사용 가능 → 강조 없음
    assert row.until == {} and row.row == []


def test_already_cooling_on_start_joins_row_and_prune_reset():
    row = CooldownRow()
    row.update({"a": COOLING, "b": COOLING}, 0)
    assert row.row == ["a", "b"]
    row.prune(["b"])
    assert row.row == ["b"]
    row.reset()
    assert row.row == [] and row.until == {}


# ---- 관측(작업 스레드 함수) ----------------------------------------------------------------------
def _slot(frame, box, cells, key, sid):
    x, y, w, h = cells[key].rect
    pr = cd.page_rect(frame, box, key[1])
    return {"id": sid, "rect": [x, y, w, h], "page_rect": list(pr), "page": cd.page_signature(frame, pr), "row": key[1]}


def test_observe_reports_only_changes_and_hides_on_other_page():
    from mabinogi_addon.ui.cooldown_section import observe
    frame, box, cells = _screen("image01.png")
    slots = [_slot(frame, box, cells, (0, 1, 1, 0), "cool"), _slot(frame, box, cells, (0, 0, 0, 0), "ready")]
    last = {}
    out = observe(frame, (0, 0), slots, last, with_crops=False)
    assert out["changes"] == {"cool": COOLING, "ready": READY}
    assert observe(frame, (0, 0), slots, last, with_crops=False) is None  # 바뀐 칸만
    slots[0]["page"] = slots[1]["page"]  # 다른 줄 페이지 모양 → 페이지 다름(줄에서 빼되 목록엔 따로 알림, 11-06)
    from mabinogi_addon.ui.cooldown_section import PAGE_DIFF
    assert observe(frame, (0, 0), slots, last, with_crops=False)["changes"] == {"cool": PAGE_DIFF}


def test_observe_with_origin_offset_and_crops():
    from mabinogi_addon.ui.cooldown_section import observe
    frame, box, cells = _screen("image01.png")
    slot = _slot(frame, box, cells, (0, 1, 1, 0), "cool")
    x0, y0 = slot["rect"][0] - 10, slot["page_rect"][1] - 60  # 칸·페이지 상자를 덮는 일부만
    out = observe(frame[y0:, x0:], (x0, y0), [slot], {}, with_crops=True)
    assert out["changes"] == {"cool": COOLING} and out["crops"]["cool"].shape == (40, 40, 3)
    # 칸이 캡처 밖(왼쪽)으로 벗어나면 반대편을 잘라 오지 않고 '가려짐'
    x1 = slot["rect"][0] + 20
    assert observe(frame[y0:, x1:], (x1, y0), [slot], {}, with_crops=False)["changes"] == {"cool": HIDDEN}


# ---- 공유 캡처 ----------------------------------------------------------------------------------
def test_shared_capture_worker_grabs_union_once_and_splits(monkeypatch):
    from mabinogi_addon.ui import skillbar_capture as sc
    monkeypatch.setattr(sc.SkillbarCapture, "INLINE", False)
    big = np.arange(200 * 300 * 3, dtype=np.uint8).reshape(200, 300, 3)
    grabs, got, done = [], {}, threading.Event()

    def grab(x, y, w, h):
        grabs.append((x, y, w, h))
        return big[y:y + h, x:x + w].copy()
    cap = sc.SkillbarCapture(grab=grab)
    worker_threads = set()

    def handler(name):
        def h(part):
            worker_threads.add(threading.current_thread().name)
            got[name] = part.copy()
            if len(got) == 2:
                done.set()
            return None
        return h
    try:
        with cap._lock:  # 두 요청을 같은 회차에 받게 미리 넣는다
            cap._requests["a"] = {"rect": (10, 20, 30, 40), "interval": 10.0, "handler": handler("a"), "due": 0.0}
            cap._requests["b"] = {"rect": (100, 50, 20, 10), "interval": 10.0, "handler": handler("b"), "due": 0.0}
        cap._ensure_thread()
        assert done.wait(3)
    finally:
        cap.stop()
    assert grabs[0] == (10, 20, 110, 40)  # 덮는 사각형 하나
    assert np.array_equal(got["a"], big[20:60, 10:40]) and np.array_equal(got["b"], big[50:60, 100:120])
    assert worker_threads == {"skillbar-capture"}  # 처리는 작업 스레드


def test_shared_capture_inline_delivers_and_clear():
    from mabinogi_addon.ui.skillbar_capture import SkillbarCapture
    cap = SkillbarCapture(grab=lambda x, y, w, h: np.zeros((h, w, 3), np.uint8))
    out = []
    cap.delivered.connect(lambda n, r: out.append((n, r)))
    cap.set_request("x", (0, 0, 4, 3), 0.1, lambda f: f.shape)
    assert out == [("x", (3, 4, 3))]
    cap.set_request("x", None, 0.1, lambda f: 1)  # None = 그만
    assert not cap.active("x")


# ---- 오버레이 ------------------------------------------------------------------------------------
def test_overlay_row_layout_examples_and_change_only_repaint():
    from mabinogi_addon.ui.cooldown_overlay import CooldownOverlay
    ov = CooldownOverlay(100)
    try:
        ov.set_locked(False)
        assert [c[2] for c in ov._cells()] == [True, True, True]  # 비었을 때 예시 3칸(위치 잡기)
        ov.set_locked(True)
        assert ov._cells() == []
        ov.set_items([("a", False), ("b", True)])
        assert ov.items() == [("a", False), ("b", True)] and ov.width() >= 2 * 40
        calls = []
        ov._relayout = lambda: calls.append(1)
        ov.set_items([("a", False), ("b", True)])
        assert calls == []  # 같으면 다시 그리지 않는다
        ov.set_scale(200)
        assert calls == [1]
    finally:
        ov.close()


# ---- 구역(제작자 전용) -------------------------------------------------------------------------
class _Watcher:
    active = True

    def is_game_active(self):
        return self.active

    def is_self_active(self):
        return False


@pytest.fixture
def creator(monkeypatch):
    from mabinogi_addon import feature_access
    monkeypatch.setattr(feature_access, "is_creator", lambda: True)


def test_section_hidden_and_idle_for_non_creator(monkeypatch):
    from mabinogi_addon import config, feature_access
    from mabinogi_addon.ui import skillbar_capture
    from mabinogi_addon.ui.skillbar_tab import SkillbarTab
    monkeypatch.setattr(feature_access, "is_creator", lambda: False)
    config.save_cooldown({"enabled": True, "slots": [{"id": "s1", "rect": [0, 0, 40, 40], "label": "스킬 1"}]})
    tab = SkillbarTab(_Watcher())
    try:
        tab.show()
        tab.cooldown._tick()
        assert tab.cooldown.isHidden()
        assert not skillbar_capture.shared().active("cooldown")
        assert tab.cooldown._overlay is None
    finally:
        tab.shutdown()
        tab.close()


def test_section_registers_snapped_cell_with_page_and_observes(creator, monkeypatch):
    from mabinogi_addon import config
    from mabinogi_addon.ui import skillbar_capture
    from mabinogi_addon.ui.cooldown_section import CooldownSection
    frame, box, cells = _screen("image01.png")
    monkeypatch.setattr(skillbar_capture.SkillbarCapture, "_grab",
                        lambda self, x, y, w, h: frame[y:y + h, x:x + w].copy())
    sec = CooldownSection(_Watcher())
    try:
        assert sec.allowed()
        slot = sec.register(cells[(0, 1, 1, 0)], frame, (0, 0))
        assert slot["page"] and slot["page_rect"] == [584, 104, 15, 16] and slot["row"] == 1
        assert sec.register(cells[(0, 1, 1, 0)], frame, (0, 0)) is None  # 중복
        assert config.load_cooldown()["slots"][0]["rect"] == slot["rect"]
        sec.enable.setChecked(True)  # 켜면 관측 → INLINE 공유 캡처로 바로 판정·전달
        assert sec.row.row == [slot["id"]]
        assert sec._overlay is not None and sec._overlay.items() == [(slot["id"], False)]
        sec._remove(slot["id"])
        assert sec.row.row == [] and config.load_cooldown()["slots"] == []
    finally:
        sec.shutdown()


def test_section_max_eight_per_set_and_ignores_plain_drag(creator):
    """세트마다 8칸(제작자 시험 #194: 예전엔 합계 8칸이라 세트 1에 5칸이면 세트 2는 3칸에서 막힘)."""
    from mabinogi_addon import config
    from mabinogi_addon.ui.cooldown_section import MAX_SLOTS, CooldownSection
    sec = CooldownSection(_Watcher())
    try:
        for set_index, y in ((0, 0), (1, 100)):
            sec.set_combo.setCurrentIndex(set_index)
            for i in range(MAX_SLOTS):
                assert sec.register(Target("skill", (i * 50, y, 40, 40), "단축바 칸", {}), None) is not None
            assert not sec.add_btn.isEnabled()  # 고른 세트가 가득
            assert sec.register(Target("skill", (999, y, 40, 40), "단축바 칸", {}), None) is None  # 같은 세트 9번째 거부
            assert sec.status.text() == "이 세트는 최대 8칸까지 등록할 수 있어요."
        sec.set_combo.setCurrentIndex(2)
        assert sec.add_btn.isEnabled()  # 다른 세트는 비어 있어 켜짐
        labels = [s["label"] for s in sec.slots]
        assert len(labels) == 16 and len(set(labels)) == 16  # 스킬 번호는 전체에서 겹치지 않게
        sec.set_combo.setCurrentIndex(0)
        assert not sec.add_btn.isEnabled()
        assert len(config.load_cooldown()["slots"]) == 16  # 저장·다시 읽기에서 16칸 유지
        sec._snap_hit = False
        sec._on_selected(1, 2, 3, 4)
        assert "클릭" in sec.status.text()
    finally:
        sec.shutdown()


def test_section_stops_when_game_inactive_or_paused(creator):
    from mabinogi_addon import config
    from mabinogi_addon.ui import skillbar_capture
    from mabinogi_addon.ui.cooldown_section import CooldownSection
    config.save_cooldown({"enabled": True, "slots": [{"id": "s1", "rect": [0, 0, 40, 40], "label": "스킬 1"}]})
    watcher = _Watcher()
    watcher.active = False
    sec = CooldownSection(watcher)
    try:
        sec._tick()
        assert not skillbar_capture.shared().active("cooldown")
        sec.row.update({"s1": COOLING}, time.monotonic())
        sec.set_paused(True)
        assert sec.row.row == []  # 일시정지 → 줄 비움(다시 보일 때 처음부터)
    finally:
        sec.shutdown()


def test_section_visible_in_skillbar_tab_for_creator(creator):
    from mabinogi_addon.ui.skillbar_tab import SkillbarTab
    tab = SkillbarTab(_Watcher())
    try:
        tab.show()
        tab.cooldown._tick()
        assert tab.cooldown.isVisible()
    finally:
        tab.shutdown()
        tab.close()


# ---- 표시 조건(제작자 실게임 11-05: 오버레이를 누르면 우리 창이 앞 → 숨겨져 끌기가 끊김) ----------------------------
class _FrontWatcher:
    def __init__(self, game=False, own=True):
        self.game, self.own = game, own

    def is_game_active(self):
        return self.game

    def is_self_active(self):
        return self.own


def _press(ov, dx=0, dy=0, kind=None):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    p = ov.frameGeometry().topLeft() + __import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(5 + dx, 5 + dy)
    return QMouseEvent(kind or QEvent.Type.MouseButtonPress, QPointF(5, 5), QPointF(p.x(), p.y()),
                       Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def test_unlocked_overlay_stays_and_drag_continues_while_our_app_is_front(creator, monkeypatch):
    from PySide6.QtCore import QEvent
    from mabinogi_addon import config
    from mabinogi_addon.ui import skillbar_capture
    from mabinogi_addon.ui.cooldown_section import CooldownSection
    config.save_cooldown({"enabled": True, "locked": False,
                          "slots": [{"id": "s1", "rect": [0, 0, 40, 40], "label": "스킬 1"}]})
    monkeypatch.setattr(skillbar_capture.SkillbarCapture, "_grab", lambda self, x, y, w, h: np.zeros((h, w, 3), np.uint8))
    watcher = _FrontWatcher(game=True, own=False)
    from PySide6.QtWidgets import QWidget
    holder = QWidget()  # 보이지 않는 부모 = 구역이 화면에 없음(다른 탭을 보는 중과 같음)
    sec = CooldownSection(watcher, holder)
    try:
        sec._tick()
        ov = sec._overlay
        assert ov is not None and ov.isVisible()  # 고정 해제 = 예시 칸
        watcher.game, watcher.own = False, True  # 오버레이를 누르는 순간 우리 창이 앞
        start = ov.pos()
        ov.mousePressEvent(_press(ov))
        sec._tick()
        assert ov.isVisible()  # 숨기지 않는다
        ov.mouseMoveEvent(_press(ov, 30, 20, QEvent.Type.MouseMove))
        sec._tick()
        assert ov.isVisible() and ov.pos() != start  # 끌기가 이어짐
        assert not skillbar_capture.shared().active("cooldown")  # 관측은 게임이 앞일 때만
        ov.mouseReleaseEvent(_press(ov, 30, 20, QEvent.Type.MouseButtonRelease))
        assert config.load_cooldown()["positions"][1] == {"x": ov.x(), "y": ov.y()}
    finally:
        sec.shutdown()


def test_locked_overlay_hides_when_another_app_is_front_and_keeps_row_while_ours(creator):
    from mabinogi_addon import config
    from mabinogi_addon.ui.cooldown_section import CooldownSection
    config.save_cooldown({"enabled": True, "locked": True,
                          "slots": [{"id": "s1", "rect": [0, 0, 40, 40], "label": "스킬 1"}]})
    watcher = _FrontWatcher(game=True, own=False)
    from PySide6.QtWidgets import QWidget
    holder = QWidget()
    sec = CooldownSection(watcher, holder)
    try:
        sec.row.update({"s1": COOLING}, time.monotonic())
        sec._show_row()
        assert sec._overlay.isVisible()
        watcher.game, watcher.own = False, False  # 다른 프로그램이 앞
        sec._tick()
        assert not sec._overlay.isVisible() and sec.row.row == []
        sec.row.update({"s1": COOLING}, time.monotonic())
        watcher.game, watcher.own = False, True  # 우리 앱이 앞, 고정 중, 구역은 안 보임 → 숨김(다른 오버레이 탭과 같음)
        sec._tick()
        assert not sec._overlay.isVisible()
    finally:
        sec.shutdown()


def test_boss_bar_overlay_also_stays_while_dragging_with_our_app_front(monkeypatch):
    from mabinogi_addon import config, feature_access
    from mabinogi_addon.ui import boss_tab as bt
    monkeypatch.setattr(feature_access, "is_creator", lambda: True)
    config.save_boss_bar_overlay({"enabled": True, "locked": False})
    watcher = _FrontWatcher(game=True, own=False)
    tab = bt.BossTab(watcher)
    tab._timer.stop()
    sec = tab.bar_section
    try:
        sec._tick()
        assert sec._overlay is not None and sec._overlay.isVisible()  # 고정 해제 = 예시 바
        watcher.game, watcher.own = False, True
        sec._overlay.mousePressEvent(_press(sec._overlay))
        sec._tick()
        assert sec._overlay.isVisible()
    finally:
        tab.shutdown()


# ---- 알림음(제작자 시험 11-05: 상태지원 음성이 나던 것) ----------------------------------------------------
def test_sound_slot_waits_for_file_and_is_off_by_default(creator, monkeypatch, tmp_path):
    """효과음은 아직 없음(11-05 사용자: 넣을 자리만) — 파일이 없으면 체크 칸 숨김·무음, 넣으면 그 파일로."""
    from mabinogi_addon import config
    from mabinogi_addon.ui import cooldown_section, notifier
    from mabinogi_addon.ui.cooldown_section import CooldownSection
    assert cooldown_section.SOUND_FILE == "쿨타임 끝.mp3"
    assert not cooldown_section.sound_available()
    assert config.load_cooldown()["sound"] is False  # 기본 꺼짐
    played = []
    monkeypatch.setattr(notifier.SoundNotifier, "play", lambda self, key: played.append(self._sounds[key]) or True)
    sec = CooldownSection(_Watcher())
    try:
        assert sec.sound_chk.isHidden()
        sec._play()
        assert played == []  # 파일이 없으면 다른 알림음으로 대신하지 않는다
    finally:
        sec.shutdown()
    (tmp_path / "쿨타임 끝.mp3").write_bytes(b"x")
    monkeypatch.setattr(notifier, "sound_path", lambda name: tmp_path / name)
    sec = CooldownSection(_Watcher())
    try:
        assert not sec.sound_chk.isHidden()
        sec._play()
        assert played == [tmp_path / "쿨타임 끝.mp3"]
    finally:
        sec.shutdown()


def test_cells_ending_together_sound_once_even_across_observations():
    row = CooldownRow()
    row.update({"a": READY, "b": READY}, 0)
    row.update({"a": COOLING, "b": COOLING}, 1)
    assert row.update({"a": READY}, 10.0) is True
    assert row.update({"b": READY}, 10.22) is False  # 다음 관측(0.22초 뒤) — 같은 순간으로 보고 한 번만
    row.update({"b": COOLING}, 11)
    assert row.update({"b": READY}, 20.0) is True  # 따로 끝나면 다시 울림


def test_same_cell_does_not_repeat_during_highlight_flash():
    row = CooldownRow()
    row.update({"a": READY}, 0)
    row.update({"a": COOLING}, 1)
    assert row.update({"a": READY}, 10.0) is True
    row.update({"a": COOLING}, 10.3)  # 강조 중 번쩍임으로 숫자가 다시 보임
    assert row.update({"a": READY}, 10.6) is False  # 같은 칸, 강조 시간 안 → 반복 안 함
    assert row.update({"a": COOLING}, 12.0) is False
    assert row.update({"a": READY}, 30.0) is True  # 실제로 다시 쓴 뒤 끝나면 울림


# ---- 세트(사용자 결정 11-05, 최대 4) · 사용 가능 순간 커졌다 돌아오기 --------------------------------------------
def _set_slot(sid, x, set_no=None):
    slot = {"id": sid, "rect": [x, 0, 40, 40], "label": f"스킬 {sid}"}
    if set_no is not None:
        slot["set"] = set_no
    return slot


def test_old_settings_move_to_set_one():
    from mabinogi_addon import config
    config.save_cooldown({"slots": [_set_slot("a", 0), _set_slot("b", 50)], "pos": {"x": 300, "y": 400}})  # 세트 없던 예전 설정
    cfg = config.load_cooldown()
    assert [s["set"] for s in cfg["slots"]] == [1, 1]
    assert cfg["positions"][1] == {"x": 300, "y": 400} and cfg["positions"][2] is None


def test_set_positions_saved_and_restored_per_set(creator):
    from mabinogi_addon import config
    from mabinogi_addon.ui.cooldown_section import CooldownSection
    config.save_cooldown({"enabled": True, "locked": False, "slots": [_set_slot("a", 0, 1), _set_slot("b", 50, 2)]})
    sec = CooldownSection(_FrontWatcher(game=True, own=False))
    try:
        sec._show_row()
        o1, o2 = sec._overlays[1], sec._overlays[2]
        o1.move(100, 200)
        o1.moved.emit()
        o2.move(500, 600)
        o2.moved.emit()
    finally:
        sec.shutdown()
    cfg = config.load_cooldown()
    assert cfg["positions"][1] == {"x": 100, "y": 200} and cfg["positions"][2] == {"x": 500, "y": 600}
    again = CooldownSection(_FrontWatcher(game=True, own=False))
    try:
        again._show_row()
        assert again._overlays[1].pos().x() == 100 and again._overlays[2].pos().y() == 600  # 다시 켜도 세트마다 제자리
    finally:
        again.shutdown()


def test_empty_set_has_no_overlay_and_unlocked_shows_box_per_used_set(creator):
    from mabinogi_addon import config
    from mabinogi_addon.ui.cooldown_section import CooldownSection
    config.save_cooldown({"enabled": True, "locked": False, "slots": [_set_slot("a", 0, 1), _set_slot("b", 50, 3)]})
    sec = CooldownSection(_FrontWatcher(game=True, own=False))
    try:
        sec._show_row()
        assert {n for n, ov in sec._overlays.items() if ov.isVisible()} == {1, 3}  # 칸 없는 2·4세트는 안 띄움
        assert sec._overlays[3].set_no == 3
    finally:
        sec.shutdown()


def test_two_sets_show_their_own_cooling_cells_at_once(creator):
    from mabinogi_addon import config
    from mabinogi_addon.ui.cooldown_section import CooldownSection
    config.save_cooldown({"enabled": True, "locked": True,
                          "slots": [_set_slot("a", 0, 1), _set_slot("b", 50, 2), _set_slot("c", 100, 2)]})
    sec = CooldownSection(_FrontWatcher(game=True, own=False))
    try:
        sec.row.update({"a": COOLING, "b": COOLING, "c": COOLING}, time.monotonic())
        sec._show_row()
        assert sec._overlays[1].items() == [("a", False)]
        assert sec._overlays[2].items() == [("b", False), ("c", False)]
        assert sec._overlays[1].isVisible() and sec._overlays[2].isVisible()
    finally:
        sec.shutdown()


def _list_rows(sec):
    """목록 줄 → (이름, 툴팁). 빈 안내 줄은 뺀다."""
    from PySide6.QtWidgets import QLabel, QPushButton
    rows = []
    for i in range(sec.list_box.count()):
        line = sec.list_box.itemAt(i).widget()
        if line is None or not line.findChildren(QPushButton):
            continue
        labels = [lb for lb in line.findChildren(QLabel) if lb.text()]
        rows.append((labels[0].text(), line.toolTip()))
    return rows


def test_list_shows_only_chosen_set_with_icon_name_and_tooltip(creator):
    """#195: 고른 세트의 칸만, 줄 = 아이콘 + 이름 + 삭제, 위치 숫자는 툴팁."""
    from mabinogi_addon.ui.cooldown_section import CooldownSection
    sec = CooldownSection(_Watcher())
    try:
        sec.set_combo.setCurrentIndex(1)
        slot = sec.register(Target("skill", (0, 0, 40, 40), "단축바 칸", {}), None)
        assert slot["set"] == 2
        sec.set_combo.setCurrentIndex(0)
        sec.register(Target("skill", (50, 0, 40, 40), "단축바 칸", {}), None)
        assert [n for n, _t in _list_rows(sec)] == ["스킬 2"]  # 세트 1만
        sec.set_combo.setCurrentIndex(1)
        rows = _list_rows(sec)
        assert [n for n, _t in rows] == ["스킬 1"]  # 세트를 바꾸면 목록도
        assert "@ (0,0)" in rows[0][1] and "40×40" in rows[0][1]  # 위치는 툴팁
    finally:
        sec.shutdown()


def test_register_saves_icon_from_snapshot_and_ready_observation_resaves(creator):
    import numpy as np
    from mabinogi_addon import config
    from mabinogi_addon.ui import cooldown_section as cs
    frame, box, cells = _screen("스크린샷 2026-11-05 203318.png")
    sec = cs.CooldownSection(_Watcher())
    try:
        slot = sec.register(cells[(1, 0, 0, 1)], frame, (0, 0))  # 등록 순간 쿨 중('47')
        assert cs.icon_path(slot["id"]).exists() and slot["icon_ok"] is False
        ready = cells[(1, 0, 0, 0)]  # 같은 자리가 사용 가능해진 화면을 흉내 — 사용 가능 칸 그림을 그 자리에
        fake = frame.copy()
        x, y, w, h = slot["rect"]
        rx, ry, _, _ = ready.rect
        fake[y:y + h, x:x + w] = frame[ry:ry + h, rx:rx + w]
        out = cs.observe(fake, (0, 0), [dict(slot, page=None)], {}, False, frozenset({slot["id"]}))
        assert out["icons"] == [slot["id"]]
        from mabinogi_addon import image_io
        import cv2
        saved = image_io.imread(cs.icon_path(slot["id"]), cv2.IMREAD_COLOR)
        assert np.array_equal(saved, fake[y:y + h, x:x + w])  # '사용 가능' 그림으로 다시 저장
        sec._running = lambda: True
        sec._on_delivered("cooldown", {"changes": {}, "icons": [slot["id"]]})
        assert config.load_cooldown()["slots"][0]["icon_ok"] is True
        assert cs.observe(fake, (0, 0), [dict(slot, page=None)], {slot["id"]: "ready"}, False, frozenset()) is None  # 한 번만
        sec._remove(slot["id"])
        assert not cs.icon_path(slot["id"]).exists()
    finally:
        sec.shutdown()


def test_old_slot_without_icon_shows_empty_placeholder(creator):
    from mabinogi_addon import config
    from mabinogi_addon.ui import cooldown_section as cs
    config.save_cooldown({"slots": [_set_slot("old", 0)]})  # 예전 등록(아이콘 없음)
    assert config.load_cooldown()["slots"][0]["icon_ok"] is False
    assert not cs.icon_path("old").exists()
    pix = cs.CooldownSection._list_icon("old")
    assert (pix.width(), pix.height()) == (cs.LIST_ICON, cs.LIST_ICON)


def test_ready_cell_pops_in_its_own_set_and_timer_stops():
    from mabinogi_addon.ui.cooldown_overlay import POP_SCALE, POP_SECONDS, CooldownOverlay
    clock = [0.0]
    ov = CooldownOverlay(100, 2)
    ov._now = lambda: clock[0]
    try:
        ov.set_items([("a", True), ("b", False)])
        size_before = ov.size()
        ov.pop("a")
        assert ov._pop_timer.isActive() and ov.pop_factor("b") == 1.0
        clock[0] = POP_SECONDS / 2
        assert abs(ov.pop_factor("a") - POP_SCALE) < 1e-6  # 가운데에서 1.4배
        ov._pop_tick()
        assert ov.size() == size_before  # 커지는 동안 창 크기는 그대로(여백 미리 확보)
        grown = ov._grown(ov._rects()[0], ov.pop_factor("a"))
        assert grown.left() >= 0 and grown.top() >= 0 and grown.right() < ov.width()  # 창 안에서 커짐
        clock[0] = POP_SECONDS + 0.01
        ov._pop_tick()
        assert ov.pop_factor("a") == 1.0 and not ov._pop_timer.isActive()  # 끝나면 타이머 멈춤
    finally:
        ov.close()


def test_section_pops_newly_ready_cell_in_its_set(creator):
    from mabinogi_addon import config
    from mabinogi_addon.ui.cooldown_section import CooldownSection
    config.save_cooldown({"enabled": True, "locked": True, "slots": [_set_slot("a", 0, 1), _set_slot("b", 50, 2)]})
    sec = CooldownSection(_FrontWatcher(game=True, own=False))
    popped = []
    try:
        sec._on_delivered("cooldown", {"changes": {"a": READY, "b": READY}})  # 처음 관측(강조 없음)
        sec._on_delivered("cooldown", {"changes": {"a": COOLING, "b": COOLING}})
        for n, ov in sec._overlays.items():
            ov.pop = lambda sid, n=n: popped.append((n, sid))
        sec._on_delivered("cooldown", {"changes": {"b": READY}})
        assert popped == [(2, "b")]  # 자기 세트 오버레이에서만
    finally:
        sec.shutdown()



def test_sixteen_slots_survive_save_and_reload_and_reader_caps_per_set():
    from mabinogi_addon import config
    slots = [_set_slot(f"a{i}", i * 50, 1) for i in range(8)] + [_set_slot(f"b{i}", i * 50, 2) for i in range(8)]
    config.save_cooldown({"slots": slots})
    cfg = config.load_cooldown()
    assert len(cfg["slots"]) == 16 and [s["set"] for s in cfg["slots"]].count(2) == 8
    config.save_cooldown({"slots": slots + [_set_slot("a9", 999, 1)]})  # 손으로 고친 설정 등: 세트 1에 9칸
    cfg = config.load_cooldown()
    assert len(cfg["slots"]) == 16 and "a9" not in {s["id"] for s in cfg["slots"]}  # 세트당 8칸으로 읽음


def test_highlight_stays_three_seconds_and_reuse_cancels():
    """제작자 시험 #194: 강조 3초(커지기 0.4초 포함) — 사용 가능 뒤 2.9초까지 줄에 있고 3초 뒤 빠진다."""
    from mabinogi_addon.tracker.cooldown_row import HIGHLIGHT_SECONDS
    assert HIGHLIGHT_SECONDS == 3.0
    row = CooldownRow()
    row.update({"a": READY}, 0)
    row.update({"a": COOLING}, 1)
    row.update({"a": READY}, 10.0)
    assert row.expire(12.9) is False and row.row == ["a"] and "a" in row.until
    assert row.expire(13.0) is True and row.row == []
    row.update({"a": COOLING}, 20)
    row.update({"a": READY}, 30.0)
    row.update({"a": COOLING}, 31.0)  # 강조 중 다시 씀 → 바로 사용 중
    assert row.row == ["a"] and "a" not in row.until



# ---- 등록 시점과 무관하게(제작자 11-06: 쿨 중 등록한 F3이 오버레이에 안 나옴) ----------------------------------
def test_one_page_selector_per_row_middle_or_right_end():
    """한 줄에 선택기는 하나 — 배치에 따라 블록 사이(540) 또는 오른쪽 끝(1160)."""
    frame, box, _ = _screen("스크린샷 2026-11-06 013726.png")
    assert cd.page_rect(frame, box, 0)[0] == round(box[0] + 1160 + 34)
    frame2, box2, _ = _screen("image01.png")
    assert cd.page_rect(frame2, box2, 0)[0] == round(box2[0] + 540 + 34)


def test_page_saved_at_registration_is_never_overwritten(creator, monkeypatch):
    """QA 5c01ccf: 위 줄 '1'로 등록(쿨 중) → Shift로 '2' 상자가 보이는 사용 가능 프레임 관측 → 저장된 페이지는 '1' 그대로.
    (예전 recheck는 그 순간 '2'로 덮어써 평소엔 계속 숨겼다.) 다시 '1' 페이지에서 쓰면 오버레이에 나온다."""
    from mabinogi_addon import config, image_io
    from mabinogi_addon.ui import cooldown_section as cs
    from mabinogi_addon.ui import skillbar_capture
    cool, box, cells = _screen("스크린샷 2026-11-06 013726.png")
    target = cells[(1, 0, 0, 2)]  # 위 줄 F3 '31'(사용 중), 페이지 '1'
    sec = cs.CooldownSection(_FrontWatcher(game=True, own=False))
    try:
        slot = sec.register(target, cool, (0, 0))
        assert "사용 가능할 때" not in sec.status.text() and "recheck" not in slot
        one = slot["page"]
        px, py, pw, ph = slot["page_rect"]
        two = image_io.imread("tests/data/스크린샷 2026-10-16 211914.png", cv2.IMREAD_COLOR)
        shift_frame = cool.copy()
        shift_frame[py:py + ph, px:px + pw] = two[py:py + ph, px:px + pw]  # '2' 상자(Shift 누르는 동안)
        x, y, w, h = slot["rect"]
        rx, ry, _, _ = cells[(1, 0, 1, 0)].rect
        shift_frame[y:y + h, x:x + w] = cool[ry:ry + h, rx:rx + w]  # 그 칸은 사용 가능
        frames = {"img": shift_frame}
        monkeypatch.setattr(skillbar_capture.SkillbarCapture, "_grab",
                            lambda self, X, Y, W, H: frames["img"][Y:Y + H, X:X + W].copy())
        sec.enable.setChecked(True)
        sec._tick()
        assert config.load_cooldown()["slots"][0]["page"] == one  # 덮어쓰지 않음
        assert sec.state_text(slot["id"]) == "가려짐(페이지 다름)"
        frames["img"] = cool  # Shift를 떼면 '1' — 쿨 중
        sec._tick()
        assert sec.row.row == [slot["id"]] and sec._overlay.items() == [(slot["id"], False)]
    finally:
        sec.shutdown()


def test_persistent_page_mismatch_is_listed_not_silent(creator, caplog):
    import logging
    from mabinogi_addon import config
    from mabinogi_addon.ui import cooldown_section as cs
    config.save_cooldown({"slots": [_set_slot("a", 0, 1)]})
    sec = cs.CooldownSection(_Watcher())
    caplog.set_level(logging.INFO, logger="mabinogi_addon.ui.cooldown_section")
    try:
        sec._note_states({"a": cs.PAGE_DIFF})
        assert sec.state_text("a") == "가려짐(페이지 다름)"
        sec._page_since["a"] -= cs.PAGE_WARN_SECONDS  # 3초 넘게 계속 다름
        assert sec.state_text("a") == "가려짐(페이지 다름) — 다른 페이지라 숨김"
        sec._render_list()
        from PySide6.QtWidgets import QLabel
        texts = [lb.text() for lb in sec.findChildren(QLabel, "cooldownState")]
        assert "가려짐(페이지 다름) — 다른 페이지라 숨김" in texts
        sec._note_states({"a": cs.cd.COOLING})
        assert sec.state_text("a") == "사용 중"
        lines = [r.getMessage() for r in caplog.records if "쿨타임 칸 상태" in r.getMessage()]
        assert len(lines) == 2 and "가려짐(페이지 다름)" in lines[0] and "사용 중" in lines[1]  # 바뀔 때만 한 줄
    finally:
        sec.shutdown()



# ---- 페이지 상자 모서리(758a01e: 던전 등에서 '1' 페이지를 '다름'으로 오판) -----------------------------------
PAGE_BOX_ROW0 = (1196, 24, 15, 16)


def _shot(name):
    from mabinogi_addon import image_io
    return image_io.imread(f"tests/data/{name}", cv2.IMREAD_COLOR)


def test_page_box_corners_do_not_change_page():
    a, b = _shot("스크린샷 2026-11-05 203318.png"), _shot("스크린샷 2026-11-03 234812.png")  # '1' 상자 — 모서리 흰 픽셀 0개 / 4개
    sig_a, sig_b = cd.page_signature(a, PAGE_BOX_ROW0), cd.page_signature(b, PAGE_BOX_ROW0)
    assert cd.same_page(b, PAGE_BOX_ROW0, sig_a) is True
    assert cd.same_page(a, PAGE_BOX_ROW0, sig_b) is True


def test_old_signature_with_corners_still_matches():
    """예전에 저장한 서명(모서리 포함)도 다시 등록 없이 맞는다."""
    import numpy as np
    b = _shot("스크린샷 2026-11-03 234812.png")
    x, y, w, h = PAGE_BOX_ROW0
    gray = cv2.cvtColor(b[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)
    old = gray > 150  # 모서리를 지우기 전 방식 그대로
    assert old[0, 0] and old[-1, -1]
    old_sig = f"{w}x{h}:{np.packbits(old.astype(np.uint8).ravel()).tobytes().hex()}"
    assert cd.same_page(_shot("스크린샷 2026-11-05 203318.png"), PAGE_BOX_ROW0, old_sig) is True


def test_page_one_vs_two_still_different():
    one = cd.page_signature(_shot("스크린샷 2026-11-05 203318.png"), PAGE_BOX_ROW0)
    assert cd.same_page(_shot("스크린샷 2026-10-16 211914.png"), PAGE_BOX_ROW0, one) is False  # 같은 자리 '2'


# ---- 페이지 확인은 '지금 키를 쓰는 단축바' 칸에만(제작자 11-06) ---------------------------------------------
def _register_on(name, key):
    from mabinogi_addon.ui.cooldown_section import CooldownSection
    frame, box, cells = _screen(name)
    sec = CooldownSection(_Watcher())
    slot = sec.register(cells[key], frame, (0, 0))
    sec.shutdown()
    return slot


def test_key_block_from_selector_position():
    for name, expected in (("스크린샷 2026-11-06 013739.png", 1), ("스크린샷 2026-11-04 014744.png", 1),
                           ("mabinogi_2026_10_30_213520.png", 0)):  # 3840 배치(선택기 540) → 왼쪽이 키 블록
        frame, box, _ = _screen(name)
        assert cd.key_block(frame, cd.selector_rects(box, 0)) == expected, name


def test_register_saves_page_only_for_key_block_cells(creator):
    keyed = _register_on("스크린샷 2026-11-04 014744.png", (1, 0, 0, 2))  # 가운데(키 블록) 위 줄
    keyless = _register_on("스크린샷 2026-11-04 014744.png", (0, 0, 0, 2))  # 왼쪽(키 없음) 위 줄
    assert keyed["page"] and keyed["page_block"] == 1 and keyed["block"] == 1
    assert keyless["page"] is None and keyless["page_block"] is None and keyless["block"] == 0
    left = _register_on("mabinogi_2026_10_30_213520.png", (0, 1, 0, 0))  # 3840: 왼쪽이 키 블록
    assert left["page"] and left["page_block"] == 0


def test_page_change_hides_only_key_block_cells():
    """위 줄 014744('2') → 013739('1'), 아래 줄 013739 → 214902: 키 없는 블록 칸은 페이지가 달라도 숨기지 않고, 키 블록 칸만 숨김."""
    from mabinogi_addon.ui.cooldown_section import PAGE_DIFF, observe
    for (before, after), row in ((("스크린샷 2026-11-04 014744.png", "스크린샷 2026-11-06 013739.png"), 0),
                                 (("스크린샷 2026-11-06 013739.png", "스크린샷 2026-10-16 214902.png"), 1)):
        frame_b, box, cells = _screen(before)
        rects = cd.selector_rects(box, row)
        sig = cd.page_signature(frame_b, rects[1])
        base = {"page": sig, "page_block": 1, "page_rects": {str(k): list(v) for k, v in rects.items()}, "page_rect": list(rects[1])}
        keyed = dict(base, id="k", rect=list(cells[(1, row, 0, 1)].rect), block=1)
        keyless = dict(base, id="n", rect=list(cells[(0, row, 0, 1)].rect), block=0)
        frame_a, _, _ = _screen(after)
        out = observe(frame_a, (0, 0), [keyed, keyless], {}, False)
        assert out["changes"]["k"] == PAGE_DIFF, (before, after)
        assert out["changes"]["n"] != PAGE_DIFF, (before, after)


def test_no_page_compare_when_key_bar_switched():
    """page_block(등록 때 키 블록)과 지금 키 블록이 다르면 비교하지 않는다 — 엉뚱한 단축바 페이지와 비교 금지."""
    from mabinogi_addon.ui.cooldown_section import PAGE_DIFF, observe
    left_frame, left_box, left_cells = _screen("mabinogi_2026_10_30_213520.png")  # 키 블록 0
    rects = cd.selector_rects(left_box, 0)
    slot = {"id": "a", "rect": list(left_cells[(0, 0, 0, 1)].rect), "block": 0, "page_block": 0,
            "page": cd.page_signature(left_frame, rects[0]), "page_rects": {str(k): list(v) for k, v in rects.items()},
            "page_rect": list(rects[0])}
    other, _, _ = _screen("스크린샷 2026-11-06 013739.png")  # 같은 좌표에 키 블록 1(선택기 1160)
    out = observe(other, (0, 0), [slot], {}, False)
    assert out["changes"]["a"] != PAGE_DIFF
