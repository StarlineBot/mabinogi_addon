"""0.30.1 Alt+Tab 뒤 '연장' 알림 반복(사용자 제보): 4K에서 시간 글자가 7px가 아니라 8px·9px 굵게(image55·213520 등, 한 장 안에서도 섞임)로 그려졌다.

1) 숫자를 못 읽고 단위만 맞으면 예전엔 0초 → 시간 있는 버프가 전부 '곧 끝남' 알림. 이제 그 줄은 읽지 못함(None).
2) 4K 화면에서 뜬 글자 세트(uhd, 같은 숫자의 다른 모양은 변형으로)로 화면과 같은 값을 읽는다.
   세트에 없는 숫자(8)나 설명 못 한 잉크가 있으면 틀린 값 대신 None.
3) 고정된 세트로 계속 못 읽으면 다시 고른다(중간에 글자 크기가 바뀌는 경우).
"""
import cv2
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.catalog import build_templates, load_catalog
from mabinogi_addon.detect import time_reader as tr
from mabinogi_addon.detect.binarize import binarize
from mabinogi_addon.tracker import BuffEngine

IMAGE55 = ("tests/data/image55.png", (3546, 392, 293, 1763))
SHOT_213520 = ("tests/data/mabinogi_2026_10_30_213520.png", (3546, 396, 294, 1764))
# 버프 id → 화면 시간(초)
_BOX = (3546, 396, 294, 1764)
EXPECTED = {
    IMAGE55: {"han_adrenaline": 82, "overture_of_the_battlefield": 333, "march": 405, "sharp": 200,
              "voice_of_vitality": 217, "melee_attack": 1479},
    SHOT_213520: {"han_adrenaline": 130, "overture_of_the_battlefield": 22, "march": 90, "sharp": 249,
                  "melee_attack": 416},
    ("tests/data/mabinogi_2026_10_30_213927.png", _BOX): {"melee_attack": 170, "sharp": 2},  # 빨간 2초
    ("tests/data/mabinogi_2026_10_30_213942.png", _BOX): {"han_adrenaline": 176, "melee_attack": 154},
    ("tests/data/mabinogi_2026_10_30_214016.png", _BOX): {"han_adrenaline": 142, "overture_of_the_battlefield": 83,
                                                         "melee_attack": 120},
    # 214051·214648은 세트를 뜰 때 쓰지 않은 장(처음 보는 4K 화면에서도 읽힘)
    ("tests/data/mabinogi_2026_10_30_214051.png", _BOX): {"han_adrenaline": 179, "overture_of_the_battlefield": 80,
                                                         "melee_attack": 85, "sharp": 289},
    ("tests/data/mabinogi_2026_10_30_214648.png", (3546, 300, 294, 1860)): {"overture_of_the_battlefield": 69,
                                                                           "sharp": 253, "star": 0},  # 빨간 0초
}


def _region(shot):
    path, (x, y, w, h) = shot
    frame = image_io.imread(path, cv2.IMREAD_COLOR)
    return frame[y:y + h, x:x + w]


def _engine():
    cat = load_catalog()
    return BuffEngine(build_templates(cat), [b.id for b in cat], appear_frames=1)


def _ticks(engine, region, count=4):
    result = None
    for step in range(count):
        result = engine.tick(region, now=step * 0.001)  # 시간은 거의 안 흐르게(판독값 그대로 비교)
    return {e.buff_id: e for e in result.entries}


@pytest.mark.parametrize("shot", list(EXPECTED), ids=lambda shot: shot[0].rsplit("/", 1)[-1][:-4])
def test_4k_times_read_as_shown_and_never_zero(shot):
    entries = _ticks(_engine(), _region(shot))
    for bid, seconds in EXPECTED[shot].items():
        assert entries[bid].remaining == pytest.approx(seconds, abs=0.5), bid
    # 시간이 있는 버프는 모두 화면 값 그대로(예전엔 숫자를 못 읽어 0초 → 거짓 알림). 못 읽은 줄은 시간 없음(None).
    timed = {bid: e.remaining for bid, e in entries.items() if e.remaining is not None}
    assert set(timed) <= set(EXPECTED[shot]) | {"penet"}  # penet = 물리 공격력 증가와 같은 줄
    assert not any(e.alerting for e in entries.values() if e.remaining is not None and e.remaining > 60)


def test_unit_without_number_is_unreadable_not_zero():
    assert tr._parse(["bun", "2", "0", "cho"]) is None
    assert tr._parse(["3", "bun", "cho"]) is None
    assert tr._parse(["3", "bun", "2", "0", "cho"]) == 200
    # image55 행진곡 줄: 기본 세트는 숫자를 못 읽고 '분'·'초'만 맞는다 → 예전 (0, 0.79), 이제 None
    strip = _region(IMAGE55)[588:616, 150:]
    assert tr.read_time(strip) is None
    assert tr.read_time(strip, set_name="uhd") == 405


def test_missing_digit_in_set_is_unreadable_not_wrong():
    """세트에 없는 글자가 섞이면(설명 못 한 잉크) 틀린 값 대신 None: '1분22초'에서 '1'을 지우면 1분이 빠진 '22초'로 읽지 않는다."""
    region = _region(IMAGE55)
    strip = binarize(region[468:496, 150:])
    assert tr._read(strip, tr._SETS["uhd"], tr.GLYPH_THRESHOLD)[0] == 82
    no_one = {key: image for key, image in tr._SETS["uhd"].items() if tr._label(key) != "1"}
    assert tr._read(strip, no_one, tr.GLYPH_THRESHOLD)[0] is None


def test_locked_set_reselects_when_glyph_size_changes():
    """7px(기본 세트)로 고정된 뒤 화면이 8px로 바뀌면, 연속 실패 끝에 다시 골라 uhd로 읽는다."""
    engine = _engine()
    engine._time_set = "default"
    region = _region(IMAGE55)
    entries = {}
    for step in range(30):
        entries = {e.buff_id: e for e in engine.tick(region, now=step * 1.1).entries}
        if engine._time_set == "uhd":
            break
    assert engine._time_set == "uhd"
    assert not entries["march"].alerting


def test_4k_sets_do_not_read_native_7px_screen():
    """4K 세트가 보통 화면(7px)에 섞여 들어오지 않는다: 기본 세트가 읽는 화면에서 4K 세트 값은 없다."""
    frame = image_io.imread("tests/data/스크린샷 2026-10-06 224732.png", cv2.IMREAD_COLOR)
    region = frame[395:775, 0:380]
    engine = _engine()
    entries = {}
    for step in range(6):  # 워밍업(세트별 신뢰도 누적) 뒤 기본 세트로 고정
        entries = {e.buff_id: e for e in engine.tick(region, now=step * 1.1).entries}
    assert engine._time_set == "default"
    assert 110 <= entries["vivace"].remaining <= 121  # 같은 화면 반복(121)과 내부 시계 사이 — 4K 세트 값이 끼지 않음
