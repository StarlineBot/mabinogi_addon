"""0.31.1 버프 즐겨찾기 구분선을 시작할 때 받아들이기(창 모드 wireweb_1~3, 같은 배치).

wireweb_1은 구분선(593) 아래 목록이 모두 미등록 버프라 '선 아래 등록 아이콘' 조건을 못 채워 선을 버렸다 →
꺼진(회색) 즐겨찾기가 켜진 목록 버프로 오버레이에 나옴. 이제 선 바로 위 한 줄에 등록 버프 아이콘(즐겨찾기 줄)이
있으면 구분선으로 받아들인다(영역 아래 게임 바닥선 886은 바로 위가 아이콘 줄이 아니라 그대로 거절).
줄 수: 칸 안 바닥 금을 창 테두리로 잡던 wireweb_3(1줄)도 기억한 줄 기준 15줄로.
"""
import cv2
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.catalog import build_templates, load_catalog
from mabinogi_addon.detect import detect_buffs, favorites

BOX = (2177, 317, 304, 1093)


@pytest.fixture(scope="module")
def templates():
    return build_templates(load_catalog())


def _reader(n, templates):
    frame = image_io.imread(f"tests/data/2026-10-30_windowed_wireweb_{n}.png", cv2.IMREAD_COLOR)
    x, y, w, h = BOX
    region = frame[y:y + h, x:x + w]
    reader = favorites.FavoritesReader(templates, (0, 50))
    list_ys = [d.y for d in detect_buffs(region, templates, (0, 50))]
    for _ in range(reader.CONFIRM_FRAMES * reader.SCAN_EVERY):
        reader.update(region, list_ys)
    return reader, region


@pytest.mark.parametrize("n", [1, 2, 3])
def test_separator_accepted_and_off_favorites_stay_out_of_list(n, templates):
    reader, _region = _reader(n, templates)
    assert reader.separator == 593 and reader.boundary == 593
    off = {bid for bid, on in reader.on.items() if not on}
    assert {"magic_attack", "ladeca", "mana_pierce", "penet"} <= off  # 회색 즐겨찾기 → 목록(켜짐)에 안 섞임
    assert reader.row_count == 15


def test_floor_line_below_panel_is_not_a_separator(templates):
    """선 아래 등록 아이콘이 없을 때의 새 근거도 게임 바닥선(886)에는 걸리지 않는다."""
    reader, region = _reader(1, templates)
    gray = favorites._gray(region)
    assert 886 in favorites.find_separators(gray)
    assert not reader._favorite_row_above(gray, 886)
    assert reader._favorite_row_above(gray, 593)
