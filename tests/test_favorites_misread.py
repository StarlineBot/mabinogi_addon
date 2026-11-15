"""0.49.2 즐겨찾기 칸 오인(사용자 제보 11-15: 즐겨찾기를 쓰고 나서부터 마나 피어스·어둠의 에르그 거짓 '사라짐' 경고,
안 건 피닉스가 '걸려 있음').

재현 조건: 사용자 영역 304×1279, 구분선 439 → 2560×1440 화면 y=161부터(tests/data 2560 즐겨찾기 장면에 같은 영역).
A. 줄 맞춤이 구분선 위 띠 전체(상태목록창 위 게임 장면까지)를 0.70으로 훑음 → 225848 화면 y=188에 피닉스 '켜짐'.
B. 켜짐을 이름 글자색만으로 봄 → 꺼진 '정화의 고동'을 0.70~0.73으로 마나 피어스로 기억한 줄이, 정화의 고동이 켜지면 '마나 피어스 켜짐'.
"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.catalog import available_catalog, build_templates
from mabinogi_addon.detect import detect_buffs
from mabinogi_addon.detect.favorites import FavoritesReader
from mabinogi_addon.detect.status_panel import anchor_template, locate_status_region
from mabinogi_addon.tracker.engine import BuffEngine

DATA = Path(__file__).parent / "data"
USER_TOP = 161  # 사용자 영역 위 끝(화면 y)


@pytest.fixture(scope="module")
def catalog():
    return build_templates(available_catalog())


def _user_region(stamp):
    image = image_io.imread(next(DATA.glob(f"스크린샷 *{stamp}.png")), cv2.IMREAD_COLOR)
    x, _y, w, _h = locate_status_region(image, anchor_template())
    return np.ascontiguousarray(image[USER_TOP:, x:x + w])


def _reader(region, catalog, frames=8):
    reader = FavoritesReader(catalog, (0, 50))
    list_ys = [d.y for d in detect_buffs(region, catalog, (0, 50))]
    for _ in range(frames):
        reader.update(region, list_ys)
    return reader


@pytest.mark.parametrize("stamp", ["001307", "213313"])
def test_lit_purify_row_is_not_mana_pierce(stamp, catalog):
    """정화의 고동이 켜진 장면: 예전엔 그 줄을 mana_pierce@412 켜짐으로 읽었다(목록에 진짜 마나 피어스가 없으면 거짓 켜짐·사라짐)."""
    reader = _reader(_user_region(stamp), catalog)
    assert reader.separator is not None
    assert not reader.on.get("mana_pierce")


def test_scene_above_panel_is_not_a_favorite(catalog):
    """225848: 상태목록창(화면 y≈420~) 위 게임 장면의 화면 y=188을 피닉스 즐겨찾기 '켜짐'으로 읽었다."""
    reader = _reader(_user_region("225848"), catalog)
    assert reader.separator is not None
    assert "flame_of_resurrection" not in reader.rows
    assert all(row.y + USER_TOP >= 400 for row in reader.rows.values())  # 줄은 모두 창 안


def test_user_warning_picture_has_no_lit_mana_pierce(catalog):
    """사용자 '사라짐' 경고 순간 그림(정화의 고동 줄을 0.721로 마나 피어스로 맞춤)."""
    region = image_io.imread(DATA / "buff_gone_20261115_112824_mana_pierce_fav_purify.webp", cv2.IMREAD_COLOR)
    reader = _reader(np.ascontiguousarray(region), catalog)
    assert not reader.on.get("mana_pierce")


@pytest.mark.parametrize("stamp", ["001307", "213313", "225848"])
def test_real_mana_pierce_in_list_still_shown(stamp, catalog):
    """목록에 진짜 마나 피어스가 있는 장면은 그대로 잡히고, 피닉스는 안 보인다."""
    engine = BuffEngine(catalog, list(catalog), anchor_id="premium_battle", favorites=True)
    region = _user_region(stamp)
    for i in range(8):
        result = engine.tick(region, i * 0.05)
    shown = {entry.buff_id for entry in result.entries}
    assert "mana_pierce" in shown
    assert "flame_of_resurrection" not in shown


def test_lit_row_needs_list_level_icon_score(catalog):
    """글자가 흰색이어도 그 순간 아이콘 점수가 0.80 아래면 켜짐이 아니다(꺼진 줄 위치 기억 0.70과 별개)."""
    from mabinogi_addon.detect import favorites as fav
    reader = _reader(_user_region("001307"), catalog)
    row = reader.rows["mana_pierce"]
    gray = cv2.cvtColor(_user_region("001307"), cv2.COLOR_BGR2GRAY)
    assert fav.FAV_MATCH_THRESHOLD <= reader._row_score(gray, "mana_pierce", row) < fav.ON_THRESHOLD


def test_repeated_remap_log_is_suppressed(caplog):
    """같은 두 결과가 번갈아 나오면(줄 하나가 들어왔다 빠졌다) 수 분간 0.3~0.5초마다 찍히던 로그 — 같은 결과는 한 번만."""
    import logging
    reader = FavoritesReader({}, (0, 50))
    with caplog.at_level(logging.INFO, logger="mabinogi_addon.favorites"):
        for i in range(200):
            reader._frame = i * 5
            reader._log_remap("줄 확인", "a@10, b@34" if i % 2 else "a@10")
    lines = [r.getMessage() for r in caplog.records if "다시 맞춤" in r.getMessage()]
    # 1000프레임(0.3초 주기면 약 5분) 동안 200줄 → 같은 결과는 LOG_REPEAT_FRAMES(240)마다 한 번씩만: 두 결과 × 5 = 10줄
    assert 2 <= len(lines) <= 2 * (1000 // FavoritesReader.LOG_REPEAT_FRAMES + 1), lines
    assert any("생략" in line for line in lines)
