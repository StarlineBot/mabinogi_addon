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
    # 11-20 밝은 반투명 스킨(사용자 실측 0.47~0.52로 못 붙던 화면) — 174704는 기준 그림 출처, 174447은 다른 배경으로 검증
    "스크린샷 2026-11-20 174704.png": (347, 844),
    "스크린샷 2026-11-20 174447.png": (1242, 862),
}
# 신호는 켜지지만(아래 띠 검음) 요리창이 아닌 화면 — 찾기로 걸러 숨김(사용자 결정 11-22)
SIGNAL_NOT_COOKING = {"스크린샷 2026-11-22 192845.png"}  # 핀즈 크래프트 창, 위아래 검은 띠
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
    assert abs(x - ex) <= 2 and abs(y - ey) <= 2 and (w, h) == (245, 10)
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
    """요리창 없는 화면: 신호(아래 띠 검은 비율)도 기준 미만이고, 찾기도 0건(11-20 두 그림 평균 최고 0.371 < 0.47)."""
    checked = 0
    for name in _others():
        frame = imread(DATA / name)
        if frame is None or frame.shape[0] < 200:
            continue
        checked += 1
        if name not in SIGNAL_NOT_COOKING:
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

    # 신호는 남았는데 못 알아봄: 1번은 지난 자리 유지, 2번 연속이면 숨김(사용자 결정 11-22 — 11-20 '손으로' 폐기)
    empty = np.zeros_like(base)
    assert finder.step(_grabber(empty), w, h).kind == "found"
    state = finder.step(_grabber(empty), w, h)
    assert state.kind == "closed" and state.bar is None and finder.bar is None
    assert finder.step(_grabber(empty), w, h).kind == "closed"
    # 다시 뜨면 다시 찾음
    assert finder.step(_grabber(base), w, h).kind == "found"
    # 신호가 사라지면 바로 닫힘
    bright = np.full_like(base, 120)
    assert finder.step(_grabber(bright), w, h).kind == "closed"


def test_never_found_hides_unless_recognized():
    """신호 있음 + 못 알아봄 2회 → 숨김(사용자 결정 11-22), 신호 없음 → 숨김(사용자 보고 11-20). 첫 찾기 전만 손으로."""
    finder = cw.CookingFinder()
    assert finder.state.kind == "manual"   # 첫 찾기 전(애드온 요리 탭에서 막 켠 바는 보임)
    empty = np.zeros((1080, 1920, 3), np.uint8)
    assert finder.step(_grabber(empty), 1920, 1080).kind == "manual"   # 1회 못 찾음은 지난 상태 유지
    assert finder.step(_grabber(empty), 1920, 1080).kind == "closed"
    assert finder.step(_grabber(np.full_like(empty, 120)), 1920, 1080).kind == "closed"
    assert finder.step(lambda *a: None, 1920, 1080).kind == "closed"   # 띠 캡처 실패도 신호 없음


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

    def registered():
        calls.append("target")
        if tab._frame is None:
            return None
        return (*origin, tab._frame.shape[1], tab._frame.shape[0])
    tab.autofind._registered = registered
    tab.autofind._open_camera = lambda: _Camera(lambda: _screen(tab._frame, origin))
    tab.autofind.submit = lambda fn: _Done(fn())  # 작업 스레드 대신 바로
    tab._frame = frame
    return tab, fg, calls


def _screen(frame, origin):
    """주 모니터 전체 프레임 흉내 — 게임 창 화면을 origin 자리에."""
    if frame is None:
        return None
    ox, oy = origin
    screen = np.full((frame.shape[0] + oy + 20, frame.shape[1] + ox + 20, 3), 90, np.uint8)
    screen[oy:oy + frame.shape[0], ox:ox + frame.shape[1]] = frame
    return screen


class _Camera:
    def __init__(self, frame_fn):
        self._frame_fn = frame_fn
        self.released = 0

    def full_frame(self):
        return self._frame_fn()

    def release(self):
        self.released += 1


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


def test_manual_spot_before_first_find_then_hidden_when_not_recognized(monkeypatch):
    """바를 막 켰을 때(첫 찾기 전)는 저장 자리에 보이고 끌기 그대로, 요리창을 못 알아보면 숨김(사용자 결정 11-22)."""
    config.save_cooking_overlay(pos={"x": 30, "y": 40}, scale=1.0, locked=False)
    tab, _fg, _calls = _tab(monkeypatch, np.zeros((1080, 1920, 3), np.uint8))
    tab.select("모둠회덮밥")
    tab.set_overlay(True)
    o = tab.overlay
    assert tab.auto_state == "manual" and o.isVisible() and (o.x(), o.y()) == (30, 40) and not o.locked
    o.move(33, 44)
    o.moved.emit()
    assert config.load_cooking_overlay()["pos"] == {"x": 33, "y": 44}
    for _ in range(4):
        tab._auto_tick()
    assert tab.auto_state == "closed" and not o.isVisible()
    tab.shutdown()


def test_job_runs_on_worker_thread_one_at_a_time():
    import threading
    import time

    from mabinogi_addon.ui.cooking_autofind import CookingAutoFind
    frame = imread(DATA / "11image.png")
    threads = []
    def full_frame():
        threads.append(threading.current_thread().name)
        return frame
    auto = CookingAutoFind(registered=lambda: (0, 0, frame.shape[1], frame.shape[0]),
                           camera=lambda: _Camera(full_frame))
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


# ---- QA 반려 11-19: 실기에서 한 번도 못 찾음 → 원인 줄이기 + 진단 로그 ----
def test_template_loads_from_non_ascii_path(tmp_path, monkeypatch):
    """Windows cv2.imread는 한글 경로를 못 읽는다 — 사용자 폴더 아래 exe 풀림 자리에서도 템플릿을 읽어야 함."""
    import shutil

    from mabinogi_addon import paths
    root = tmp_path / "사용자" / "templates"
    (root / "cooking").mkdir(parents=True)
    for name in cw.TEMPLATE_FILES:
        shutil.copy(paths.detect_templates_dir() / "cooking" / name, root / "cooking" / name)
    monkeypatch.setattr(paths, "detect_templates_dir", lambda: root)
    cw.templates.cache_clear()
    try:
        assert [t.shape for t in cw.templates()] == [(42, 247), (42, 247)]
        source = Path(cw.__file__).read_text(encoding="utf-8")
        assert "cv2.imread(" not in source  # 경로 인코딩과 무관한 image_io.imread만
    finally:
        cw.templates.cache_clear()


def test_unregistered_uses_primary_monitor_from_live_frame():
    from mabinogi_addon.ui.cooking_autofind import CookingAutoFind
    frame = imread(DATA / "11image.png")
    auto = CookingAutoFind(registered=lambda: None, camera=lambda: _Camera(lambda: frame))
    state, origin, where = auto._job()
    assert state.kind == "found" and state.bar[:2] == (348, 850) and origin == (0, 0)
    assert "주 모니터" in where and "라이브" in where


def test_registered_window_cropped_from_live_frame():
    from mabinogi_addon.ui.cooking_autofind import CookingAutoFind
    game = imread(DATA / "11image.png")
    screen = _screen(game, (100, 50))
    auto = CookingAutoFind(registered=lambda: (100, 50, game.shape[1], game.shape[0]),
                           camera=lambda: _Camera(lambda: screen))
    state, origin, where = auto._job()
    assert state.kind == "found" and state.bar[:2] == (348, 850) and origin == (100, 50)
    assert "등록 게임 창" in where and "라이브" in where


def test_window_outside_live_frame_falls_back_to_mss():
    from mabinogi_addon.ui.cooking_autofind import CookingAutoFind
    game = imread(DATA / "11image.png")
    auto = CookingAutoFind(registered=lambda: (3000, 0, game.shape[1], game.shape[0]),
                           camera=lambda: _Camera(lambda: np.zeros((1080, 1920, 3), np.uint8)))
    auto._mss_grab = lambda left, top: _grabber(game)  # 두 번째 모니터의 게임 창을 mss로
    state, origin, where = auto._job()
    assert state.kind == "found" and origin == (3000, 0) and "mss" in where


def test_logs_by_signal_every_step_while_on(caplog):
    """QA 반려 11-19: 신호가 켜져 있는 동안은 매 step 한 줄(못 찾아 manual이 이어져도), 꺼져 있으면 30초에 한 줄."""
    import logging

    from mabinogi_addon.ui.cooking_autofind import CookingAutoFind
    frame = imread(DATA / "11image.png")
    current = {"frame": frame}
    auto = CookingAutoFind(registered=lambda: None, camera=lambda: _Camera(lambda: current["frame"]))
    auto.submit = lambda fn: _Done(fn())

    def lines():
        return [r.getMessage() for r in caplog.records if r.getMessage().startswith("요리창 찾기:")]
    with caplog.at_level(logging.INFO, logger="mabinogi_addon.cooking"):
        auto.tick(True)
        assert auto.tick(True).kind == "found"
    line = lines()[0]
    assert "신호 바뀜" in line and "상태=found" in line and "대상=주 모니터" in line
    assert "띠검은비율=1.00" in line and "신호=켜짐" in line and "전체찾기=예" in line
    assert "최고점수=0.699" in line and "자리=348,850" in line and "못찾음=0" in line
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="mabinogi_addon.cooking"):
        auto.tick(True)                      # 신호 켜짐 → 상태가 같아도 매번
    assert len(lines()) == 1 and "전체찾기=아니오" in lines()[0] and "신호 바뀜" not in lines()[0]

    # 신호는 켜졌는데 요리창 모양이 없음(실사용 실패 재현) → 매 step 줄 + 실패 프레임
    caplog.clear()
    current["frame"] = np.zeros_like(frame)
    with caplog.at_level(logging.INFO, logger="mabinogi_addon.cooking"):
        for _ in range(4):
            auto.tick(True)
    got = lines()
    assert len(got) == 4 and all("신호=켜짐" in x for x in got)
    assert "못찾음=1" in got[0] and "상태=found" in got[0] and "상태=closed" in got[1]

    # 신호 꺼짐: 바뀔 때 한 줄, 그 뒤 30초 안엔 없음
    caplog.clear()
    current["frame"] = np.full_like(frame, 120)
    with caplog.at_level(logging.INFO, logger="mabinogi_addon.cooking"):
        for _ in range(3):
            auto.tick(True)
    got = lines()
    assert len(got) == 1 and "신호 바뀜" in got[0] and "신호=꺼짐" in got[0] and "최고점수=-" in got[0]


def test_failure_frames_saved_up_to_limit(caplog):
    """신호 켜짐 + 못 찾음 프레임은 실행당 3장, 신호 꺼짐 프레임은 30초 간격 2장까지 logs/cooking-find에."""
    import logging

    from mabinogi_addon.ui import cooking_autofind as ca
    frame = np.zeros((1080, 1920, 3), np.uint8)     # 아래 띠 검음 → 신호 켜짐, 요리창 모양 없음
    current = {"frame": frame}
    auto = ca.CookingAutoFind(registered=lambda: None, camera=lambda: _Camera(lambda: current["frame"]))
    auto.submit = lambda fn: _Done(fn())
    with caplog.at_level(logging.INFO, logger="mabinogi_addon.cooking"):
        for _ in range(8):
            auto.tick(True)
    misses = sorted(ca.shot_dir().glob("*_miss*.png"))
    assert 1 <= len(misses) <= ca.MAX_MISS_SHOTS
    assert any(f"저장={misses[0].name}" in r.getMessage() for r in caplog.records)
    current["frame"] = np.full_like(frame, 120)       # 신호 꺼짐
    clock = {"t": 1000.0}
    ca.time.monotonic, real = (lambda: clock["t"]), ca.time.monotonic
    try:
        for _ in range(5):
            clock["t"] += 31
            auto.tick(True)
            auto.tick(True)
    finally:
        ca.time.monotonic = real
    offs = sorted(ca.shot_dir().glob("*_off*.png"))
    assert len(offs) == ca.MAX_OFF_SHOTS == 2


def test_no_target_and_exception_logged(caplog):
    import logging

    from mabinogi_addon.ui.cooking_autofind import CookingAutoFind

    def broken_camera():
        raise RuntimeError("dxcam 없음")

    def broken_registered():
        raise OSError("창 조회 실패")
    auto = CookingAutoFind(registered=broken_registered, camera=broken_camera)
    auto._thread_mss = lambda: (_ for _ in ()).throw(RuntimeError("mss 없음"))
    auto.submit = lambda fn: _Done(fn())
    with caplog.at_level(logging.INFO, logger="mabinogi_addon.cooking"):
        assert auto.tick(True) is None
        assert auto.tick(True) is None
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "게임 창 조회 실패" in text and "라이브 카메라를 못 써서" in text and "모니터 조회 실패" in text
    assert "상태=대상 없음" in text
    assert text.count("상태=대상 없음") == 1  # 같은 실패를 매 초 반복해 찍지 않음

    class Boom:
        def done(self):
            return True

        def result(self):
            raise ValueError("작업 예외")
    auto.submit = lambda fn: Boom()
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="mabinogi_addon.cooking"):
        auto.tick(True)
        auto.tick(True)
    assert any("요리창 찾기 실패(예외)" in r.getMessage() for r in caplog.records)


def test_capture_none_counts_failures():
    finder = cw.CookingFinder()
    state = finder.step(lambda *a: None, 1920, 1080)
    assert state.kind == "closed" and finder.capture_failures == 1 and finder.last_ratio is None


def test_overlay_off_releases_camera(monkeypatch):
    tab, _fg, _calls = _tab(monkeypatch, imread(DATA / "11image.png"))
    tab.select("모둠회덮밥")
    tab.set_overlay(True)
    tab._auto_tick()
    camera = tab.autofind._camera
    assert camera is not None
    tab.autofind._executor = None
    released = []
    tab.autofind.submit = lambda fn: (fn(), released.append(True), _Done(None))[-1]
    tab.set_overlay(False)
    assert camera.released == 1 and tab.autofind._camera is None
    tab.shutdown()


def test_full_search_time_2560():
    """성능 기록(11-20): 두 그림 평균 전체 찾기 1회 — 2560×1440 약 0.2초(작업 스레드, 신호 켜졌을 때만). 느린 CI 여유 2초."""
    import time
    frame = imread(DATA / "스크린샷 2026-11-20 174704.png")
    cw.best(frame)  # 템플릿 읽기 제외
    started = time.perf_counter()
    cw.best(frame)
    assert time.perf_counter() - started < 2.0


def test_tab_not_recognized_hides_and_off_restores_manual_spot(monkeypatch):
    """사용자 결정 11-22: 찾은 뒤 신호는 있는데 2회 못 알아보면 숨김(11-20 '손으로' 폐기). 바를 껐다 켜면 손으로 맞춘 자리로."""
    frame = imread(DATA / "11image.png")
    config.save_cooking_overlay(pos={"x": 10, "y": 20}, scale=1.0, locked=False)
    tab, _fg, _calls = _tab(monkeypatch, frame, origin=(100, 50))
    tab.select("모둠회덮밥")
    tab.set_overlay(True)
    o = tab.overlay
    tab._auto_tick()
    tab._auto_tick()
    assert tab.auto_state == "found" and o.locked          # 찾은 자리는 클릭 통과
    tab._frame = np.zeros_like(frame)                     # 신호 켜짐, 요리창 모양 없음
    for _ in range(3):
        tab._auto_tick()
    assert tab.auto_state == "closed" and not o.isVisible()
    tab.set_overlay(False)
    tab.set_overlay(True)                                 # 다시 켜면 첫 찾기 전 = 손으로 맞춘 자리
    assert tab.auto_state == "manual" and o.isVisible() and (o.x(), o.y()) == (10, 20) and not o.locked
    tab._frame = frame                                    # 다시 알아보면 그 자리로
    tab._auto_tick()
    tab._auto_tick()
    assert tab.auto_state == "found" and o.locked
    tab.shutdown()


def test_tab_hides_bar_without_cooking_window_even_if_never_found(monkeypatch):
    """사용자 보고 11-20·결정 11-22: 신호 없으면 숨김, 신호 있는데 못 알아봐도 숨김, 찾으면 그 자리."""
    config.save_cooking_overlay(pos={"x": 10, "y": 20}, scale=1.0, locked=False)
    frame = imread(DATA / "11image.png")
    tab, _fg, _calls = _tab(monkeypatch, np.full_like(frame, 120), origin=(100, 50))
    tab.select("모둠회덮밥")
    tab.set_overlay(True)
    o = tab.overlay
    assert tab.auto_state == "manual" and o.isVisible()   # 첫 찾기 전
    tab._auto_tick()
    tab._auto_tick()
    assert tab.auto_state == "closed" and not o.isVisible()
    tab._frame = np.zeros_like(frame)                     # 신호 있음, 못 알아봄
    for _ in range(3):
        tab._auto_tick()
    assert tab.auto_state == "closed" and not o.isVisible()
    tab._frame = frame
    tab._auto_tick()
    tab._auto_tick()
    assert tab.auto_state == "found" and o.isVisible()
    tab.shutdown()


def test_pinz_craft_window_with_black_bands_hides_bar(monkeypatch):
    """사용자 보고 11-22: 핀즈 크래프트 창(위아래 검은 띠)은 신호가 켜지지만 요리창이 아님 → 2회 못 알아봄 → 숨김."""
    frame = imread(DATA / "스크린샷 2026-11-22 192845.png")
    h, w = frame.shape[:2]
    assert cw.signal(_band(frame)) and cw.locate(frame) is None
    finder = cw.CookingFinder()
    finder.step(_grabber(frame), w, h)
    assert finder.step(_grabber(frame), w, h).kind == "closed"
    config.save_cooking_overlay(pos={"x": 10, "y": 20}, scale=1.0, locked=False)
    tab, _fg, _calls = _tab(monkeypatch, frame)
    tab.select("모둠회덮밥")
    tab.set_overlay(True)
    for _ in range(4):
        tab._auto_tick()
    assert tab.auto_state == "closed" and not tab.overlay.isVisible()
    tab.shutdown()
