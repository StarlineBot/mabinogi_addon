"""시간 판독 throttle 회귀 테스트.

아이콘 존재는 매 틱 보되, 시간 판독은 등장 직후 + _TIME_READ_GAP(3초)마다 +
임박 근처(알림기준+margin)엔 매 틱. 내부 시계가 그 사이를 카운트다운·알림한다.
"""

import os

import cv2
import pytest

from mabinogi_addon.catalog import build_templates, load_catalog
from mabinogi_addon.tracker import BuffEngine

_SHOT = "tests/data/스크린샷 2026-10-06 224732.png"


def _region():
    if not os.path.exists(_SHOT):
        pytest.skip("스크린샷 없음")
    img = cv2.imread(_SHOT, cv2.IMREAD_COLOR)
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
    # vivace는 121초(기준 30초에서 멀다) → 3초 간격에만 판독
    eng.tick(region, now=0.5)
    eng.tick(region, now=1.0)
    eng.tick(region, now=2.0)
    assert calls["n"] == 0  # 3초 안 지남 → 판독 생략
    eng.tick(region, now=3.1)
    assert calls["n"] >= 1  # 3초 경과 → 재판독


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
