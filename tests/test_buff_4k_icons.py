"""0.33.0 QA: 4K 버프 아이콘 점수가 기준(0.8) 바로 위 — 사라짐 경고 반복·버프 미검출.

4K 화면의 버프 아이콘은 미세하게 흐려 실제 버프 점수가 0.83~0.87(2560·창·1080은 1.0). 점수가 0.8 근처에서 흔들리면
'있음→3초 없음' 확정이 반복돼 사라짐 경고가 계속 울렸고, 2026-10-11_123333(4K)의 행진곡(0.786)은 목록에서 빠졌다.
기준 0.8은 그대로(낮추면 비슷한 아이콘 0.70~0.77이 '있음'): 기준 바로 아래는 흐려 비교해 구제, 이미 있던 버프는 같은 줄 이력으로 유지.
"""
import glob
import os

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.catalog import available_catalog, build_templates
from mabinogi_addon.detect import detect_buffs
from mabinogi_addon.detect.icon_matcher import DEFAULT_THRESHOLD, match_icon
from mabinogi_addon.detect.status_panel import anchor_template, locate_status_region
from mabinogi_addon.tracker.engine import BuffEngine


@pytest.fixture(scope="module")
def catalog():
    return build_templates(available_catalog())


def _region(path):
    frame = image_io.imread(path, cv2.IMREAD_COLOR)
    x, y, w, h = locate_status_region(frame, anchor_template())
    return np.ascontiguousarray(frame[y:y + h, x:x + w]), frame.shape[0]


def test_4k_march_found_in_123333(catalog):
    region, _ = _region("tests/data/2026-10-11_123333.png")
    found = {d.buff_id: d.score for d in detect_buffs(region, catalog, (0, 50))}
    assert "march" in found and found["march"] < DEFAULT_THRESHOLD  # 0.786 — 흐려 비교로 구제(0.912)


PNGS = sorted(glob.glob("tests/data/**/*.png", recursive=True))
RESCUED = {"2026-10-11_123333.png": {"march"}}  # 한 프레임 검출이 예전(0.8 이상)과 다른 유일한 장


def _shot(path):
    frame = image_io.imread(path, cv2.IMREAD_COLOR)
    if frame is None or frame.ndim != 3 or frame.shape[0] < 500:
        pytest.skip("버프 화면 아님")
    box = locate_status_region(frame, anchor_template())
    if not box:
        pytest.skip("상태목록창 없음")
    x, y, w, h = box
    return np.ascontiguousarray(frame[y:y + h, x:x + w]), frame.shape[0]


@pytest.mark.parametrize("path", PNGS, ids=os.path.basename)
def test_detections_unchanged_except_4k_rescue(catalog, path):
    """한 프레임(이력 없음) 검출이 예전(점수 0.8 이상)과 같다 — 다른 건 123333 행진곡뿐. 2560·창·1080 결과 그대로.
    4K 장은 검출 점수 하한도 본다(구제 구간 0.78 아래로 떨어진 '있음'이 없음)."""
    region, height = _shot(path)

    def gray(img):
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    strip = gray(region[:, 0:50])
    legacy = {bid for bid, t in catalog.items() if match_icon(strip, gray(t)).score >= DEFAULT_THRESHOLD}
    found = detect_buffs(region, catalog, (0, 50))
    assert {d.buff_id for d in found} == legacy | RESCUED.get(os.path.basename(path), set())
    if height >= 2000:
        assert all(d.score >= 0.78 for d in found), found


def test_enough_4k_shots():
    heights = [image_io.imread(p, cv2.IMREAD_COLOR).shape[0] for p in PNGS if "mabinogi_2026" in p or "2026-10-1" in p]
    assert sum(h >= 2000 for h in heights) >= 9


def _noisy(region, y, size, sigma=25):
    out = region.copy()
    rng = np.random.default_rng(0)
    patch = out[y:y + size, 0:50].astype(float) + rng.normal(0, sigma, (size, 50, 3))
    out[y:y + size, 0:50] = np.clip(patch, 0, 255).astype(np.uint8)
    return out


def test_held_buff_survives_score_dip_but_not_real_end(catalog):
    region, _ = _region("tests/data/mabinogi_2026_10_30_214016.png")
    march = {d.buff_id: d for d in detect_buffs(region, catalog, (0, 50))}["march"]
    size = catalog["march"].shape[0]
    dipped = _noisy(region, march.y, size)  # 4K 흔들림처럼 점수 0.75~0.78
    assert "march" not in {d.buff_id for d in detect_buffs(dipped, catalog, (0, 50))}
    kept = {d.buff_id: d for d in detect_buffs(dipped, catalog, (0, 50), held={"march": march.y})}
    assert "march" in kept and 0.75 <= kept["march"].score < 0.78
    gone = region.copy()
    gone[march.y:march.y + size, 0:50] = region[march.y - 30:march.y - 30 + size, 0:50]  # 아이콘이 실제로 사라짐
    assert "march" not in {d.buff_id for d in detect_buffs(gone, catalog, (0, 50), held={"march": march.y})}


def test_engine_keeps_4k_buff_through_flicker(catalog):
    """흔들린 프레임 0.6초·정상 0.2초를 8초 동안 반복 — 목록의 예리(4K 0.854)가 계속 '있음'(예전: 없음 확정 반복 → 사라짐 경고 반복).
    (214016 행진곡은 꺼진 즐겨찾기라 목록 버프인 213927 예리로 본다.)"""
    region, _ = _region("tests/data/mabinogi_2026_10_30_213927.png")
    sharp = {d.buff_id: d for d in detect_buffs(region, catalog, (0, 50))}["sharp"]
    dipped = _noisy(region, sharp.y, catalog["sharp"].shape[0], sigma=20)  # 0.775
    assert "sharp" not in {d.buff_id for d in detect_buffs(dipped, catalog, (0, 50))}
    # 지속시간 표시를 끈 버프(시간으로 '아직 있음'을 확인하는 보조 경로가 없음 — 사라짐 경고가 반복되던 경우)
    engine = BuffEngine(catalog, list(catalog), anchor_id="premium_battle", favorites=True,
                        show_duration={"sharp": False})
    for i in range(6):
        engine.tick(region, i * 0.05)
    for i in range(80):
        # 흔들림 0.6초(엔진 '없음' 확정 0.4초보다 김) + 정상 0.2초를 반복
        result = engine.tick(dipped if i % 8 < 6 else region, 1.0 + i * 0.1)
        assert "sharp" in {entry.buff_id for entry in result.entries}, i
