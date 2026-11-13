"""버프 사라짐 경고 — 포커스 복귀 유예(0.47.1, 사용자 결정 11-13)와 확정 진단 로그·PNG."""
import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon.catalog import BuffDef
from mabinogi_addon.detect.buff_detector import Detection
from mabinogi_addon.tracker import engine as engine_mod
from mabinogi_addon.tracker.engine import BuffEngine, OverlayEntry
from mabinogi_addon.tracker.gone_watch import GoneWatch
from mabinogi_addon.ui import buff_controller as bc_mod
from mabinogi_addon.ui.buff_controller import BuffController
from mabinogi_addon.ui.overlay import BuffOverlay

_ICON = Path("src/mabinogi_addon/assets/buff/icon")
W = {"pierce"}


# ---- 확정 시각 규칙(순수) ----

def _run(events, until):
    """events: {시각: ('focus', bool) | ('ids', set)}. 0.1초 틱. 확정 시각 목록을 돌려준다."""
    g = GoneWatch()
    ids = {"pierce"}
    g.update(ids, W, 0.0)
    out, cancels = [], []
    t = 0.0
    while t <= until + 1e-9:
        for kind, value in events.get(round(t, 1), []):
            if kind == "focus":
                g.focus(value, t, W)
            else:
                ids = value
        confirmed, cancelled = g.update(ids, W, t)
        out += [round(t, 1) for _ in confirmed]
        cancels += cancelled
        t = round(t + 0.1, 1)
    return out, cancels


def test_focus_kept_confirms_3s_after_gone():
    assert _run({10.0: [("ids", set())]}, 20)[0] == [13.0]


def test_gone_while_away_confirms_once_5s_after_return():
    out, _ = _run({10.0: [("focus", False)], 12.0: [("ids", set())], 30.0: [("focus", True)]}, 40)
    assert out == [35.0]  # 예전엔 안 울렸다


def test_present_when_left_missing_after_return_counts_from_return():
    """나갈 때 있었고, 안 보는 동안 판정이 동결돼 계속 '있음' → 복귀 첫 틱에 없음 → 복귀 5초에."""
    out, _ = _run({10.0: [("focus", False)], 30.0: [("focus", True), ("ids", set())]}, 40)
    assert out == [35.0]


@pytest.mark.parametrize("gone_after_return,expected", [(1.0, 35.0), (3.0, 36.0)])
def test_gone_shortly_after_return(gone_after_return, expected):
    out, _ = _run({10.0: [("focus", False)], 30.0: [("focus", True)],
                   round(30.0 + gone_after_return, 1): [("ids", set())]}, 45)
    assert out == [expected]


def test_missing_4s_after_return_then_visible_does_not_fire_and_is_logged():
    out, cancels = _run({10.0: [("focus", False)], 30.0: [("focus", True), ("ids", set())],
                         34.0: [("ids", {"pierce"})]}, 45)
    assert out == [] and len(cancels) == 1 and cancels[0][0] == "pierce"


# ---- 컨트롤러: 로그·PNG ----

class FakeEngine:
    def __init__(self):
        self.log_gone_ids = set()
        self.gone_info = {"pierce": {"reason": "미검출 시간 초과", "at": 0.0, "state": "ACTIVE", "remaining": 50.0,
                                     "last_read": 60.0, "last_read_at": 0.0, "last_y": 40}}
        region = np.full((200, 220, 3), 80, np.uint8)
        self.last_diag = {"frame_valid": True, "anchor": True, "detections": [Detection("march", 0.97, 12)],
                          "boundary": None, "region": region, "prev_region": region.copy()}

    def machine_snapshot(self, bid, now):
        return {"state": "ABSENT", "remaining": None, "last_read": None, "last_read_at": None}

    def last_y(self, bid):
        return 40

    def icon_score_at(self, region, bid, y):
        return 0.31


@pytest.fixture
def ctrl(monkeypatch, tmp_path):
    QApplication.instance() or QApplication([])
    clock = {"t": 0.0}
    monkeypatch.setattr(bc_mod.time, "monotonic", lambda: clock["t"])
    played = []
    from mabinogi_addon.ui import notifier
    monkeypatch.setattr(notifier, "play_warn_gone_sound", lambda: played.append(clock["t"]) or True)
    catalog = {"pierce": BuffDef("pierce", "마나 피어스", _ICON / "march.png", None),
               "march": BuffDef("march", "행진곡", _ICON / "march.png", None)}
    c = BuffController(BuffOverlay(), catalog, show_duration={})
    c.set_order(["march", "pierce"])
    c._engine = FakeEngine()
    c.set_warn_gone_ids({"pierce"})
    c.gone_png_dir = tmp_path / "buff-gone"
    return c, clock, played


def _tick(c, clock, t, ids):
    clock["t"] = t
    c._on_updated([OverlayEntry(b, 100.0, False) for b in ids])


def test_alt_tab_return_missing_logs_once_with_png_and_focus_lines(ctrl, caplog):
    c, clock, played = ctrl
    caplog.set_level(logging.INFO, logger="mabinogi_addon.buff_gone")
    assert c._engine.log_gone_ids == {"pierce"}
    _tick(c, clock, 0.0, ["march", "pierce"])
    clock["t"] = 10.0
    c._on_foreground_changed(False, False)
    for t in (10.5, 11.0, 20.0):
        _tick(c, clock, t, ["march", "pierce"])
    clock["t"] = 30.0
    c._on_foreground_changed(True, False)
    for i in range(80):  # 0.1초마다 8초
        _tick(c, clock, round(30.0 + i * 0.1, 1), ["march"])
    assert played == [35.0]
    lines = [r.getMessage() for r in caplog.records]
    assert sum("[포커스] 게임 활성 → 비활성" in m for m in lines) == 1
    assert sum("[포커스] 게임 비활성 → 활성" in m for m in lines) == 1
    confirm = [m for m in lines if m.startswith("[사라짐 확정]")]
    assert len(confirm) == 1 and len(lines) == 3  # 틱마다 로그 없음
    text = confirm[0]
    for part in ("pierce", "복귀 뒤 5.0초", "안 보인 5.0초", "상태=ABSENT", "엔진 사유=미검출 시간 초과",
                 "frame_valid=True", "앵커=True", "march@12:0.97", "구분선 y=없음", "마지막 y=40", "근처 점수=0.31",
                 "220x200", "밝기=80.0", "멈춘 프레임=True"):
        assert part in text, part
    assert len(list((c.gone_png_dir).glob("*.png"))) == 1


def test_png_keeps_latest_10_and_same_buff_logs_every_10s(ctrl, caplog):
    c, clock, _ = ctrl
    caplog.set_level(logging.INFO, logger="mabinogi_addon.buff_gone")
    t = 0.0
    for _ in range(14):  # 4초 간격으로 사라짐 확정 14번
        _tick(c, clock, t, ["march", "pierce"])
        _tick(c, clock, t + 0.1, ["march"])
        _tick(c, clock, t + 3.2, ["march"])
        t += 11.0  # 10초 제한 밖
    pngs = sorted(c.gone_png_dir.glob("*.png"))
    assert len(pngs) == 10
    assert sum(r.getMessage().startswith("[사라짐 확정]") for r in caplog.records) == 14
    caplog.clear()
    for k in range(3):  # 10초 안에 다시 확정 → 로그는 1번만
        _tick(c, clock, t + k * 4, ["march", "pierce"])
        _tick(c, clock, t + k * 4 + 0.1, ["march"])
        _tick(c, clock, t + k * 4 + 3.3, ["march"])
    assert sum(r.getMessage().startswith("[사라짐 확정]") for r in caplog.records) == 1


def test_cancel_within_grace_is_logged(ctrl, caplog):
    c, clock, played = ctrl
    caplog.set_level(logging.INFO, logger="mabinogi_addon.buff_gone")
    _tick(c, clock, 0.0, ["march", "pierce"])
    clock["t"] = 1.0
    c._on_foreground_changed(False, False)
    clock["t"] = 5.0
    c._on_foreground_changed(True, False)
    for i in range(40):
        _tick(c, clock, round(5.0 + i * 0.1, 1), ["march"])  # 복귀 직후 4초 미검출
    _tick(c, clock, 9.1, ["march", "pierce"])  # 다시 보임
    for i in range(50):
        _tick(c, clock, round(9.2 + i * 0.1, 1), ["march", "pierce"])
    assert played == []
    assert any(r.getMessage().startswith("[사라짐 취소] pierce") for r in caplog.records)


# ---- 엔진: ABSENT로 바뀔 때 사유(경고 켠 버프만) ----

def test_engine_logs_absent_reason_only_for_warned(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="mabinogi_addon.tracker.engine")
    templates = {"pierce": np.zeros((16, 16), np.uint8), "other": np.zeros((16, 16), np.uint8)}
    eng = BuffEngine(templates, ["pierce", "other"], show_duration={"pierce": False, "other": False})
    eng.log_gone_ids = {"pierce"}
    seen = [Detection("pierce", 0.95, 40), Detection("other", 0.95, 70)]
    monkeypatch.setattr(engine_mod, "detect_buffs", lambda *a, **k: list(seen))
    region = np.zeros((120, 220, 3), np.uint8)
    for i in range(5):
        eng.tick(region, i * 0.2)
    seen.clear()
    for i in range(5):
        eng.tick(region, 1.0 + i * 0.2)
    lines = [r.getMessage() for r in caplog.records if "[사라짐 사유]" in r.getMessage()]
    assert len(lines) == 1 and lines[0].startswith("[사라짐 사유] pierce: 미검출 시간 초과")
    assert eng.gone_info["pierce"]["state"] == "ACTIVE" and eng.gone_info["pierce"]["last_y"] == 40
    assert eng.last_diag["frame_valid"] is True and eng.last_diag["region"] is region
