"""DebuffEngine: '아직 안 걸린 디버프만 표시' + 안정화(숨김 즉시 / 재표시 지연)."""

import numpy as np

from mabinogi_addon.tracker.debuff_engine import DebuffEngine


def _templates():
    rng = np.random.default_rng(0)
    a = rng.integers(0, 255, (10, 10, 3), dtype=np.uint8)
    b = rng.integers(0, 255, (10, 10, 3), dtype=np.uint8)
    return {"a": a, "b": b}


def _region_with(template):
    region = np.zeros((24, 60, 3), np.uint8)
    region[7:17, 20:30] = template
    return region


def _shown(result):
    return [e.buff_id for e in result.entries]


def test_detected_debuff_hidden_immediately():
    tpl = _templates()
    eng = DebuffEngine(tpl, ["a", "b"])
    # a가 보스에 걸려있음(감지) → 'a'는 즉시 오버레이에서 빠지고 'b'만 남음
    assert _shown(eng.tick(_region_with(tpl["a"]), now=0.0)) == ["b"]


def test_reappear_only_after_debounce():
    tpl = _templates()
    eng = DebuffEngine(tpl, ["a", "b"], reappear_sec=1.5)
    eng.tick(_region_with(tpl["a"]), now=0.0)  # a 숨김
    empty = np.zeros((24, 60, 3), np.uint8)
    assert _shown(eng.tick(empty, now=0.5)) == ["b"]  # 아직 재표시 안 함
    assert _shown(eng.tick(empty, now=2.1)) == ["a", "b"]  # 1.5초 경과 → 재표시


def test_redetect_hides_again_immediately():
    tpl = _templates()
    eng = DebuffEngine(tpl, ["a", "b"], reappear_sec=1.5)
    empty = np.zeros((24, 60, 3), np.uint8)
    eng.tick(empty, now=0.0)  # 둘 다 표시
    assert _shown(eng.tick(_region_with(tpl["b"]), now=0.2)) == ["a"]  # b 재감지→숨김


def test_order_and_no_duration_no_alert():
    tpl = _templates()
    eng = DebuffEngine(tpl, ["b", "a"])
    empty = np.zeros((24, 60, 3), np.uint8)
    res = eng.tick(empty, now=0.0)
    assert _shown(res) == ["b", "a"]  # 등록 순서 유지
    assert all(e.remaining is None and not e.alerting for e in res.entries)
    assert res.alerts == []


def test_set_order_live():
    tpl = _templates()
    eng = DebuffEngine(tpl, ["a", "b"])
    empty = np.zeros((24, 60, 3), np.uint8)
    eng.set_order(["b", "a"])
    assert _shown(eng.tick(empty, now=0.0)) == ["b", "a"]
