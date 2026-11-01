"""마우스 커서 표시(마우스 커서 명세 6절) — 꼬리 점·흔들기 판정·설정·오버레이 표시 조건·홈/탭 동기화."""

from __future__ import annotations

import os

import pytest

from mabinogi_addon import config
from mabinogi_addon.cursor_fx import (
    TailPoint, smooth, sparkle_multicolor,
    DEFAULTS, SHAKE_SCALE, SHAKE_SECONDS, TAIL_SECONDS, ShakeDetector, Trail, bounds, clean_settings, shake_scale,
)

# --- 순수 계산 ---


def test_defaults_match_spec():
    # 0.36.0 QA: colorChosen(색을 직접 고른 적 있는지, 기본 False — 반짝이 여러 색 규칙) 추가
    # 0.36.1 명세 변경(QA·사용자 실측 렉): 흔들어 찾기 기본 꺼짐
    assert DEFAULTS == {"enabled": False, "shape": "ring", "tail": "none", "shake": False, "color": "#FFD43B",
                        "size": 40, "tailLength": "normal", "opacity": 100, "colorChosen": False}
    assert clean_settings(None) == DEFAULTS


def test_clean_settings_bounds_and_unknowns():
    s = clean_settings({"shape": "star", "tail": "dots", "size": 500, "opacity": 3, "color": "#12abZZ",
                        "tailLength": "long", "enabled": 1, "shake": False})
    assert s["shape"] == "ring" and s["tail"] == "dots" and s["size"] == 120 and s["opacity"] == 20
    assert s["color"] == DEFAULTS["color"] and s["tailLength"] == "long"
    assert s["enabled"] is False  # 불리언만 받는다
    assert s["shake"] is False
    assert clean_settings({"opacity": 74})["opacity"] == 70  # 10%씩
    assert clean_settings({"color": "#a78bfa"})["color"] == "#A78BFA"


@pytest.mark.parametrize("length", list(TAIL_SECONDS))
def test_trail_keeps_only_tail_length(length):
    seconds = TAIL_SECONDS[length]
    trail = Trail()
    for i in range(60):  # 1초 동안 초당 60번 움직임
        trail.add(i / 60, i * 5, 0)
    now = 59 / 60
    pts = trail.points(now, seconds)
    assert pts and all(0 <= p.age <= 1 for p in pts)
    assert pts[0].age >= pts[-1].age and pts[-1].age == 0  # 오래된 것부터
    oldest = now - pts[0].age * seconds
    assert now - oldest <= seconds + 1e-9 and len(pts) == pytest.approx(seconds * 60, abs=2)


def test_trail_stops_redrawing_when_cursor_stops():
    trail = Trail()
    for i in range(10):
        trail.add(i / 60, i * 10, 0)
    assert not trail.add(10 / 60, 90, 0.4)  # 같은 자리(1px 미만)는 점을 늘리지 않음
    stop = 9 / 60
    assert trail.active(stop + 0.1, 0.3)
    assert not trail.active(stop + 0.31, 0.3)  # 멈춘 뒤 꼬리 길이가 지나면 그릴 것 없음
    assert trail.points(stop + 0.31, 0.3) == []


def test_bounds_cover_points_with_pad_only():
    trail = Trail()
    trail.add(0, 100, 200)
    trail.add(0.01, 160, 230)
    box = bounds(trail.points(0.01, 0.3), 10)
    assert box == (90, 190, 80, 50)
    assert bounds([], 10) is None


def _feed(det, xs, dt):
    hits = []
    for i, x in enumerate(xs):
        hits.append(det.add(i * dt, x))
    return hits


def test_shake_detected_for_fast_zigzag():
    xs = [500 + (120 if (i // 4) % 2 else -120) * ((i % 4) / 3) for i in range(30)]
    assert any(_feed(ShakeDetector(), xs, 1 / 60))


def test_straight_or_slow_motion_is_not_shake():
    assert not any(_feed(ShakeDetector(), [i * 20 for i in range(60)], 1 / 60))  # 직선
    zig = [500 + (120 if (i // 4) % 2 else -120) * ((i % 4) / 3) for i in range(30)]
    assert not any(_feed(ShakeDetector(), zig, 0.25))  # 같은 모양이라도 느리면(7초) 아님
    small = [500 + (3 if i % 2 else -3) for i in range(60)]
    assert not any(_feed(ShakeDetector(), small, 1 / 60))  # 작은 떨림


def test_shake_cooldown_and_scale():
    det = ShakeDetector()
    xs = [500 + (120 if (i // 4) % 2 else -120) * ((i % 4) / 3) for i in range(80)]
    hits = [i for i, hit in enumerate(_feed(det, xs, 1 / 60)) if hit]
    assert hits and all(b - a >= SHAKE_SECONDS * 60 - 1 for a, b in zip(hits, hits[1:]))
    assert shake_scale(-0.1) == 1 and shake_scale(SHAKE_SECONDS) == 1
    assert shake_scale(SHAKE_SECONDS / 2) == pytest.approx(SHAKE_SCALE)


# --- 오버레이 ---


class _Watcher:
    def __init__(self):
        self.active = True

    def is_game_active(self):
        return self.active


@pytest.fixture
def fx(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from mabinogi_addon.ui.cursor_overlay import CursorFx

    clock = [100.0]
    pos = [(400, 300)]
    watcher = _Watcher()
    f = CursorFx(watcher, pos_source=lambda: pos[0], clock=lambda: clock[0])
    yield f, clock, pos, watcher
    f.shutdown()


def _run(f, clock, seconds, step=1 / 60, move=None):
    for _ in range(int(seconds / step)):
        clock[0] += step
        if move:
            move()
        f.tick()


def test_settings_saved_and_restored(fx):
    f, *_ = fx
    f.update_settings(enabled=True, shape="scope", tail="sparkle", color="#1dd3b0", size=60, opacity=50)
    saved = clean_settings(config.load_cursor_fx())
    assert saved["shape"] == "scope" and saved["tail"] == "sparkle" and saved["color"] == "#1DD3B0"
    from mabinogi_addon.ui.cursor_overlay import CursorFx
    again = CursorFx(_Watcher())
    try:
        assert again.settings == saved
    finally:
        again.shutdown()


def test_off_by_default_and_no_timer(fx):
    f, clock, pos, watcher = fx
    assert not f.is_enabled() and not f._timer.isActive()
    _run(f, clock, 0.5)
    assert not any(w.isVisible() for w in f.windows())


def test_ring_follows_cursor_and_hides_when_game_behind_or_paused(fx):
    f, clock, pos, watcher = fx
    f.update_settings(enabled=True)
    assert f._timer.isActive()
    _run(f, clock, 0.3)
    ring = f._ring
    assert ring.isVisible() and ring.geometry().center().x() in (399, 400)
    pos[0] = (800, 500)
    _run(f, clock, 0.05)
    assert abs(ring.geometry().center().x() - 800) <= 1
    from PySide6.QtCore import Qt
    assert ring.windowFlags() & Qt.WindowType.WindowTransparentForInput  # 클릭 통과
    watcher.active = False
    _run(f, clock, 0.3)
    assert not any(w.isVisible() for w in f.windows())
    watcher.active = True
    _run(f, clock, 0.3)
    assert ring.isVisible()
    f.set_paused(True)
    assert not any(w.isVisible() for w in f.windows()) and not f._timer.isActive()
    f.set_paused(False)
    _run(f, clock, 0.3)
    assert ring.isVisible()


def test_stopped_cursor_does_not_move_or_redraw(fx, monkeypatch):
    f, clock, pos, watcher = fx
    f.update_settings(enabled=True, tail="line")
    step = [0]

    def move():
        step[0] += 1
        pos[0] = (400 + step[0] * 8, 300)
    _run(f, clock, 0.3, move=move)
    assert f._tail.isVisible()
    tail_box = f._tail.geometry()
    screen = f._tail.screen().geometry()
    assert tail_box.width() < screen.width()  # 화면 전체 창 아님(꼬리 범위만)
    calls = []
    for w in f.windows():
        monkeypatch.setattr(w, "setGeometry", lambda *a, w=w: calls.append(w))
        monkeypatch.setattr(w, "update", lambda *a, w=w: calls.append(w))
    _run(f, clock, TAIL_SECONDS["normal"] + 0.05)  # 멈춤: 꼬리가 사라질 때까지는 다시 그림
    assert not f._tail.isVisible()
    calls.clear()
    _run(f, clock, 1.0)  # 그 뒤로는 아무 창도 옮기거나 다시 그리지 않는다
    assert calls == []


def test_screen_lines_are_one_pixel_windows(fx):
    f, clock, pos, watcher = fx
    f.update_settings(enabled=True, shape="lines")
    _run(f, clock, 0.3)
    h, v = f._hline.geometry(), f._vline.geometry()
    assert f._hline.isVisible() and f._vline.isVisible() and not f._ring.isVisible()
    assert h.height() == 1 and v.width() == 1 and h.y() == 300 and v.x() == 400
    assert h.width() > 1 and v.height() > 1


def test_shake_shows_ring_even_with_shape_none(fx):
    f, clock, pos, watcher = fx
    f.update_settings(enabled=True, shape="none", shake=True)  # 0.36.1: 기본 꺼짐 → 켜고 확인
    i = [0]

    def zig():
        i[0] += 1
        pos[0] = (int(500 + (120 if (i[0] // 4) % 2 else -120) * ((i[0] % 4) / 3)), 300)
    _run(f, clock, 0.3)
    assert not f._ring.isVisible()
    _run(f, clock, 0.4, move=zig)
    assert f._ring.isVisible() and f._ring.width() > f.settings["size"] + 8
    _run(f, clock, SHAKE_SECONDS + 0.3)
    assert not f._ring.isVisible()


# --- 탭·홈 ---


from test_navigation import window  # noqa: E402,F401  (창 픽스처)


def test_creator_only_scope(window, monkeypatch):
    """첫 개발: 제작자에게만 공개(2026-11-01 사용자 결정). 아니면 탭·홈 칸 숨김, 설정이 켜져 있어도 돌지 않음."""
    from mabinogi_addon import feature_access
    w, app = window
    index = w._convenience_tabs.indexOf(w._cursor_scroll)
    assert not feature_access.cursor_fx_available()  # 픽스처 사용자는 제작자가 아님
    assert not w._convenience_tabs.isTabVisible(index) and not w.home_page.boxes['편의기능'].isVisibleTo(w.home_page)
    w.cursor_fx.settings['enabled'] = True
    try:
        w.cursor_fx._sync_timer()
        assert not w.cursor_fx.is_enabled() and not w.cursor_fx._timer.isActive()
        w._home_switch('cursor', False)  # 홈에서 바꿀 수 없음
        assert w.cursor_fx.settings['enabled'] is True
        monkeypatch.setattr(feature_access, 'is_creator', lambda: True)
        w.settings_tab.login_changed.emit()  # 로그인 바뀌면 바로 반영
        assert w._convenience_tabs.isTabVisible(index) and w.home_page.boxes['편의기능'].isVisibleTo(w.home_page)
        assert w.cursor_fx.is_enabled() and w.cursor_fx._timer.isActive()
    finally:
        w.cursor_fx.settings['enabled'] = False
        w.cursor_fx._sync_timer()


def test_tab_order_home_switch_and_tab_stay_in_sync(window, monkeypatch):
    from mabinogi_addon import feature_access
    w, app = window
    monkeypatch.setattr(feature_access, 'is_creator', lambda: True)
    w._refresh_cursor_access()
    # 마우스 커서 명세 1절 B안: 2단 계산기·그림대화·마우스 커서, 계산기 안 3단
    assert [w._convenience_tabs.tabText(i) for i in range(w._convenience_tabs.count())] == ['계산기', '그림대화', '마우스 커서']
    assert [w._calculator_tabs.tabText(i) for i in range(w._calculator_tabs.count())] == ['분배', '구슬 분배', '환전비율', '던전 입장']
    try:
        w._home_switch('cursor', True)  # 홈 스위치 → 화면 스위치·설정
        assert w.cursor_tab.switch.isChecked() and w.cursor_fx.is_enabled()
        assert clean_settings(config.load_cursor_fx())['enabled'] is True
        assert w._home_state()['rows']['cursor'][2] is True
        w.cursor_tab.switch.setChecked(False)  # 화면 스위치 → 홈 줄
        assert not w.cursor_fx.is_enabled() and w._home_state()['rows']['cursor'] == ('꺼짐', 'muted', False)
        w._home_open_feature('cursor')  # › → 편의기능 › 마우스 커서
        app.processEvents()
        assert w._tabs.currentWidget() is w._convenience_tabs
        assert w._convenience_tabs.currentWidget() is w._cursor_scroll
    finally:
        w.cursor_fx.update_settings(enabled=False)


def test_idle_cursor_reads_less_often_and_wakes_on_move(fx):
    from mabinogi_addon.ui.cursor_overlay import IDLE_TICK_MS, TICK_MS
    f, clock, pos, watcher = fx
    f.update_settings(enabled=True, tail="dots")
    _run(f, clock, 0.3)
    assert f._timer.interval() == TICK_MS
    _run(f, clock, 1.5)  # 멈춤 1초 넘음
    assert f._timer.interval() == IDLE_TICK_MS
    pos[0] = (450, 320)
    _run(f, clock, 0.02)
    assert f._timer.interval() == TICK_MS


# --- 0.36.0 QA: 꼬리 곡선·반짝이 색 ---


def _circle(speed=16.0, seconds=0.3):
    import math
    trail = Trail()
    t = 0.0
    while t <= 1.0:
        trail.add(t, 300 + 120 * math.cos(t * speed), 200 + 70 * math.sin(t * speed))
        t += 1 / 60
    return trail.points(1.0, seconds)


def _max_turn(points):
    import math
    worst = 0.0
    for a, b, c in zip(points, points[1:], points[2:]):
        h1 = math.atan2(b.y - a.y, b.x - a.x)
        h2 = math.atan2(c.y - b.y, c.x - b.x)
        worst = max(worst, abs((h2 - h1 + math.pi) % (2 * math.pi) - math.pi))
    return worst


def test_smooth_passes_through_points_and_rounds_corners():
    raw = _circle()
    curve = smooth(raw, 5, min_gap=0)
    assert len(curve) == (len(raw) - 1) * 5 + 1
    for i, p in enumerate(raw):  # 원래 점은 그대로 지난다(나이도 같음)
        q = curve[i * 5]
        assert (q.x, q.y, q.age) == pytest.approx((p.x, p.y, p.age))
    # 0.36.1: 기본은 3등분, 점 사이 12px 미만은 나누지 않음(그리기 조각 수 줄이기)
    default = smooth(raw)
    assert len(default) <= (len(raw) - 1) * 3 + 1
    slow = [TailPoint(i * 4.0, 0.0, 1 - i / 20) for i in range(20)]
    assert smooth(slow) == slow
    ages = [p.age for p in curve]
    assert ages == sorted(ages, reverse=True)  # 오래된 것부터 그대로
    assert _max_turn(curve) < _max_turn(raw) / 3  # 꺾이는 각이 훨씬 작다(빠른 원에서 다각형 → 곡선)
    assert smooth(raw[:2]) == raw[:2] and smooth([]) == []


def test_sparkle_color_rule_default_multi_chosen_single():
    assert sparkle_multicolor(clean_settings({})) is True  # 기본(색을 고르기 전) = 여러 색
    assert sparkle_multicolor(clean_settings({"color": "#FFFFFF", "colorChosen": True})) is False  # 흰색 골라도 흰색만
    assert sparkle_multicolor(clean_settings({"color": "#FF5A5F", "colorChosen": True})) is False


@pytest.mark.parametrize("multicolor,expect_many", [(True, True), (False, False)])
def test_sparkle_paint_uses_one_or_many_hues(multicolor, expect_many):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import numpy as np
    from PySide6.QtGui import QImage, QPainter
    from mabinogi_addon.ui.cursor_paint import paint_tail

    img = QImage(640, 400, QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    paint_tail(p, _circle(), "sparkle", "#FFFFFF", 40, 1.0, multicolor=multicolor)
    p.end()
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(400, img.bytesPerLine())[:, :640 * 4].reshape(400, 640, 4)
    lit = arr[..., :3][arr[..., :3].max(axis=2) > 120].astype(int)
    spread = (lit.max(axis=1) - lit.min(axis=1))  # 흰색 계열이면 채널 차이가 작다
    assert bool(spread.max() > 60) == expect_many


def test_choosing_color_in_tab_marks_chosen(fx):
    from mabinogi_addon.ui.cursor_tab import CursorTab
    f, *_ = fx
    tab = CursorTab(f)
    try:
        assert f.settings["colorChosen"] is False
        tab.swatches[3].click()  # 흰색
        assert f.settings["color"] == "#FFFFFF" and f.settings["colorChosen"] is True
        assert clean_settings(config.load_cursor_fx())["colorChosen"] is True
    finally:
        tab.close()


# --- 0.36.1 QA: 흔들 때·꼬리 렉(창 크기를 매 틱 바꿈) ---


def test_ring_window_size_fixed_while_pulsing(fx, monkeypatch):
    from mabinogi_addon.cursor_fx import SHAKE_SCALE
    f, clock, pos, watcher = fx
    f.update_settings(enabled=True, shape="ring", shake=True)
    _run(f, clock, 0.3)
    side = f._ring.width()
    assert side == int(40 * SHAKE_SCALE) + 8 and f._ring.height() == side
    sizes, moves = set(), []
    i = [0]

    def zig():
        i[0] += 1
        pos[0] = (int(500 + (150 if (i[0] // 4) % 2 else -150) * ((i[0] % 4) / 3)), 300)
        sizes.add((f._ring.width(), f._ring.height()))
        moves.append(f._ring.pos())
    f.stats.clear()
    _run(f, clock, 1.5, move=zig)
    assert f._shake_at > 0  # 흔들기 판정됨(맥동)
    assert sizes == {(side, side)} and f.stats["resizes"] == 0  # 크기는 그대로, 위치만
    assert len(set((p.x(), p.y()) for p in moves)) > 5


def test_tail_window_resizes_rarely(fx):
    import math
    f, clock, pos, watcher = fx
    f.update_settings(enabled=True, shape="none", tail="rainbow")
    k = [0]

    def circle():
        k[0] += 1
        t = k[0] / 60
        pos[0] = (int(800 + 250 * math.cos(t * 9)), int(500 + 180 * math.sin(t * 9)))
    f.stats.clear()
    _run(f, clock, 3.0, move=circle)  # 3초 동안 빠르게 원 그리기(180틱)
    assert f.stats["tail_updates"] > 150
    # 0.36.1 2차(Windows 실측: 크게 고정한 창은 칠할 면적이 늘어 선 꼬리 0.66→1.37%): 64px 단위로 꼬리에 맞춤 —
    # 면적은 꼬리만큼, 크기 변경은 틱의 절반 아래(예전 0.36.0: 틱마다 180번)
    assert f.stats["resizes"] <= f.stats["tail_updates"] // 2
    assert f._tail.width() % 64 == 0 and f._tail.height() % 64 == 0


def test_fast_normal_motion_is_not_shake():
    import math
    # 전투 중 흔한 빠른 움직임: 큰 원 돌리기·좌우 두세 번 크게 왕복
    circle = [600 + 300 * math.cos(i / 60 * 12) for i in range(120)]
    assert not any(_feed(ShakeDetector(), circle, 1 / 60))
    three = [500 + (250 if (i // 6) % 2 else -250) * ((i % 6) / 5) for i in range(20)]  # 방향 바뀜 3번
    assert not any(_feed(ShakeDetector(), three, 1 / 60))


def test_precise_timer_and_lag_log(fx, monkeypatch, caplog):
    """0.36.1: 앱 안에서만 렉 — 정밀 타이머, 30초마다 틱 밀림 로그(다른 작업이 막는지 / 그리기가 무거운지 가르기)."""
    import logging
    from PySide6.QtCore import Qt
    from mabinogi_addon.ui import cursor_overlay as co
    f, clock, pos, watcher = fx
    f.update_settings(enabled=True, tail="line")
    assert f._timer.timerType() == Qt.TimerType.PreciseTimer
    real = [1000.0]
    monkeypatch.setattr(co.time, "perf_counter", lambda: real[0])
    caplog.set_level(logging.INFO, logger=co.__name__)
    k = [0]
    for i in range(2000):  # 약 33초: 열 번에 한 번 50ms 밀림
        k[0] += 1
        pos[0] = (400 + k[0] % 50 * 6, 300)
        real[0] += 0.05 if i % 10 == 0 else 0.016
        clock[0] += 0.016
        f.tick()
    lines = [r.getMessage() for r in caplog.records if "마우스 커서 틱" in r.getMessage()]
    assert lines and "늦은 틱(>33ms)" in lines[0] and "최대 간격 50ms" in lines[0]
