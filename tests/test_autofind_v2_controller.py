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
        def make(k):
            def run(frame):
                self.calls.append(k)
                if k in ("skillbar", "stat_bars") and not self.ui:
                    return None
                return self.boxes.get(k)
            return run
        return {k: make(k) for k in ("skillbar", "stat_bars", "buff", "resources", "boss", "halo_timer")}

    ui = True  # 게임 UI(단축바·체력바)가 보이나 — False면 로딩·로그인 화면

    def readers(self):
        def read(key):
            return lambda crop: self.ui if key in ("skillbar", "stat_bars") else True
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
    assert autofind_regions.region_for("tuarim", {"x": 9, "y": 9, "w": 9, "h": 9}) is None  # 못 찾음 → 쉰다
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
    assert fnd.calls == ["buff"]


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


def test_loading_screen_waits_10s(app):
    fnd = Finders(boxes={})
    c, clock, cap, *_ = _make(app, finders=fnd)
    _run(c, clock, 1.0)
    assert len(cap.calls) == 1 and c.engine.phase == "waiting_ui"
    _run(c, clock, 9.5)  # 결과는 다음 틱(t=1)에 반영 → 다시 확인은 t=11
    assert len(cap.calls) == 1
    _run(c, clock, 0.5)
    assert len(cap.calls) == 2


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
