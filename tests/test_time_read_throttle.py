"""시간 판독 throttle 회귀 테스트.

아이콘 존재는 매 틱 보되, 시간 판독은 등장 직후 + _TIME_READ_GAP마다 +
임박 근처(알림기준+margin)엔 매 틱. 내부 시계가 그 사이를 카운트다운·알림한다.
"""

import os

import cv2
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.catalog import build_templates, load_catalog
from mabinogi_addon.tracker import BuffEngine

_SHOT = "tests/data/스크린샷 2026-10-06 224732.png"


def _region():
    if not os.path.exists(_SHOT):
        pytest.skip("스크린샷 없음")
    img = image_io.imread(_SHOT, cv2.IMREAD_COLOR)
    if img is None or img.shape[0] < 775:
        pytest.skip("해상도 예상과 다름")
    return img[395:775, 0:380]


def _engine():
    cat = load_catalog()
    return BuffEngine(
        build_templates(cat), [b.id for b in cat], appear_frames=1
    )


def _count_reads(eng, monkeypatch):
    calls = {"n": 0}
    orig = eng._read_row_time

    def _counting(region, y):
        calls["n"] += 1
        return orig(region, y)

    monkeypatch.setattr(eng, "_read_row_time", _counting)
    return calls


def test_far_from_threshold_throttles_reads(monkeypatch):
    region = _region()
    eng = _engine()
    eng.tick(region, now=0.0)  # 등장 → 판독(여기선 카운트 전)
    calls = _count_reads(eng, monkeypatch)
    gap = eng._TIME_READ_GAP
    # vivace는 121초(기준 30초에서 멀다) → _TIME_READ_GAP 간격에만 판독
    eng.tick(region, now=gap * 0.3)
    eng.tick(region, now=gap * 0.6)
    assert calls["n"] == 0  # 간격 안 지남 → 판독 생략
    eng.tick(region, now=gap + 0.1)
    assert calls["n"] >= 1  # 간격 경과 → 재판독


def test_near_threshold_reads_every_tick(monkeypatch):
    region = _region()
    eng = _engine()
    eng.tick(region, now=0.0)
    # 알림 기준을 크게 줘 vivace(121초)를 '임박 근처'로 만든다
    eng.set_alert_before({"vivace": 200})
    calls = _count_reads(eng, monkeypatch)
    eng.tick(region, now=0.1)
    eng.tick(region, now=0.2)
    eng.tick(region, now=0.3)
    assert calls["n"] >= 3  # 임박 근처 → 매 틱 판독(연장 즉시 반영)


def test_newly_appeared_buff_is_read(monkeypatch):
    region = _region()
    eng = _engine()
    calls = _count_reads(eng, monkeypatch)
    eng.tick(region, now=0.0)  # 첫 등장
    assert calls["n"] >= 1  # 등장 직후엔 반드시 판독(시계 시드)


# ---- 종료(종료된 버프 빠른 해제) vs 깜빡임(종료임박) 구분 ----
def test_flicker_kept_but_termination_released(monkeypatch):
    from mabinogi_addon.tracker import engine as engine_mod

    class _Det:
        def __init__(self, bid, y=0):
            self.buff_id = bid
            self.y = y

    region = _region()
    eng = _engine()  # appear_frames=1

    # 1) vivace 감지 + 시간 50 → ACTIVE(시계=50)
    monkeypatch.setattr(engine_mod, "detect_buffs", lambda *a, **k: [_Det("vivace")])
    monkeypatch.setattr(eng, "_read_row_time", lambda region, y: 50.0)
    eng.tick(region, now=0.0)

    # 2) 아이콘 미검출이지만 그 행 시간이 시계와 일치(≈49.9) → 살아있음(유지)
    monkeypatch.setattr(engine_mod, "detect_buffs", lambda *a, **k: [])
    monkeypatch.setattr(eng, "_read_row_time", lambda region, y: 49.9)
    res_keep = eng.tick(region, now=0.1)
    assert any(e.buff_id == "vivace" for e in res_keep.entries)  # 깜빡임 → 유지

    # 3) 아이콘 미검출 + 그 행 시간이 시계와 불일치(다른 버프가 올라옴) → 0.4초 후 해제
    monkeypatch.setattr(eng, "_read_row_time", lambda region, y: 5.0)
    eng.tick(region, now=0.2)  # 불일치 → 미감지 누적 시작
    res_gone = eng.tick(region, now=0.7)  # 0.5초 미감지(>0.4) → 해제
    assert not any(e.buff_id == "vivace" for e in res_gone.entries)
