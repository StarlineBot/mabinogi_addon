"""진짜 창모드 — 펫이 보이는 게임 화면을 피해 빈 바닥에서만 돌아다님(QA 11-26, 사용자 결정 ①안)."""
import random

import pytest

from mabinogi_addon.character import brain as br
from mabinogi_addon.character import floor_space as fs

FLOOR = br.Floor(0, 1920, 1040)
BLOCK = [(600.0, 1400.0)]      # 창모드 게임 창이 바닥 띠와 겹치는 x


def _brain(x=200.0, seed=3):
    b = br.Brain(FLOOR, rng=random.Random(seed), profile=br.ARIA)
    b.pos = (x, FLOOR.y)
    return b


def _run(b, seconds, blocked=(), game_front=False, start=0.0, dt=0.05):
    """tick을 돌리며 (걷기 목표 x 목록, 위치 x 목록)을 모음."""
    targets, xs, events = [], [], []
    t = start
    while t < start + seconds:
        events += b.tick(t, game_front, blocked)
        if b._target is not None:
            targets.append(b._target[0])
        xs.append(b.pos[0])
        t += dt
    return targets, xs, events


# ---- 순수 계산 --------------------------------------------------------------------------------
def test_merge_and_free_spans():
    assert fs.merge([(5, 8), (0, 3), (2, 4), (8, 9)]) == [(0, 4), (5, 9)]
    assert fs.free_spans(FLOOR, BLOCK) == [(0, 600), (1400, 1920)]
    assert fs.free_spans(FLOOR, [(250, 1700)]) == []              # 양쪽 다 300보다 좁음
    assert fs.free_spans(FLOOR, []) == [(0, 1920)]


def test_windowed_game_blocks_its_x_range():
    """창모드: 게임 창이 가운데, 위에 아무것도 없음 → 게임 창 x 범위가 막힘."""
    assert fs.blocked_spans([(600, 200, 1400, 1000)], FLOOR, 190) == [(600, 1400)]


def test_fullscreen_covered_by_browser_blocks_nothing():
    """전체창 + 브라우저가 전부 덮음 → 보이는 사각형 없음 → 막힌 구간 없음(지금처럼 화면 전체)."""
    game = (0, 0, 1920, 1080)
    visible = fs_subtract_all(game, [(0, 0, 1920, 1080)])
    assert visible == [] and fs.blocked_spans(visible, FLOOR, 190) == []


def test_fullscreen_with_small_browser_leaves_no_room():
    """전체창 + 작은 브라우저 창 → 바닥 띠 대부분이 게임 → 설 자리 없음."""
    visible = fs_subtract_all((0, 0, 1920, 1080), [(700, 100, 1300, 700)])
    blocked = fs.blocked_spans(visible, FLOOR, 190)
    assert blocked == [(0, 1920)] and fs.free_spans(FLOOR, blocked) == []


def test_small_window_above_floor_band_blocks_nothing():
    """게임 창 아래 끝이 바닥 띠보다 위(창이 작고 화면 위쪽) → 막힌 구간 없음."""
    assert fs.blocked_spans([(600, 100, 1400, 800)], FLOOR, 190) == []


def test_dpi_150_conversion():
    rects = fs.to_logical([(900, 300, 2100, 1500)], 1.5)
    assert rects == [(600, 200, 1400, 1000)]
    assert fs.blocked_spans(rects, FLOOR, 190) == [(600, 1400)]


def fs_subtract_all(rect, covers):
    from mabinogi_addon.system.dialogue_visibility import subtract
    pieces = [rect]
    for cover in covers:
        pieces = [p for piece in pieces for p in subtract(piece, cover)]
    return pieces


# ---- brain --------------------------------------------------------------------------------
def test_roam_targets_never_enter_blocked_span():
    """(a)·(c) 막힌 구간이 있으면 목표 x가 그 안에 들어가지 않고, 반대편으로 건너가지도 않음."""
    for seed, x in ((1, 200.0), (2, 1700.0), (3, 450.0)):
        b = _brain(x, seed)
        targets, xs, _ = _run(b, 240, BLOCK)
        assert targets, seed
        assert not [t for t in targets if 600 - 150 < t < 1400 + 150], seed
        side = x < 600
        assert all((p < 600) == side for p in xs), seed


def test_standing_inside_blocked_walks_out_to_nearest():
    """(b) 막힌 구간 안에 서 있으면(창을 옮김) 가까운 빈 구간으로 걸어 나감."""
    b = _brain(1300.0)
    _run(b, 2, ())                        # 막힘 없을 때 서 있음
    _, xs, _ = _run(b, 20, BLOCK, start=2)
    assert xs[-1] >= 1400 + 150 - 1       # 오른쪽이 더 가까움
    b = _brain(700.0)
    _, xs, _ = _run(b, 20, BLOCK)
    assert xs[-1] <= 600 - 150 + 1


def test_no_room_goes_home_and_dozes_without_affinity_or_game_lines():
    """(d) 빈 구간이 펫 폭보다 좁으면 구석(home)으로 가서 졸고 — 호감도 시간·게임 대사는 없음."""
    b = _brain(900.0)
    _, _, events = _run(b, 90, [(250, 1700)])
    assert b._goal == "corner" and b.state in b.profile.sitting
    assert b.pos == b.home()
    assert ("corner_minute",) not in events
    assert ("say", "game_enter") not in events


def test_block_gone_roams_whole_floor_again():
    """(e) 막힌 구간이 사라지면 다시 화면 전체를 돌아다님."""
    b = _brain(200.0, seed=5)
    _run(b, 60, BLOCK)
    targets, _, _ = _run(b, 400, (), start=60)
    assert any(600 < t < 1400 for t in targets) and any(t > 1400 for t in targets)


def test_game_front_unchanged_and_counts_affinity():
    """(f) 게임 포그라운드 동작은 그대로 — 막힌 구간을 받아도 무시하고 구석·호감도."""
    b = _brain(900.0)
    _, _, events = _run(b, 90, BLOCK, game_front=True)
    assert b._goal == "corner" and b.state in b.profile.sitting
    assert ("say", "game_enter") in events and ("corner_minute",) in events


def test_fullscreen_alt_tab_roams_everywhere():
    """전체창 회귀 금지: 브라우저가 게임을 덮어 막힌 구간이 없으면 구석에서 자지 않고 화면 전체."""
    b = _brain(900.0, seed=7)
    targets, _, _ = _run(b, 300, ())
    assert b._goal == "roam" and min(targets) < 600 and max(targets) > 1400


@pytest.mark.parametrize("profile", [br.DARE, br.ARIA, br.IAN, br.LENA, br.STARLINE])
def test_every_profile_avoids_block(profile):
    b = br.Brain(FLOOR, rng=random.Random(11), profile=profile)
    b.pos = (300.0, FLOOR.y)
    targets, _, _ = _run(b, 200, BLOCK)
    assert not [t for t in targets if 450 < t < 1550]


# ---- 창·컨트롤러 연결 ----------------------------------------------------------------------
@pytest.fixture
def app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_pet_window_asks_blocked_once_a_second_only_when_game_not_front(app):
    from PySide6.QtGui import QImage

    from mabinogi_addon.ui.pet_window import PetWindow

    clock = [0.0]
    calls, front, seen = [], [False], []
    b = _brain(200.0)
    real = b.tick
    b.tick = lambda now, game_front, blocked=(): seen.append(tuple(blocked)) or real(now, game_front, blocked)
    image = QImage(100, 280, QImage.Format.Format_ARGB32)
    w = PetWindow(b, {n: image for f, _t, _l in b.profile.anims.values() for n in f}, "#ffffff",
                  game_front=lambda: front[0], clock=lambda: clock[0], blocked=lambda: calls.append(1) or BLOCK)
    for _ in range(60):          # 3초(0.05초마다)
        w.step()
        clock[0] += 0.05
    assert len(calls) == 3 and seen[-1] == tuple(BLOCK)
    front[0] = True
    for _ in range(60):
        w.step()
        clock[0] += 0.05
    assert len(calls) == 3 and seen[-1] == ()        # 게임 중엔 부르지 않음
    front[0] = False
    w._blocked_fn = lambda: 1 / 0                    # 판정 실패 → 막힌 곳 없음
    for _ in range(30):
        w.step()
        clock[0] += 0.05
    assert seen[-1] == ()
    w.close()


def test_controller_converts_visible_rects_to_blocked_spans(app, monkeypatch):
    from mabinogi_addon.ui import character_controller as cc
    from mabinogi_addon.ui import dpi

    class Watcher:
        def __init__(self):
            self.rects = [(900, 300, 2100, 1500)]

        def visible_game_rects(self):
            return self.rects

    monkeypatch.setattr(dpi, "screen_scale", lambda: 1.5)
    ctrl = cc.CharacterController.__new__(cc.CharacterController)
    ctrl._watcher = watcher = Watcher()
    fn = ctrl._blocked_fn(FLOOR, br.ARIA)
    assert fn() == [(600, 1400)]
    watcher.rects = None                              # 모름 → 막힌 곳 없음
    assert fn() == ()
    ctrl._watcher = None
    assert fn() == ()


def test_watchers_default_to_unknown():
    from mabinogi_addon.system.game_visibility import visible_game_rects
    from mabinogi_addon.system.window_watcher import AlwaysActiveWatcher

    assert AlwaysActiveWatcher().visible_game_rects() is None
    import sys
    if sys.platform != "win32":
        assert visible_game_rects("client.exe", ("마비노기",), 1) is None


def test_visible_game_rects_with_fake_windows(monkeypatch):
    """Z 순서 위 창 영역 빼기 — 우리 앱·투명 클릭 통과·숨김 창은 안 가림, 주 화면으로 자름(가짜 win32)."""
    import sys
    import types

    from mabinogi_addon.system import game_visibility as gv
    from mabinogi_addon.system import window_watcher as ww

    # hwnd: (pid, exe, 보임, 최소화, 영역, 확장 스타일, 제목) — 앞(위) 창부터
    wins = {
        1: (50, "mine.exe", True, False, (0, 0, 400, 400), 0x80, "펫"),            # 우리 펫·오버레이(도구 창 — 가리지 않음)
        2: (60, "hud.exe", True, False, (0, 0, 3000, 2000), 0x80020, "HUD"),     # 클릭 통과 투명 오버레이
        3: (70, "discord.exe", True, False, (1500, 800, 1800, 1100), 0, "디스코드"),  # 게임 오른쪽 아래 일부 가림
        4: (80, "chrome.exe", False, False, (0, 0, 1920, 1080), 0, "숨김"),
        5: (90, "client.exe", True, False, (600, 200, 1600, 1100), 0, "마비노기"),   # 게임(화면 밖 20px)
        6: (91, "client.exe", True, False, (0, 0, 100, 100), 0, "마비노기 작은 창"),
    }
    gui = types.SimpleNamespace(
        EnumWindows=lambda cb, extra: [cb(h, extra) for h in wins],
        IsWindowVisible=lambda h: wins[h][2], IsIconic=lambda h: wins[h][3],
        GetWindowText=lambda h: wins[h][6], GetWindowLong=lambda h, i: wins[h][5],
        GetWindowRect=lambda h: wins[h][4])
    proc = types.SimpleNamespace(GetWindowThreadProcessId=lambda h: (0, wins[h][0]))
    api = types.SimpleNamespace(MonitorFromPoint=lambda p, f: 1, GetMonitorInfo=lambda m: {"Monitor": (0, 0, 1920, 1080)})
    monkeypatch.setitem(sys.modules, "win32gui", gui)
    monkeypatch.setitem(sys.modules, "win32process", proc)
    monkeypatch.setitem(sys.modules, "win32api", api)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(gv, "_bounds", lambda g, c, w, h: wins[h][4])
    monkeypatch.setattr(gv, "_cloaked", lambda c, w, h: False)
    pids = {v[0]: v[1] for v in wins.values()}
    monkeypatch.setattr(ww, "_exe_basename_of_pid", lambda pid: pids[pid])
    rects = gv.visible_game_rects("client.exe", ("마비노기",), 50)
    covered = sum((r - l) * (b - t) for l, t, r, b in rects)
    assert covered == 1000 * 880 - 100 * 280            # 게임(주 화면 안) − 디스코드가 가린 부분
    assert fs.blocked_spans(rects, FLOOR, 190) == [(600, 1500)]           # 바닥 띠 오른쪽 끝은 디스코드가 덮음
    assert gv.visible_game_rects(None, ("마비노기",), 50) == rects   # 미등록이면 제목 폴백(같은 창)
    monkeypatch.setattr(gv, "_bounds", lambda *a: 1 / 0)
    assert gv.visible_game_rects("client.exe", ("마비노기",), 50) is None   # 실패 → 모름


def test_own_main_window_covers_but_own_tool_window_does_not(monkeypatch):
    """QA 반려 11-26: 우리 앱 일반 창(메인·대화상자)은 실제로 게임을 덮음 → 전체창 위에 띄우면 roam. 도구 창(펫·오버레이)은 안 가림."""
    import sys
    import types

    from mabinogi_addon.system import game_visibility as gv
    from mabinogi_addon.system import window_watcher as ww

    def run(front_style, front_rect):
        wins = {1: (50, front_style, front_rect), 2: (90, 0, (0, 0, 1920, 1080))}   # 우리 창 / 전체창 게임
        gui = types.SimpleNamespace(
            EnumWindows=lambda cb, extra: [cb(h, extra) for h in wins],
            IsWindowVisible=lambda h: True, IsIconic=lambda h: False,
            GetWindowText=lambda h: "마비노기", GetWindowLong=lambda h, i: wins[h][1],
            GetWindowRect=lambda h: wins[h][2])
        monkeypatch.setitem(sys.modules, "win32gui", gui)
        monkeypatch.setitem(sys.modules, "win32process",
                            types.SimpleNamespace(GetWindowThreadProcessId=lambda h: (0, wins[h][0])))
        monkeypatch.setitem(sys.modules, "win32api", types.SimpleNamespace(
            MonitorFromPoint=lambda p, f: 1, GetMonitorInfo=lambda m: {"Monitor": (0, 0, 1920, 1080)}))
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(gv, "_bounds", lambda g, c, w, h: wins[h][2])
        monkeypatch.setattr(gv, "_cloaked", lambda c, w, h: False)
        monkeypatch.setattr(ww, "_exe_basename_of_pid", lambda pid: {50: "mabinogi_addon.exe", 90: "client.exe"}[pid])
        floor = br.Floor(0, 1920, 1039)
        return fs.blocked_spans(gv.visible_game_rects("client.exe", ("마비노기",), 50), floor, 190)

    assert run(0, (0, 0, 1920, 1040)) == []                      # (1) 우리 메인 창이 거의 덮음 → 막힌 곳 없음 → roam
    b = _brain(900.0)
    targets, _, _ = _run(b, 120, run(0, (0, 0, 1920, 1040)))
    assert b._goal == "roam" and targets
    assert run(0x80, (0, 0, 1920, 1040)) == [(0, 1920)]          # (2) 도구 창(펫·오버레이)은 가림으로 안 침
    assert run(0x80020 | 0x80, (0, 0, 1920, 1040)) == [(0, 1920)]


# ---- 걷는 중 쓰다듬기(QA 11-26 '걸어다닐 때 해도 안 됨') -------------------------------------------
@pytest.mark.parametrize("profile", [br.DARE, br.LENA])
def test_petting_while_walking_stops_and_pets(profile):
    b = br.Brain(br.Floor(0, 1920, 1000), rng=random.Random(1), profile=profile)
    b.pos = (300.0, 1000.0)
    b.tick(0.0, False)
    b._walk_to((1500.0, 1000.0), 0.0)
    t, events, stood = 0.0, [], None
    while t < 2.0:
        t += 0.05
        events += b.tick(t, False)
        side = 1 if int(t / 0.15) % 2 else -1          # 머리 위에서 ±25px로 흔들며 따라감(커서도 펫과 같이 움직임)
        events += b.hover(t, b.pos[0] + 25 * side, True)
        if stood is None and b._rub_turns:
            stood = b.state
        if ("say", "pet_start") in events:
            break
    assert ("say", "pet_start") in events and t <= 2.0
    assert stood == "stand"                             # 첫 전환에 멈춰 섬


def test_petting_while_walking_in_pet_window(app):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QImage, QMouseEvent

    from mabinogi_addon.ui.pet_window import PetWindow, load_frames
    clock = [0.0]
    b = br.Brain(br.Floor(0, 1920, 1000), rng=random.Random(1), profile=br.DARE)
    b.pos = (300.0, 1000.0)
    w = PetWindow(b, load_frames("다래", br.DARE), "#ffffff", game_front=lambda: False, clock=lambda: clock[0])
    w.step()
    b._walk_to((1500.0, 1000.0), 0.0)
    got = []
    w.events.connect(lambda ev: got.extend(ev))
    while clock[0] < 2.0 and ("say", "pet_start") not in got:
        clock[0] += 0.05
        w.step()
        w.grab()                                        # 오프스크린 — 그려야 그림 자리(_sprite)가 정해짐
        head = w._sprite.center().x(), w._sprite.top() + w._sprite.height() * 0.15
        side = 1 if int(clock[0] / 0.15) % 2 else -1
        local = QPointF(head[0] + 25 * side, head[1])
        glob = QPointF(w.x() + local.x(), w.y() + local.y())
        w.mouseMoveEvent(QMouseEvent(QMouseEvent.Type.MouseMove, local, glob, Qt.MouseButton.NoButton,
                                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    assert ("say", "pet_start") in got
    w.close()


# ---- 레나 앉아 떠 있기(사용자 11-26 '마법으로 떠 있는 자세 — 둥둥') ------------------------------------
def test_lena_sit_floats_and_bobs_then_lands_smoothly():
    b = br.Brain(br.Floor(0, 1920, 1000), rng=random.Random(2), profile=br.LENA)
    b.pos = (1700.0, 1000.0)
    t, offs = 0.0, []
    while t < 30:
        b.tick(t, True)
        offs.append((t, b.state, b.float_offset(t)))
        t += 0.05
    k = br.LENA.scale
    sitting = [(t, o) for t, s, o in offs if s == "sit_loop" and t - b._float_since >= 0.4]
    assert sitting
    vals = [o for _t, o in sitting]
    assert -(14 + 3) * k - 0.01 <= min(vals) and max(vals) <= -(14 - 3) * k + 0.01       # −14 ± 3(배율)
    assert all(o == 0 for _t, s, o in offs if s in ("stand", "walk", "crouch"))
    steps = [abs(b2 - a2) for (_t1, _s1, a2), (_t2, _s2, b2) in zip(offs, offs[1:])]
    assert max(steps) <= 14 * k * 0.05 / 0.4 + 0.5                                         # 앉을 때 튀지 않음
    # 주기 2.4초: 2.4초 뒤 같은 높이
    t0 = sitting[0][0]
    assert abs(b.float_offset(t0 + 2.4) - b.float_offset(t0)) < 0.05 or b.state != "sit_loop"
    # 게임이 끝나면 일어나며 내려옴(튀지 않음)
    seen = []
    while t < 40:
        b.tick(t, False)
        seen.append((b.state, b.float_offset(t)))
        t += 0.05
    rise = [o for s, o in seen if s == "rise"]
    assert rise and rise[0] < -5 and all(abs(a - c) <= 14 * k * 0.05 / 0.4 * 1.2 + 3 for a, c in zip(rise, rise[1:]))
    assert seen[-1][1] == 0


@pytest.mark.parametrize("profile", [br.DARE, br.ARIA, br.IAN])
def test_other_characters_never_float(profile):
    b = br.Brain(br.Floor(0, 1920, 1000), rng=random.Random(2), profile=profile)
    b.pos = (1700.0, 1000.0)
    t = 0.0
    while t < 20:
        b.tick(t, True)
        assert b.float_offset(t) == 0
        t += 0.1


def test_starline_only_settles_into_its_drawn_float():
    """Starline은 둥둥 떠 있기(sit_float)가 없고, 앉은 반복에 들어갈 때만 앉기 끝 높이에서 1.5초 동안 제자리로 올라옴(sit_settle,
    QA 11-28 — 앉아 뜬 높이는 그림 자리(앵커)로). 그래서 offset은 0 이상(아래)이고 다 오르면 0."""
    b = br.Brain(br.Floor(0, 1920, 1000), rng=random.Random(2), profile=br.STARLINE)
    b.pos = (1700.0, 1000.0)
    assert br.STARLINE.sit_float is None and br.STARLINE.sit_settle
    t, entered = 0.0, None
    while t < 20:
        b.tick(t, True)
        off = b.float_offset(t)
        assert off >= 0
        if b.state == "sit_loop" and entered is None:
            entered = t
        if entered is not None and t > entered + br.STARLINE.sit_settle[1] + 0.1 and b.state == "sit_loop":
            assert off == 0
        t += 0.1
    assert entered is not None
