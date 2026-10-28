"""즐겨찾기 칸 읽기(기획서 3.1.1) 회귀 — tests/data 실게임 스크린샷.

즐겨찾기 7줄(환생시 체형 유지·미이르의 깃털·푸른 내상·분열된 에너지·현재의 의지·영혼 연결 상태·정화의 고동),
구분선은 2560×1440 기준 y≈598~601. 켜짐/꺼짐 정답은 화면을 확대해 이름 글자색(흰/회색)으로 확인했다.
즐겨찾기 아이콘 템플릿은 켜진 장면(001307의 1번째 줄 등)에서 잘라 쓴다(기본 카탈로그에 없는 버프).
"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from mabinogi_addon.detect import detect_buffs
from mabinogi_addon.detect.favorites import FavoritesReader, find_separators, line_state
from mabinogi_addon.detect.status_panel import anchor_template, locate_status_region
from mabinogi_addon.tracker.engine import BuffEngine

DATA = Path(__file__).parent / "data"
NAMES = ("rebirth", "miir", "blue", "split", "will", "soul", "purify")
TOP = 400  # 상태목록창 맨 위(즐겨찾기 첫 줄 위)부터 지정한 영역 — 2560×1440 스크린샷 공통


def _load(stamp):
    path = next(DATA.glob(f"스크린샷 *{stamp}.png"))
    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)


@pytest.fixture(scope="module")
def templates():
    ref = _load("001307")  # 즐겨찾기 아이콘 열 x=15, 첫 줄 y=429, 줄 간격 24
    favs = {name: ref[429 + 24 * k:445 + 24 * k, 15:31].copy() for k, name in enumerate(NAMES)}
    return {"premium_battle": anchor_template(), **favs}


def _region(stamp, top=TOP):
    image = _load(stamp)
    x, _y, w, _h = locate_status_region(image, anchor_template())
    return np.ascontiguousarray(image[top:, x:x + w])


def _read(region, templates, frames=6):
    reader = FavoritesReader(templates, (0, 50))
    list_ys = [d.y for d in detect_buffs(region, {"p": anchor_template()}, (0, 50))]
    for _ in range(frames):
        reader.update(region, list_ys)
    return reader, list_ys


# 켜진 즐겨찾기(흰 글자) 정답. 나머지 줄은 꺼짐(회색).
LIT = {
    "001307": {"rebirth", "purify"},          # 정화의 고동 1초(빨간 시간)
    "213313": {"rebirth", "blue", "purify"},  # 푸른 내상 27초
    "213335": {"rebirth", "miir", "soul"},    # 영혼 연결 상태 5분 33초
    "000512": {"rebirth", "miir"},
    "175307": {"miir"},
    "233749": set(),                          # 밝은 사막 배경, 모두 꺼짐
    "150822": set(),
    "190909": {"rebirth"},                    # 어두운 맵
}


@pytest.mark.parametrize("stamp", sorted(LIT))
def test_separator_rows_and_lit_favorites(stamp, templates):
    reader, _ = _read(_region(stamp), templates)
    assert 596 <= reader.separator + TOP <= 602
    assert reader.row_count == 7 and set(reader.rows) == set(NAMES)
    assert {name for name, on in reader.on.items() if on} == LIT[stamp]


def test_engine_reports_only_lit_favorites_with_list_times(templates):
    for stamp, expected in (("213313", {"rebirth": None, "blue": 27, "purify": 1}),
                            ("213335", {"rebirth": None, "miir": None, "soul": 333})):
        engine = BuffEngine(templates, list(NAMES), anchor_id="premium_battle", favorites=True)
        region = _region(stamp)
        for i in range(6):
            result = engine.tick(region, 100.0 + i * 0.05)
        assert result.frame_valid
        got = {e.buff_id: None if e.remaining is None else round(e.remaining) for e in result.entries}
        assert got == expected


def test_default_mode_has_no_favorites_reader(templates):
    engine = BuffEngine(templates, list(NAMES), anchor_id="premium_battle")
    assert engine.favorites is None  # 기본은 지금 목록 방식 그대로(0.26.0: 즐겨찾기 칸은 제작자 알파)


def test_separator_found_on_dark_map_and_not_below_panel():
    # 어두운 맵에서도 선이 보이고(190909), 상태목록창 아래 게임 화면의 가로선(142736 퀵바 y≈1387)은 후보여도
    # 그 아래에 목록 버프가 없으니 받아들이지 않는다.
    assert any(596 <= y + TOP <= 602 for y in find_separators(_region("190909")))
    region = _region("142736")
    reader, list_ys = _read(region, {"p": anchor_template()})
    assert 596 <= reader.separator + TOP <= 602
    assert all(not any(ly > y for ly in list_ys) for y in find_separators(region) if y + TOP > 1300)


def test_no_separator_reads_whole_region_as_list(templates):
    region = _region("233749", top=605)  # 예전 방식처럼 목록 맨 위부터 지정(즐겨찾기 칸 밖)
    engine = BuffEngine(templates, list(NAMES), anchor_id="premium_battle", favorites=True)
    plain = BuffEngine(templates, list(NAMES), anchor_id="premium_battle")
    for i in range(6):
        a, b = engine.tick(region, 100.0 + i * 0.05), plain.tick(region, 100.0 + i * 0.05)
    assert engine.favorites.boundary is None
    assert [e.buff_id for e in a.entries] == [e.buff_id for e in b.entries]


def test_dark_frame_keeps_line_and_line_is_forgotten_only_when_really_gone(templates):
    region = _region("233749")
    reader, list_ys = _read(region, templates)
    sep = reader.separator
    dark = (region * 0.04).astype(np.uint8)  # 맵 이동으로 화면이 순간 까매짐
    assert line_state(dark, sep) is None
    for _ in range(10):
        reader.update(dark, list_ys)
    assert reader.separator == sep
    erased = region.copy()  # 즐겨찾기를 모두 해제해 선이 사라짐(밝은 배경)
    erased[sep - 1:sep + 4] = region[sep - 6:sep - 1]
    assert line_state(erased, sep) is False
    for _ in range(FavoritesReader.FORGET_FRAMES - 1):
        reader.update(erased, list_ys)
    assert reader.separator == sep
    reader.update(erased, list_ys)
    assert reader.separator is None


def test_line_moves_only_after_several_frames_when_a_favorite_is_added(templates):
    region = _region("001307")
    reader, list_ys = _read(region, templates)
    sep = reader.separator
    grown = region.copy()  # 즐겨찾기를 하나 늘려 칸이 한 줄(24px) 아래로 늘어남
    grown[sep + 24:] = region[sep:-24]
    grown[sep:sep + 24] = region[sep - 24:sep]
    list_ys = [y + 24 for y in list_ys]
    for _ in range(FavoritesReader.CONFIRM_FRAMES - 1):
        reader.update(grown, list_ys)
        assert reader.separator == sep
    reader.update(grown, list_ys)
    assert reader.separator == sep + 24


def test_blinking_list_top_is_not_taken_as_a_favorite(templates):
    # 목록 맨 위 버프가 30초 이하로 점멸·반투명이어도 경계는 구분선으로만 정한다(사용자 지적).
    region = _region("233749")
    reader, list_ys = _read(region, templates)
    sep, rows = reader.separator, dict(reader.rows)
    blink = region.copy()
    blink[sep + 3:sep + 27] = (blink[sep + 3:sep + 27] * 0.35).astype(np.uint8)
    for _ in range(FavoritesReader.CONFIRM_FRAMES + 2):
        reader.update(blink, list_ys)
    assert reader.separator == sep and reader.rows == rows and reader.row_count == 7


def test_order_change_is_remapped_automatically(templates):
    region = _region("001307")
    reader, list_ys = _read(region, templates)
    first, second = reader.rows["rebirth"].y, reader.rows["miir"].y
    swapped = region.copy()  # 게임에서 즐겨찾기 1·2번째 줄 순서를 바꿈
    swapped[first:first + 24], swapped[second:second + 24] = region[second:second + 24], region[first:first + 24]
    reader.update(swapped, list_ys)
    assert reader.rows["rebirth"].y == second and reader.rows["miir"].y == first
    assert reader.on["rebirth"] and not reader.on["miir"]


def test_anchor_buff_in_favorites_counts_as_seen(templates):
    # 기준 버프가 즐겨찾기 칸에 있어도 켜져 있으면 정상 프레임(기준 버프 미검출 경고 없음)
    engine = BuffEngine(templates, list(NAMES), anchor_id="rebirth", favorites=True)
    region = _region("001307")
    for i in range(6):
        result = engine.tick(region, 100.0 + i * 0.05)
    assert result.frame_valid and engine.anchor_seen


@pytest.mark.parametrize("stamp, box_top", [("213313", 615), ("142736", 449)])
def test_autofind_widens_to_favorites_top(stamp, box_top):
    # 자동 찾기 기본값(기준 버프 위 34줄)이 즐겨찾기 칸 중간·아래에서 시작할 때 창 위 테두리(y≈418) 위까지 넓힌다.
    from mabinogi_addon.detect.favorites import favorites_top
    from mabinogi_addon.detect.status_panel import find_anchor
    image = _load(stamp)
    box = locate_status_region(image, anchor_template())
    assert box[1] == box_top
    top = favorites_top(image, box, find_anchor(image, anchor_template()).y)
    assert 405 <= top <= 418 < 429  # 첫 즐겨찾기 줄(y=429)보다 위


def test_autofind_keeps_box_when_it_already_covers_favorites():
    from mabinogi_addon.detect.favorites import favorites_top
    from mabinogi_addon.detect.status_panel import find_anchor
    image = _load("233749")
    box = locate_status_region(image, anchor_template())
    assert favorites_top(image, box, find_anchor(image, anchor_template()).y) is None
