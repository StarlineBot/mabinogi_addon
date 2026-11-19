"""요리창 자동 찾기(docs/cooking-spec.md 7절, 0.54.0) — 찾기·신호·추적·끈 동안 캡처 0·손으로 맞추기 대체."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mabinogi_addon import config
from mabinogi_addon.detect import cooking_window as cw
from mabinogi_addon.image_io import imread

DATA = Path(__file__).parent / "data"
# 요리 화면(사용자 원본 3장 + 회색 1920 2장) → 게이지 바(테두리 포함) 왼쪽 위, 눈·테두리 픽셀로 확인
COOKING = {
    "11image.png": (348, 850),
    "22image1.png": (1252, 1303),
    "mabinogi_2026_11_19_171429.png": (347, 1144),
    "mabinogi_2026_11_19_162740.webp": (957, 733),
    "mabinogi_2026_11_19_162700.webp": (956, 701),
}
# 요리 화면을 1024px로 줄인 사본(게임 해상도 아님 — UI 크기가 달라 찾지 않는 게 맞음)
SHRUNK = {"mabinogi_2026_11_19_171429.webp", "image (31).webp"}


@pytest.fixture(autouse=True)
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("name", sorted(COOKING))
def test_finds_bar_on_cooking_screens(name):
    frame = imread(DATA / name)
    match = cw.locate(frame)
    assert match is not None and match.score >= cw.MATCH_MIN
    x, y, w, h = match.bar
    ex, ey = COOKING[name]
    assert abs(x - ex) <= 3 and abs(y - ey) <= 3 and (w, h) == (245, 10)
    assert cw.signal(_band(frame))  # 요리창이 뜨면 아래 띠가 검다


def _band(frame):
    h, w = frame.shape[:2]
    x, y, bw, bh = cw.band_rect(w, h)
    return frame[y:y + bh, x:x + bw]


def _others():
    names = []
    for path in sorted(DATA.iterdir()):
        if path.suffix.lower() in (".png", ".webp", ".jpg") and path.name not in COOKING and path.name not in SHRUNK:
            names.append(path.name)
    return names


def test_no_false_positive_without_cooking_window():
    """요리창 없는 화면: 신호(아래 띠 검은 비율)도 기준 미만이고, 찾기도 0건(11-19 측정 최고 0.496 < 0.6)."""
    checked = 0
    for name in _others():
        frame = imread(DATA / name)
        if frame is None or frame.shape[0] < 200:
            continue
        checked += 1
        assert cw.black_ratio(_band(frame)) < cw.SIGNAL_RATIO, name
        assert cw.locate(frame) is None, name
    assert checked >= 100


def test_signal_threshold_boundary():
    band = np.full((40, 100), 200, np.uint8)
    band[:, :70] = 0          # 줄여 읽기(4칸 간격)로 정확히 0.7
    assert cw.black_ratio(band) == pytest.approx(0.72, abs=0.03) and cw.signal(band)
    band[:, :] = 200
    band[:, :64] = 7          # 밝기 7은 검정, 8부터 아님
    assert not cw.signal(band)
    band[:, :76] = 8
    assert cw.black_ratio(band) == 0.0


def _grabber(frame, calls=None):
    def grab(x, y, w, h):
        if calls is not None:
            calls.append((x, y, w, h))
        return frame[y:y + h, x:x + w]
    return grab


def test_tracking_nearby_then_moved_then_closed():
    base = imread(DATA / "11image.png")
    h, w = base.shape[:2]
    finder = cw.CookingFinder()
    calls = []
    state = finder.step(_grabber(base, calls), w, h)
    assert state.kind == "found" and state.bar[:2] == (348, 850) and finder.full_searches == 1
    state = finder.step(_grabber(base, calls), w, h)  # 같은 자리 → 둘레만(전체 다시 안 찾음)
    assert state.kind == "found" and finder.full_searches == 1
    near = calls[-1]
    assert near[2] < w and near[3] < h and near[2] <= 247 + 2 * 42 + 2

    # 요리창을 옮김: 같은 요리창 조각을 다른 자리에(나머지는 검정 — 신호는 그대로)
    moved = np.zeros_like(base)
    piece = base[700:1000, 200:700]
    moved[300:600, 1200:1700] = piece
    state = finder.step(_grabber(moved), w, h)
    assert state.kind == "found" and state.bar[:2] == (348 - 200 + 1200, 850 - 700 + 300)
    assert finder.full_searches == 2

    # 신호는 남았는데 요리창이 없음: 1번은 지난 자리 유지, 2번 연속이면 닫힘
    empty = np.zeros_like(base)
    assert finder.step(_grabber(empty), w, h).kind == "found"
    assert finder.step(_grabber(empty), w, h).kind == "closed"
    # 다시 뜨면 다시 찾음
    assert finder.step(_grabber(base), w, h).kind == "found"
    # 신호가 사라지면 바로 닫힘
    bright = np.full_like(base, 120)
    assert finder.step(_grabber(bright), w, h).kind == "closed"


def test_never_found_stays_manual():
    """한 번도 못 찾았으면(다른 인터페이스 등) 닫힘이 아니라 손으로 맞추기 — 0.53.0처럼 저장 자리에 표시."""
    finder = cw.CookingFinder()
    empty = np.zeros((1080, 1920, 3), np.uint8)
    assert finder.step(_grabber(empty), 1920, 1080).kind == "manual"
    assert finder.step(_grabber(empty), 1920, 1080).kind == "manual"
    assert finder.step(_grabber(np.full_like(empty, 120)), 1920, 1080).kind == "manual"


# ---- 탭 연결 ----
class _Fg:
    def __init__(self):
        self.front = "game"

    def is_game_active(self):
        return self.front == "game"

    def is_self_active(self):
        return self.front == "self"


class _Done:
    def __init__(self, value):
        self._value = value

    def done(self):
        return True

    def result(self):
        return self._value


def _tab(monkeypatch, frame=None, origin=(100, 50)):
    from mabinogi_addon.ui import dpi
    from mabinogi_addon.ui.cooking_tab import CookingTab
    monkeypatch.setattr(dpi, "screen_scale", lambda: 1.0)
    fg = _Fg()
    tab = CookingTab(fg)
    calls = []

    def target():
        calls.append("target")
        if frame is None:
            return None
        return (*origin, frame.shape[1], frame.shape[0])
    tab.autofind._target = target
    tab.autofind._grab = lambda left, top: _grabber(tab._frame)
    tab.autofind.submit = lambda fn: _Done(fn())  # 작업 스레드 대신 바로
    tab._frame = frame
    return tab, fg, calls


def test_no_capture_while_off_or_game_not_front(monkeypatch):
    tab, fg, calls = _tab(monkeypatch, imread(DATA / "11image.png"))
    tab.select("모둠회덮밥")
    for _ in range(3):
        tab._auto_tick()          # 바를 안 켰음
    assert calls == [] and not tab._find_timer.isActive()
    tab.set_overlay(True)
    assert tab._find_timer.isActive()
    fg.front = "other"
    tab._auto_tick()              # 게임이 앞이 아님
    assert calls == []
    tab.set_overlay(False)
    assert not tab._find_timer.isActive()
    tab.shutdown()


def test_tab_places_bar_on_found_spot_and_hides_when_closed(monkeypatch):
    frame = imread(DATA / "11image.png")
    config.save_cooking_overlay(pos={"x": 10, "y": 20}, scale=1.3, locked=False)
    tab, _fg, _calls = _tab(monkeypatch, frame, origin=(100, 50))
    tab.select("모둠회덮밥")
    tab.set_overlay(True)
    o = tab.overlay
    assert tab.auto_state == "manual" and (o.x(), o.y()) == (10, 20) and o.scale == 1.3
    tab._auto_tick()   # 찾기 작업 걸기
    tab._auto_tick()   # 결과 반영
    assert tab.auto_state == "found"
    bw, bh = o.bar_size()
    assert (o.x(), o.y() + o.height() - bh) == (100 + 348, 50 + 850)  # 바가 요리창 바 자리에 정확히
    assert (bw, bh) == (245, 10) and o.locked and o.isVisible()
    o.moved.emit()     # 찾은 자리는 저장 위치를 덮지 않음
    assert config.load_cooking_overlay()["pos"] == {"x": 10, "y": 20}
    # 요리창이 꺼짐(신호 사라짐) → 숨김
    tab._frame = np.full_like(frame, 120)
    tab._auto_tick()
    tab._auto_tick()
    assert tab.auto_state == "closed" and not o.isVisible()
    # 다시 뜨면 다시 찾아 띄움
    tab._frame = frame
    tab._auto_tick()
    tab._auto_tick()
    assert tab.auto_state == "found" and o.isVisible()
    # 바를 끄면 손으로 맞춘 자리·배율·잠금으로 돌아가 있음
    tab.set_overlay(False)
    assert tab.auto_state == "manual" and (o.x(), o.y()) == (10, 20) and o.scale == 1.3 and not o.locked
    tab.shutdown()


def test_manual_fallback_when_not_found(monkeypatch):
    """요리창을 못 찾는 화면이면 0.53.0처럼 저장 자리에 보이고 끌기·잠금 그대로."""
    config.save_cooking_overlay(pos={"x": 30, "y": 40}, scale=1.0, locked=False)
    tab, _fg, _calls = _tab(monkeypatch, np.zeros((1080, 1920, 3), np.uint8))
    tab.select("모둠회덮밥")
    tab.set_overlay(True)
    for _ in range(4):
        tab._auto_tick()
    o = tab.overlay
    assert tab.auto_state == "manual" and o.isVisible() and (o.x(), o.y()) == (30, 40) and not o.locked
    o.move(33, 44)
    o.moved.emit()
    assert config.load_cooking_overlay()["pos"] == {"x": 33, "y": 44}
    tab.shutdown()


def test_job_runs_on_worker_thread_one_at_a_time():
    import threading
    import time

    from mabinogi_addon.ui.cooking_autofind import CookingAutoFind
    frame = imread(DATA / "11image.png")
    threads = []
    auto = CookingAutoFind(target=lambda: (0, 0, frame.shape[1], frame.shape[0]))

    def grab(left, top):
        threads.append(threading.current_thread().name)
        return _grabber(frame)
    auto._grab = grab
    assert auto.tick(True) is None            # 작업 걸기
    first = auto._future
    auto.tick(True)
    assert auto._future is first or first.done()  # 도는 중이면 새로 걸지 않음
    deadline = time.monotonic() + 10
    state = None
    while state is None and time.monotonic() < deadline:
        time.sleep(0.05)
        state = auto.tick(False)
    assert state is not None and state.kind == "found"
    assert threads and all(name.startswith("cooking-find") for name in threads)
    auto.shutdown()
