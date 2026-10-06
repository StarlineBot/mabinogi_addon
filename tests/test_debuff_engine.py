"""DebuffEngine: '아직 안 걸린 디버프만 표시' + 안정화(숨김 즉시 / 재표시 지연).

매칭은 영역을 고정 높이로 정규화한 뒤 수행하므로, 테스트는 '영역 높이 ≈ 아이콘 높이'
(사용자가 디버프 줄에 타이트하게 영역을 잡은 상태)를 가정한다.
"""

import cv2
import numpy as np

from mabinogi_addon.tracker.debuff_engine import DebuffEngine

_H = 18  # 아이콘/영역 높이


def _templates():
    rng = np.random.default_rng(0)
    a = rng.integers(0, 255, (_H, _H, 3), dtype=np.uint8)
    b = rng.integers(0, 255, (_H, _H, 3), dtype=np.uint8)
    return {"a": a, "b": b}


def _region_with(template):
    region = np.zeros((_H, 90, 3), np.uint8)
    region[:, 20 : 20 + template.shape[1]] = template  # 줄 높이를 꽉 채워 배치
    return region


def _empty():
    return np.zeros((_H, 90, 3), np.uint8)


def _shown(result):
    return [e.buff_id for e in result.entries]


def test_detected_debuff_hidden_immediately():
    tpl = _templates()
    eng = DebuffEngine(tpl, ["a", "b"])
    assert _shown(eng.tick(_region_with(tpl["a"]), now=0.0)) == ["b"]


def test_reappear_only_after_debounce():
    tpl = _templates()
    eng = DebuffEngine(tpl, ["a", "b"], reappear_sec=1.5)
    eng.tick(_region_with(tpl["a"]), now=0.0)  # a 숨김
    assert _shown(eng.tick(_empty(), now=0.5)) == ["b"]  # 아직 재표시 안 함
    assert _shown(eng.tick(_empty(), now=2.1)) == ["a", "b"]  # 1.5초 경과 → 재표시


def test_redetect_hides_again_immediately():
    tpl = _templates()
    eng = DebuffEngine(tpl, ["a", "b"], reappear_sec=1.5)
    eng.tick(_empty(), now=0.0)  # 둘 다 표시
    assert _shown(eng.tick(_region_with(tpl["b"]), now=0.2)) == ["a"]


def test_order_and_no_duration_no_alert():
    tpl = _templates()
    eng = DebuffEngine(tpl, ["b", "a"])
    res = eng.tick(_empty(), now=0.0)
    assert _shown(res) == ["b", "a"]  # 등록 순서 유지
    assert all(e.remaining is None and not e.alerting for e in res.entries)
    assert res.alerts == []


def test_detects_when_region_drawn_a_bit_loose():
    # 영역을 아이콘보다 약간 크게(여유 있게) 잡은 경우: 정규화 후 0.75 변형이 잡는다.
    tpl = _templates()  # 18px 아이콘
    region = np.zeros((24, 90, 3), np.uint8)  # 줄보다 살짝 큰 영역
    region[3:21, 20:38] = tpl["a"]  # 18px 아이콘을 여유 있는 영역에 배치
    eng = DebuffEngine(tpl, ["a", "b"])
    assert _shown(eng.tick(region, now=0.0)) == ["b"]  # a 감지 → 숨김


def test_set_order_live():
    tpl = _templates()
    eng = DebuffEngine(tpl, ["a", "b"])
    eng.set_order(["b", "a"])
    assert _shown(eng.tick(_empty(), now=0.0)) == ["b", "a"]
