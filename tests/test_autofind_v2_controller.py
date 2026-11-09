"""자동 찾기 v2 화면 쪽 진행(docs/autofind-v2-creator-spec.md 3·6절) — 가짜 캡처·가짜 탐지기·가짜 시계."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import autofind_regions, config
from mabinogi_addon.ui import autofind_v2_controller as ctl

TARGET = (1, 100, 0, 0, 1920, 1080)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    saved = {"buffRegion": {"x": 1, "y": 2, "w": 3, "h": 4}}
    path.write_text(json.dumps(saved), encoding="utf-8")
    monkeypatch.setattr(config, "LOCAL_CONFIG_PATH", path)
    monkeypatch.setattr(config, "_read_local_config", lambda p=path: json.loads(path.read_text(encoding="utf-8")))
    monkeypatch.setattr(config, "_write_local_config",
                        lambda data, p=path: path.write_text(json.dumps(data), encoding="utf-8"))
    monkeypatch.setattr("mabinogi_addon.ui.dpi.screen_scale", lambda: 1.0)
    autofind_regions.reset_for_tests()
    autofind_regions.activate(True)
    autofind_regions.set_use_values({k: True for k in autofind_regions.USE_KEYS})
    yield path
    autofind_regions.reset_for_tests()


class Inline:
    inline = True

    def submit(self, fn):
        from concurrent.futures import Future
        f = Future()
        f.set_result(fn())
        return f


class Capture:
    def __init__(self):
        self.calls = []

    def grab(self, x, y, w, h):
        self.calls.append((x, y, w, h))
        return np.zeros((h, w, 3), np.uint8)

    def close(self):
        pass


class Finders:
    def __init__(self, boxes=None):
        self.boxes = boxes if boxes is not None else {"skillbar": (10, 900, 400, 60), "stat_bars": (10, 10, 200, 40),
                               "buff": (1700, 200, 30, 300), "resources": {"dorcha": (500, 500, 40, 20)},
                               "boss": None, "halo_timer": None}
        self.calls = []

    def finders(self):
        from mabinogi_addon import autofind_v2 as v2

        def make(k):
            def run(frame):
                box = self.boxes.get(k)
                if frame.shape[1] < 1900:  # 지난 자리 여백 조각(화면 전체는 1920·2560) — 그 조각 안의 자리로 돌려준다
                    self.calls.append(k + "@margin")
                    if k in ("skillbar", "stat_bars") and not self.ui or not isinstance(box, tuple):
                        return None
                    x0, y0, x1, y1 = v2.margin_rect(box, TARGET[4], TARGET[5])
                    if frame.shape[:2] != (y1 - y0, x1 - x0):
                        return None  # 다른 자리 둘레 — 거기엔 없음
                    return (box[0] - x0, box[1] - y0, box[2], box[3])
                self.calls.append(k)
                if k in ("skillbar", "stat_bars") and not self.ui:
                    return None
                return box
            return run
        return {k: make(k) for k in ("skillbar", "stat_bars", "buff", "resources", "boss", "halo_timer")}

    ui = True  # 게임 UI(단축바·체력바)가 보이나 — False면 로딩·로그인 화면

    reads: dict = {}  # 항목별 지난 자리 판독 결과 바꾸기(기본 True)

    def readers(self):
        def read(key):
            return lambda crop: self.ui if key in ("skillbar", "stat_bars") else self.reads.get(key, True)
        return {k: read(k) for k in ("skillbar", "stat_bars", "buff", "dorcha", "tuarim", "boss", "halo_timer")}


class Watcher:
    active = True

    def is_game_active(self):
        return self.active


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def _make(app, *, target=TARGET, finders=None, wanted=None):
    clock, cap, fnd, watcher = Clock(), Capture(), finders or Finders(), Watcher()
    box = {"t": target}
    c = ctl.AutofindV2Controller(watcher, wanted, target_fn=lambda prev: box["t"], executor=Inline(),
                                 capture=cap, finders=fnd, clock=clock)
    c.engine.reset(0.0)
    return c, clock, cap, fnd, watcher, box


def _run(c, clock, seconds, step=0.5):
    end = clock.t + seconds
    while clock.t < end:
        clock.t += step
        c.tick()


def test_initial_find_publishes_runtime_regions_and_keeps_saved_config(app, isolated):
    before = json.loads(isolated.read_text(encoding="utf-8"))
    c, clock, cap, fnd, *_ = _make(app)
    _run(c, clock, 1.5)
    assert c.engine.phase == "stable"
    assert autofind_regions.region_for("buff", {"x": 1, "y": 2, "w": 3, "h": 4}) == {"x": 1700, "y": 200, "w": 30, "h": 300}
    assert autofind_regions.region_for("skillbar", None) == {"x": 10, "y": 900}
    assert autofind_regions.region_for("tuarim", None) is None  # 못 찾음 + 저장 영역 없음 → 쉰다
    assert autofind_regions.region_for("tuarim", {"x": 9, "y": 9, "w": 9, "h": 9}) == {"x": 9, "y": 9, "w": 9, "h": 9}  # v1 대비책
    assert autofind_regions.source("tuarim") == "v1" and autofind_regions.source("buff") == "auto"
    after = json.loads(isolated.read_text(encoding="utf-8"))
    assert after["buffRegion"] == before["buffRegion"]  # 저장 영역 그대로
    assert set(after) == {"buffRegion", "autofindV2"}  # 찾은 자리는 autofindV2.last에만
    assert after["autofindV2"]["last"]["buff"]["size"] == [1920, 1080]
    assert [k for k in cap.calls if k[2:] == (1920, 1080)] == [(0, 0, 1920, 1080)]  # 처음 찾기 = 화면 한 번(나머지는 보스바·전투 시간 예상 자리 작은 조각)
    assert all(w <= 680 for _, _, w, _ in cap.calls[1:])


def test_stable_state_makes_no_find_or_capture(app):
    c, clock, cap, fnd, *_ = _make(app, wanted=lambda k: k not in ("tuarim", "boss", "halo_timer"))
    _run(c, clock, 1.5)
    captures, calls = len(cap.calls), len(fnd.calls)
    for _ in range(1200):  # 10분
        clock.t += 0.5
        for k in ("buff", "dorcha", "stat_bars"):
            autofind_regions.report(k, True)
        c.tick()
    assert len(cap.calls) == captures and len(fnd.calls) == calls


def test_lost_item_researched_after_10s_and_only_that_group(app):
    c, clock, cap, fnd, *_ = _make(app, wanted=lambda k: k == "buff")
    _run(c, clock, 1.5)
    fnd.calls.clear()
    autofind_regions.report("buff", False)
    _run(c, clock, 11)
    assert [k for k in fnd.calls if not k.endswith("@margin")] == ["buff"]  # 'UI 보이나' 여백 확인 말고는 버프만


def test_window_resize_restarts_initial_find(app):
    c, clock, cap, fnd, _, box = _make(app)
    _run(c, clock, 1.5)
    gen = c.engine.generation
    box["t"] = (1, 100, 0, 0, 2560, 1440)
    c.tick()
    assert c.engine.generation > gen and autofind_regions.region_for("buff", None) is None
    _run(c, clock, 1.0)
    assert c.engine.phase == "stable" and (0, 0, 2560, 1440) in cap.calls


def test_paused_when_game_not_in_front(app):
    c, clock, cap, fnd, watcher, _ = _make(app)
    watcher.active = False
    _run(c, clock, 30)
    assert cap.calls == [] and c.engine.phase == "waiting_ui"


def test_loading_screen_rechecks_every_2_5s(app):
    fnd = Finders(boxes={})
    c, clock, cap, *_ = _make(app, finders=fnd)
    _run(c, clock, 1.0)
    assert len(cap.calls) == 1 and c.engine.phase == "waiting_ui"
    _run(c, clock, 2.0)  # 결과는 다음 틱(t=1)에 반영 → 다시 확인은 t=3.5
    assert len(cap.calls) == 1
    _run(c, clock, 0.5)
    assert len(cap.calls) == 2


def _full_finds(fnd):
    return [k for k in fnd.calls if not k.endswith("@margin")]


def test_loading_between_games_makes_no_full_screen_find(app):
    """게임 → 로딩 3초 → 게임: 화면 전체 찾기 0번(명세 6.1 시험)."""
    c, clock, cap, fnd, *_ = _make(app, wanted=lambda k: k in ("buff", "skillbar", "stat_bars"))
    _run(c, clock, 1.5)
    assert c.engine.phase == "stable"
    fnd.calls.clear()
    full_before = [k for k in cap.calls if k[2:] == (1920, 1080)]

    def play(seconds, ok):
        end = clock.t + seconds
        while clock.t < end:
            clock.t += 0.5
            for k in ("buff", "skillbar", "stat_bars"):
                autofind_regions.report(k, ok)
            c.tick()
    play(20, True)
    fnd.ui = False
    play(3, False)
    assert c.engine.ui_hidden
    fnd.ui = True
    play(20, True)
    assert not c.engine.ui_hidden
    assert _full_finds(fnd) == []
    assert [k for k in cap.calls if k[2:] == (1920, 1080)] == full_before


def test_long_loading_never_counts_failures(app):
    """로딩 2분: 실패 0번, 다시 찾기 0번 — 다시 보이면 지난 자리로 바로 읽는다."""
    c, clock, cap, fnd, *_ = _make(app, wanted=lambda k: k in ("buff", "skillbar", "stat_bars"))
    _run(c, clock, 1.5)
    fnd.calls.clear()
    fnd.ui = False
    for _ in range(240):
        clock.t += 0.5
        autofind_regions.report("buff", False)
        c.tick()
    assert _full_finds(fnd) == [] and c.engine.items["buff"].failures == 0
    assert autofind_regions.region_for("buff", None) == {"x": 1700, "y": 200, "w": 30, "h": 300}
    fnd.ui = True
    _run(c, clock, 3.0)
    assert not c.engine.ui_hidden and not c.engine.items["buff"].unhealthy


def test_login_then_connect_finds_within_3s(app):
    """로그인 화면 2분 → 접속: 3초 안에 처음 찾기."""
    fnd = Finders()
    fnd.ui = False
    c, clock, cap, *_ = _make(app, finders=fnd)
    _run(c, clock, 120)
    assert c.engine.phase == "waiting_ui"
    fnd.ui = True
    _run(c, clock, 3.0)
    assert c.engine.phase == "stable" and c.engine.items["buff"].status == "found"


def test_user_override_wins(app):
    c, clock, *_ = _make(app)
    _run(c, clock, 1.5)
    autofind_regions.user_set("buff")
    saved = {"x": 1, "y": 2, "w": 3, "h": 4}
    assert autofind_regions.region_for("buff", saved) == saved and c.engine.items["buff"].user
    c.restart()
    _run(c, clock, 1.0)
    assert autofind_regions.region_for("buff", saved) == saved


def test_last_positions_used_for_same_window_size(app, isolated):
    c, clock, cap, fnd, *_ = _make(app)
    _run(c, clock, 1.5)
    c.shutdown()
    autofind_regions.reset_for_tests()
    autofind_regions.activate(True)
    autofind_regions.set_use_values({k: True for k in autofind_regions.USE_KEYS})
    fnd2 = Finders()
    c2, clock2, *_ = _make(app, finders=fnd2)
    _run(c2, clock2, 1.5)
    assert "buff" not in fnd2.calls and c2.engine.items["buff"].source == "last"
    assert "buff@margin" in fnd2.calls  # 지난 자리 둘레 여백 조각에서만 찾음(화면 전체 탐지 없음)


def test_inactive_provider_reports_nothing(app):
    autofind_regions.activate(False)
    called = []
    autofind_regions.set_reporter(lambda *a: called.append(a))
    autofind_regions.report("buff", True)
    saved = {"x": 1, "y": 2, "w": 3, "h": 4}
    assert called == [] and autofind_regions.region_for("buff", saved) == saved



def test_game_restart_with_last_positions_waits_for_ui_then_finds(app, isolated, caplog):
    """QA 7b629b2: 지난 자리가 있어도(게임 재시작) 로딩 화면에선 처음 찾기를 하지 않고(실패 0), 게임 화면이 되면 바로 처음 찾기."""
    import logging
    c, clock, cap, fnd, *_ = _make(app)
    _run(c, clock, 1.5)  # 첫 실행: 지난 자리 기록
    c.shutdown()
    autofind_regions.reset_for_tests()
    autofind_regions.activate(True)
    autofind_regions.set_use_values({k: True for k in autofind_regions.USE_KEYS})
    caplog.set_level(logging.INFO, logger="mabinogi_addon.ui.autofind_v2_controller")
    fnd2 = Finders()
    fnd2.ui = False  # 게임 재시작 → 로딩 화면
    c2, clock2, *_ = _make(app, finders=fnd2)
    _run(c2, clock2, 25)
    assert c2.engine.phase == "waiting_ui" and "buff" not in fnd2.calls  # 처음 찾기 안 함
    assert all(it.failures == 0 for it in c2.engine.items.values())  # 실패로 세지 않음
    assert autofind_regions.region_for("buff", None) is None
    fnd2.ui = True  # 게임 화면
    _run(c2, clock2, 10.5)
    assert c2.engine.phase == "stable" and c2.engine.items["buff"].status == "found"
    assert autofind_regions.region_for("buff", None) is not None
    text = [r.getMessage() for r in caplog.records]
    assert sum("UI 아직 안 보임" in t for t in text) == 1  # 기다리기 시작할 때 한 줄
    assert any("게임 UI가 보여요" in t for t in text) and any("처음 찾기" in t and "초(CPU" in t for t in text)


def _real_last_setup(isolated, frame):
    """실제 탐지기로 찾은 단축바·체력바 자리를 autofindV2.last에(같은 게임 창 크기)."""
    from mabinogi_addon.autofind_replay import detector_assets, run_detector
    last = {}
    for key in ("skillbar", "stat_bars"):
        box = run_detector(key, frame, detector_assets(key), {})
        assert box is not None, key
        last[key] = {"box": dict(zip(("x", "y", "w", "h"), (int(v) for v in box))), "size": [frame.shape[1], frame.shape[0]]}
    raw = json.loads(isolated.read_text(encoding="utf-8"))
    raw["autofindV2"] = {"last": last}
    isolated.write_text(json.dumps(raw), encoding="utf-8")


class ShotCapture(Capture):
    def __init__(self, frame):
        super().__init__()
        self.frame = frame

    def grab(self, x, y, w, h):
        self.calls.append((x, y, w, h))
        return None if self.frame is None else self.frame[y:y + h, x:x + w].copy()


@pytest.mark.parametrize("loading", [False, True])
def test_real_finders_last_positions_with_margin(app, isolated, loading):
    """QA 92e9ca1(72824a8 회귀): 지난 자리를 딱 맞게 잘라 탐지기에 넣으면 1440에서 늘 False → '게임 화면을 기다리는 중' 고착.
    이제 둘레 여유로 실제 탐지기 — 게임 화면(013739)은 처음 찾기 진행, 로딩 화면(UI 없음)은 기다림."""
    from mabinogi_addon import image_io
    import cv2
    shot = image_io.imread("tests/data/스크린샷 2026-11-06 013739.png", cv2.IMREAD_COLOR)
    _real_last_setup(isolated, shot)
    frame = np.zeros_like(shot) if loading else shot
    h, w = shot.shape[:2]
    clock, watcher = Clock(), Watcher()
    c = ctl.AutofindV2Controller(watcher, None, target_fn=lambda prev: (1, 100, 0, 0, w, h), executor=Inline(),
                                 capture=ShotCapture(frame), clock=clock)
    c.engine.reset(0.0)
    c._finders.finders = (lambda real: (lambda: {k: v for k, v in real().items()}))(c._finders.finders)
    _run(c, clock, 1.0)
    if loading:
        assert c.engine.phase == "waiting_ui"
    else:
        assert c.engine.phase == "stable" and c.engine.items["skillbar"].status == "found"
    c.shutdown()


BOSS, HALO = (700, 60, 520, 28), (880, 260, 160, 40)


def _second_run_without_boss(app, isolated, boss_now=None):
    """첫 실행에서 보스바·전투 시간을 찾아 지난 자리를 남기고, 보스바가 없는 화면으로 다시 실행."""
    first = Finders()
    first.boxes.update(boss=BOSS, halo_timer=HALO)
    c, clock, *_ = _make(app, finders=first)
    _run(c, clock, 1.5)
    assert json.loads(isolated.read_text(encoding="utf-8"))["autofindV2"]["last"]["boss"]["box"]["x"] == 700
    c.shutdown()
    autofind_regions.reset_for_tests()
    autofind_regions.activate(True)
    autofind_regions.set_use_values({k: True for k in autofind_regions.USE_KEYS})
    fnd = Finders()
    fnd.boxes.update(boss=boss_now, halo_timer=None)
    fnd.reads = {"boss": False, "halo_timer": False}  # 지난 자리에 지금은 보스바·전투 시간이 없음
    return _make(app, finders=fnd)


def _ui_crop(c, key):
    from mabinogi_addon import autofind_v2 as v2
    x0, y0, x1, y1 = v2.margin_rect(c.engine.items[key].box, TARGET[4], TARGET[5])
    return (x0, y0, x1 - x0, y1 - y0)


def test_boss_and_halo_last_spot_used_at_once_without_appear_find(app, isolated, caplog):
    """사용자 11-07(QA 82db972): 지난 자리 있음 + 보스바 없는 화면 → 바로 찾음(확인 전)·디버프 띠 발행·나타나면 찾기 0."""
    import logging

    from mabinogi_addon.ui.autofind_v2_section import AutofindV2Section
    caplog.set_level(logging.INFO, logger="mabinogi_addon.ui.autofind_v2_controller")
    c, clock, cap, fnd, *_ = _second_run_without_boss(app, isolated)
    _run(c, clock, 120)
    for key in ("boss", "halo_timer"):
        it = c.engine.items[key]
        assert it.status == "found" and it.pending and it.label() == "찾음 · 지난 자리(나타나면 확인)"
    assert autofind_regions.region_for("boss", None) == dict(zip("xywh", BOSS))
    assert autofind_regions.region_for("debuff", None) == dict(zip("xywh", ctl.debuff_from_boss(BOSS)))
    assert autofind_regions.region_for("halo_timer", None) == dict(zip("xywh", HALO))
    assert "boss" not in fnd.calls and "halo_timer" not in fnd.calls  # 나타나면 찾기 호출 0
    ui_crops = {_ui_crop(c, k) for k in ("skillbar", "stat_bars")}  # 'UI 보이나' 여백 확인(명세 6.1 — 아무것도 안 읽히는 시험)
    assert all(k[2:] == (1920, 1080) or k in ui_crops for k in cap.calls)  # 예상 자리 작은 조각도 안 찍음(전체 화면은 투아림 다시 찾기뿐)
    section = AutofindV2Section(c)
    section.refresh()
    assert "보스바: 찾음 · 지난 자리(나타나면 확인)" in section.items.text()
    autofind_regions.report("boss", True)  # 같은 자리에 보스바가 나타나 읽힘
    assert not c.engine.items["boss"].pending and c.engine.items["boss"].label() == "찾음 · 지난 자리 그대로"
    assert c.engine.items["halo_timer"].pending  # 전투 시간은 아직 확인 전
    autofind_regions.report("boss", True)
    text = [r.getMessage() for r in caplog.records]
    assert sum("지난 자리 확인됨: 보스바" in t for t in text) == 1  # 한 번만


def test_boss_last_spot_moves_after_rare_full_check(app, isolated, caplog):
    """게임 UI 배율이 바뀐 화면(다른 자리) → 5분에 한 번 화면 전체 확인으로 새 자리('자리 바뀜' 한 줄)."""
    import logging
    caplog.set_level(logging.INFO, logger="mabinogi_addon.ui.autofind_v2_controller")
    moved = (640, 50, 640, 34)
    c, clock, cap, fnd, *_ = _second_run_without_boss(app, isolated, boss_now=moved)
    _run(c, clock, 290)
    assert "boss" not in fnd.calls and c.engine.items["boss"].box == BOSS  # 그 전엔 화면 전체 확인 없음
    _run(c, clock, 15)
    assert fnd.calls.count("boss") == 1 and fnd.calls.count("halo_timer") == 1
    it = c.engine.items["boss"]
    assert it.box == moved and not it.pending and it.source == "appear"
    assert autofind_regions.region_for("boss", None) == dict(zip("xywh", moved))
    assert c.engine.items["halo_timer"].pending  # 전투 시간은 화면에 없음 → 지난 자리 그대로(확인 전)
    assert json.loads(isolated.read_text(encoding="utf-8"))["autofindV2"]["last"]["boss"]["box"]["x"] == 640
    text = [r.getMessage() for r in caplog.records]
    assert sum("자리 바뀜: 보스바" in t for t in text) == 1
    _run(c, clock, 300)
    assert fnd.calls.count("boss") == 1 and fnd.calls.count("halo_timer") == 2  # 확인된 보스바는 더 안 봄



def _real_initial(isolated, shot, last_boxes):
    """실제 탐지기·스크린샷으로 처음 찾기 한 번 — (컨트롤러, 탐지기 호출 [(항목, 화면 전체인지)])."""
    raw = json.loads(isolated.read_text(encoding="utf-8"))
    raw["autofindV2"] = {"last": {k: {"box": dict(zip("xywh", map(int, b))), "size": [shot.shape[1], shot.shape[0]]}
                                  for k, b in last_boxes.items()}}
    isolated.write_text(json.dumps(raw), encoding="utf-8")
    h, w = shot.shape[:2]
    clock, calls = Clock(), []
    c = ctl.AutofindV2Controller(Watcher(), None, target_fn=lambda prev: (1, 100, 0, 0, w, h), executor=Inline(),
                                 capture=ShotCapture(shot), clock=clock)
    c.engine.reset(0.0)
    real = c._finders.finders

    def spied():
        def wrap(k, f):
            return lambda frame: calls.append((k, frame.shape[:2] == (h, w))) or f(frame)
        return {k: wrap(k, f) for k, f in real().items()}
    c._finders.finders = spied
    _run(c, clock, 1.0)
    return c, calls


@pytest.mark.parametrize("shot_name", ["image.png", "스크린샷 2026-11-06 013739.png"])  # 1080·2560
def test_real_last_positions_kept_without_full_search(app, isolated, shot_name):
    """QA 536ec7c: 단축바·체력바(·버프)는 지난 자리 딱 맞는 조각에선 탐지기가 못 찾아 매번 화면 전체 탐지(0.1초씩)로 넘어갔다.
    이제 둘레 여백 조각에서 찾아 4px 이내면 '지난 자리 그대로' — 화면 전체 탐지 호출 없음."""
    from mabinogi_addon import image_io
    import cv2
    shot = image_io.imread(f"tests/data/{shot_name}", cv2.IMREAD_COLOR)
    finders = ctl.Finders().finders()
    boxes = {k: finders[k](shot) for k in ("skillbar", "stat_bars", "buff")}
    c, calls = _real_initial(isolated, shot, boxes)
    try:
        assert c.engine.phase == "stable"
        for key in ("skillbar", "stat_bars", "buff"):
            it = c.engine.items[key]
            assert (it.status, it.source) == ("found", "last"), key
            assert it.label() == "찾음 · 지난 자리 그대로"
            assert (key, True) not in calls, key  # 화면 전체 탐지 없음
    finally:
        c.shutdown()


def test_real_last_position_moved_uses_new_spot(app, isolated):
    """지난 자리와 자리가 달라졌으면(여기선 지난 자리를 20px 옮겨 둠) 지금 찾은 새 자리 — '지난 자리 그대로'가 아님."""
    from mabinogi_addon import image_io
    import cv2
    shot = image_io.imread("tests/data/image.png", cv2.IMREAD_COLOR)
    real = ctl.Finders().finders()["skillbar"](shot)
    moved = (real[0] + 20, real[1] - 20, real[2], real[3])
    c, calls = _real_initial(isolated, shot, {"skillbar": moved})
    try:
        it = c.engine.items["skillbar"]
        assert it.status == "found" and it.source == "search" and it.box == tuple(real)
        assert ("skillbar", True) not in calls  # 여백 조각 안에 있어 화면 전체 탐지 없음
    finally:
        c.shutdown()


def test_fixed_from_previous_run_and_auto_return(app):
    """직접 지정 고정은 다음 실행에도 이기고, `자동으로 돌아가기`면 바로 다시 찾아 자동 자리로."""
    autofind_regions.reset_for_tests()
    autofind_regions.activate(True, ["buff"])
    autofind_regions.set_use_values({k: True for k in autofind_regions.USE_KEYS})
    c, clock, cap, fnd, *_ = _make(app)
    c.start()
    c.engine.reset(0.0)
    for key in autofind_regions.user_keys():
        c.engine.user_override(key)
    _run(c, clock, 1.5)
    saved = {"x": 1, "y": 2, "w": 3, "h": 4}
    assert c.engine.items["buff"].user and autofind_regions.region_for("buff", saved) == saved
    autofind_regions.auto_return("buff")
    assert not c.engine.items["buff"].user
    _run(c, clock, 2.0)  # 'UI 보이나' 확인 한 번 + 다시 찾기(새 자리는 시험 중에도 그 자리로 읽어 봄)
    assert autofind_regions.region_for("buff", saved) == {"x": 1700, "y": 200, "w": 30, "h": 300}
    c.shutdown()
