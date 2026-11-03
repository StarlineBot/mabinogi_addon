"""앱 CPU 절감 1단계 — 기능별 처리 시간 계측(측정만, 동작 변경 없음)."""
from __future__ import annotations

import logging
import threading
import time

import pytest

from mabinogi_addon import perf_meter


@pytest.fixture(autouse=True)
def clean():
    perf_meter.take()
    yield
    perf_meter.take()


def test_measure_accumulates_by_feature_and_thread():
    with perf_meter.measure("버프"):
        time.sleep(0.01)
    with perf_meter.measure("버프"):
        pass
    def worker():
        with perf_meter.measure("버프"):
            time.sleep(0.005)
    t = threading.Thread(target=worker)
    t.start()
    t.join()
    snap = perf_meter.take()
    assert snap[("버프", "화면")][2] == 2 and snap[("버프", "화면")][0] >= 0.009
    assert snap[("버프", "작업")][2] == 1
    assert perf_meter.take() == {}  # 꺼내면 비움


def test_exception_inside_is_still_measured_and_propagates():
    with pytest.raises(ValueError):
        with perf_meter.measure("보스"):
            raise ValueError
    assert perf_meter.take()[("보스", "화면")][2] == 1


def test_line_format_sorted_by_time():
    snap = {("보스", "화면"): [0.6, 0.5, 200], ("버프", "작업"): [1.32, 1.2, 300]}
    line = perf_meter.format_line(snap, 60.0, 3.0, cores=8)
    assert line == ("기능별 처리 시간(60초, 앱 CPU 0.6% · 코어 8개 · 코어 1개 기준 50ms/s): "
                    "버프 22.0ms/s CPU 20.0(작업·300회) · 보스 10.0ms/s CPU 8.3(화면·200회)")
    assert perf_meter.format_line({}, 60.0, 1.0) is None


def test_reporter_logs_one_line_per_period(caplog):
    caplog.set_level(logging.INFO, logger="mabinogi_addon.perf")
    r = perf_meter.Reporter()
    r.start()
    try:
        assert r.report() is None  # 기록 없으면 남기지 않음
        with perf_meter.measure("도르카"):
            pass
        line = r.report()
        assert line and "도르카" in line and caplog.records[-1].getMessage() == line
    finally:
        r.stop()


def test_every_listed_feature_tick_is_measured():
    """측정 대상 틱이 모두 감싸져 있는지(동작은 원래 함수 그대로)."""
    from mabinogi_addon.ui import (blackbox_controller, boss_tab, cursor_overlay, dorcha_search, dorcha_tab,
                                   halo_capture_section, mirror_manager, optimization_controller, skillbar_tab,
                                   stat_bars_tab, tuarim_tab)
    wrapped = [boss_tab.BossTab._safe_tick, halo_capture_section.HaloCaptureSection._tick,
               tuarim_tab.TuarimTab._tick_enabled, dorcha_tab.DorchaTab._tick, dorcha_tab.DorchaTab._compute_tick,
               stat_bars_tab.StatBarsTab._tick, skillbar_tab.SkillbarTab._tick, mirror_manager.MirrorManager._tick,
               blackbox_controller.BlackboxController._tick, optimization_controller.OptimizationController._tick,
               cursor_overlay.CursorFx.tick, dorcha_search.DorchaSearch.run]
    assert all(hasattr(fn, "__wrapped__") for fn in wrapped)


def test_buff_and_debuff_workers_report_their_own_names():
    from mabinogi_addon.ui.buff_controller import _TrackWorker

    class Source:
        def grab(self):
            return None

    class Watcher:
        def is_game_active(self):
            return True

        def is_self_active(self):
            return False

    for name in ("버프", "디버프"):
        w = _TrackWorker(Source(), object(), Watcher(), name=name)
        w._running = True
        w._sleep = lambda active=True, w=w: setattr(w, "_running", False)
        w.run()
        w.deleteLater()
    snap = perf_meter.take()
    assert {k[0] for k in snap} == {"버프", "디버프"}
