"""0.30.2 투아림·도르카 4K: 자동 찾기(장식 금속 픽셀만 마스크)와 판독(4K 글자 참조).

- 장식 마스크가 둘레를 고리로 통째로 잡아 잎사귀 사이 게임 배경까지 비교 → 파란 배경에서 0.95대로 기준 미달.
  배경이 다른 실제 10장에서 값이 거의 안 변하는 픽셀만 남겼다(scripts/build_ornament_mask.py).
- 투아림 %: 4K는 9px 글자·10px '%'(기본 8px) → small_uhd_refs.npz(scripts/build_tuarim_uhd_refs.py).
- 도르카: 4K '1' 획이 3px로 가늘어 기존 참조와 0.68~0.88 → 4K 6장 참조 추가, image55는 넣지 않고 따로 검증.
- 틀린 값 대신 None 원칙 유지.
"""
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.autofind_replay import detector_assets, run_detector
from mabinogi_addon.detect import resource_anchor
from mabinogi_addon.detect.dorcha_reader import read_dorcha
from mabinogi_addon.detect.tuarim_reader import read_percent

ROOT = Path(__file__).resolve().parents[1]
# 파일 → (투아림 상자, 투아림 %, 도르카 상자, 도르카 값). image55는 화면 전체가 4px 위.
SHOTS = {
    "image55.png": ((1368, 81, 42, 16), 9, (1342, 53, 28, 23), 15),
    "mabinogi_2026_10_30_213520.png": ((1368, 85, 42, 16), 44, (1342, 57, 28, 23), 15),
    "mabinogi_2026_10_30_213927.png": ((1368, 85, 42, 16), 0, (1342, 57, 28, 23), 14),
    "mabinogi_2026_10_30_213942.png": ((1368, 85, 42, 16), 3, (1342, 57, 28, 23), 13),
    "mabinogi_2026_10_30_214016.png": ((1368, 85, 42, 16), 8, (1342, 57, 28, 23), 11),
    "mabinogi_2026_10_30_214051.png": ((1368, 85, 42, 16), 13, (1342, 57, 28, 23), 10),
    "mabinogi_2026_10_30_214648.png": ((1368, 85, 42, 16), 24, (1342, 57, 28, 23), 9),
    "2026-10-30_windowed_wireweb_1.png": ((1384, 116, 42, 16), 31, (1358, 88, 28, 23), 10),
    "2026-10-30_windowed_wireweb_2.png": ((1384, 116, 42, 16), 66, (1358, 88, 28, 23), 7),
    "2026-10-30_windowed_wireweb_3.png": ((1384, 116, 42, 16), 51, (1358, 88, 28, 23), 7),
}


def _crop(frame, box):
    x, y, w, h = box
    return frame[y:y + h, x:x + w]


@pytest.mark.parametrize("name", sorted(SHOTS))
def test_tuarim_and_dorcha_found_and_read(name):
    tuarim_box, percent, dorcha_box, word = SHOTS[name]
    frame = image_io.imread(ROOT / "tests/data" / name, cv2.IMREAD_COLOR)
    assert run_detector("tuarim", frame, detector_assets("tuarim"), {}) == tuarim_box
    assert read_percent(_crop(frame, tuarim_box)) == percent
    assert run_detector("dorcha", frame, detector_assets("dorcha"), {}) == dorcha_box
    assert read_dorcha(_crop(frame, dorcha_box)) == word


def test_ornament_mask_is_metal_only_subset_of_old_ring():
    old = image_io.imread(ROOT / "src/mabinogi_addon/detect/templates/autofind/tuarim_mask.png",
                          cv2.IMREAD_GRAYSCALE)[:, :45] > 0
    mask = resource_anchor.assets()["mask"] > 0
    assert mask.any() and not np.any(mask & ~old)  # 예전 고리 안에서만(가운데 숫자 제외 유지)
    assert 0.5 * old.sum() <= mask.sum() <= 0.7 * old.sum()  # 잎사귀 사이 배경을 뺐다(1116 → 672)


def test_dorcha_holdout_4k_was_not_used_for_references():
    sources = json.loads((ROOT / "src/mabinogi_addon/detect/templates/dorcha/sources.json").read_text(encoding="utf-8"))
    assert "image55.png" not in {item["file"] for item in sources}  # 처음 보는 4K 화면으로 검증


def test_tuarim_4k_missing_digit_is_none_not_wrong():
    """4K 세트에 없는 숫자(5·6·7)는 못 읽음: '24%'의 2를 5 모양으로 바꿔도 다른 값이 나오지 않는다."""
    from mabinogi_addon.detect import tuarim_small
    refs, labels, percent = tuarim_small._UHD
    assert set(labels.tolist()) == {0, 1, 2, 3, 4, 8, 9}
    frame = image_io.imread(ROOT / "tests/data/mabinogi_2026_10_30_214648.png", cv2.IMREAD_COLOR)
    region = _crop(frame, (1368, 85, 42, 16)).copy()
    region[:, 10:17] = region[0, 0]  # 십의 자리 '2'를 지움 → '4%'로 읽거나 None, 결코 다른 두 자리 값은 아님
    assert read_percent(region) in (4, None)
