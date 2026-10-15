"""Controlled duration-addition probes; OCR and Windows audio are not replayed."""

import numpy as np
import pytest

from mabinogi_addon.tracker.engine import BuffEngine


@pytest.fixture
def pipeline(monkeypatch):
    template = np.random.default_rng(7).integers(0, 256, (16, 16, 3), dtype=np.uint8)
    region = np.zeros((32, 64, 3), dtype=np.uint8)
    region[:16, :16] = template
    engine = BuffEngine({"qa": template}, ["qa"], icon_column=(0, 16),
                        appear_frames=1, alert_before={"qa": 30},
                        alert_before2={"qa": 10})
    reading = [40.0]
    monkeypatch.setattr(engine, "_read_row_time", lambda *_: reading[0])
    trace = []

    def tick(now, value):
        reading[0] = value
        result = engine.tick(region, now=now)
        machine = engine._machines["qa"]
        trace.append({"now": now, "supplied_reading": value,
                      "remaining": machine.remaining(now),
                      "pending": machine._pending,
                      "alerts": result.alerts, "alerts2": result.alerts2})
        return result

    assert not tick(0.0, 40).alerts
    assert not tick(0.2, 39.8).alerts
    return tick, trace


def test_add_duration_after_first_alert_is_silent_until_next_threshold(pipeline):
    tick, trace = pipeline
    assert tick(10.0, 30).alerts == ["qa"]
    for now, value in [(12, 88), (12.05, 87.95), (12.1, 87.9)]:
        result = tick(now, value)
        assert not result.alerts and not result.alerts2, trace
    assert tick(70, 30).alerts == ["qa"]
    assert not tick(70.05, 29.95).alerts


def test_previous_minute_loss_defense_does_not_immediately_refire(pipeline):
    tick, trace = pipeline
    assert tick(10, 30).alerts == ["qa"]
    for now, value in [(12, 28), (12.05, 30), (12.1, 30),
                       (12.15, 29.95), (12.2, 90), (12.25, 89.95)]:
        result = tick(now, value)
        assert not result.alerts and not result.alerts2, trace


@pytest.mark.parametrize("boundary", ["first", "second"])
def test_valid_extension_readings_at_boundary_should_not_emit_old_clock_alert(pipeline, boundary):
    tick, trace = pipeline
    if boundary == "second":
        assert tick(10, 30).alerts == ["qa"]
        assert not tick(29.8, 10.2).alerts2
        first = tick(30, 70)  # Existing duration +60s, no disappearance or recast.
        confirmed = tick(30.05, 69.95)
    else:
        first = tick(10, 90)
        confirmed = tick(10.05, 89.95)
    assert not first.alerts and not first.alerts2, trace
    assert not confirmed.alerts and not confirmed.alerts2, trace
