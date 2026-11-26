"""걷기 다시 그리기(기획 11-26, docs/characters/걷기_다시그리기.md 'QA 확인 기준') — 다섯 캐릭터 + 착장 2벌 걷기 8장.

기준 머리 = 교체 전 앱 walk_0(tests/data/walk_ref — 서 있기와 머리 크기를 맞춰 둔 상태). 새 걷기 머리(위 42%)가 그것과 ±5%,
키는 그 캐릭터(착장은 그 옷) stand_0 대비 ±5%, 8장이 모두 있고 이웃 장 키가 ±3% 안.
"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.character import brain as br
from scripts.silhouette import best_scale

ROOT = Path(__file__).resolve().parents[1]
CHARS = ROOT / "src/mabinogi_addon/assets/characters"
REF = Path(__file__).parent / "data/walk_ref"
CASES = [("아리아", None), ("다래", None), ("레나", None), ("Starline", None), ("이안", None),
         ("아리아", "tshirt"), ("이안", "vest_tie")]
HEAD = 0.42


def _read(path):
    image = image_io.imread(path, cv2.IMREAD_UNCHANGED)
    assert image is not None, path
    return image


def _folder(name, outfit):
    return CHARS / name if outfit is None else CHARS / name / "outfits" / outfit


def _head(frame):
    ys, xs = np.where(frame[..., 3] > 128)
    tight = frame[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return tight[:round(tight.shape[0] * HEAD)]


@pytest.mark.parametrize("name,outfit", CASES, ids=[f"{n}-{o or 'base'}" for n, o in CASES])
def test_walk_has_eight_frames_and_no_size_jump(name, outfit):
    folder = _folder(name, outfit)
    assert sorted(p.name for p in folder.glob("walk_*.png")) == [f"walk_{i}.png" for i in range(8)]
    heights = [_read(folder / f"walk_{i}.png").shape[0] for i in range(8)]
    for a, b in zip(heights, heights[1:] + heights[:1]):
        assert abs(a - b) / a <= 0.03, heights


@pytest.mark.parametrize("name,outfit", CASES, ids=[f"{n}-{o or 'base'}" for n, o in CASES])
def test_walk_head_matches_previous_walk(name, outfit):
    ref = _head(_read(REF / f"{name if outfit is None else f'{name}_{outfit}'}.png"))
    for i in range(8):
        k = best_scale(ref, _head(_read(_folder(name, outfit) / f"walk_{i}.png")), 0.85, 1.15, 61)
        assert 0.95 <= k <= 1.05, (i, k)


@pytest.mark.parametrize("name,outfit", CASES, ids=[f"{n}-{o or 'base'}" for n, o in CASES])
def test_walk_height_matches_stand(name, outfit):
    folder = _folder(name, outfit)
    stand = _read(folder / "stand_0.png").shape[0]
    for i in range(8):
        h = _read(folder / f"walk_{i}.png").shape[0]
        assert abs(h - stand) / stand <= 0.05, (i, h, stand)


def test_walk_loop_time_and_speed_kept():
    """기획 '기본안': 한 바퀴 시간·빠르기는 그대로, 장 수만 8장(이안은 이미 8장 0.15초)."""
    loops = {"DARE": (br.DARE, 1.2, 100.0), "ARIA": (br.ARIA, 1.32, 90.0), "LENA": (br.LENA, 1.32, 85.5),
             "STARLINE": (br.STARLINE, 1.32, 74.8), "IAN": (br.IAN, 1.2, 66.0)}
    for key, (profile, loop, speed) in loops.items():
        names, times, looping = profile.anims["walk"]
        assert names == tuple(f"walk_{i}" for i in range(8)) and looping, key
        assert len(times) == 8 and sum(times) == pytest.approx(loop), key
        assert profile.walk_speed == speed, key


def test_starline_walk_tone_match_keeps_texture():
    """QA 11-26 '걷기 팔·다리가 자글자글': 톤 맞추기 뒤 어두운 안쪽 노이즈(|L − 흐림|)가 맞추기 전 ×1.1 안, 서 있기 대비
    어두운(L<80)·중간(80~170) Lab 평균 ΔE ≤ 3 (예전 경계 자르기 방식은 노이즈 +65%)."""
    from scripts.build_dare_frames import scaled
    from scripts.build_starline_frames import _band_means
    from scripts.build_walk_v2 import WALKS, clean, read_frames

    def noise(img):
        L = cv2.cvtColor(np.ascontiguousarray(img[..., :3]), cv2.COLOR_BGR2LAB).astype(np.float32)[..., 0]
        inner = cv2.erode((img[..., 3] > 250).astype(np.uint8), np.ones((11, 11), np.uint8)) > 0
        return float(np.abs(L - cv2.GaussianBlur(L, (0, 0), 1.5))[inner & (L < 90)].mean())

    stand = _read(CHARS / "Starline" / "stand_0.png")
    ref = _band_means(stand)
    zip_path, folder, factor = WALKS["Starline"]
    for i, raw in enumerate(read_frames(zip_path, folder)):
        made = _read(CHARS / "Starline" / f"walk_{i}.png")
        assert noise(made) <= noise(scaled(clean(raw), factor)) * 1.1, i
        assert all(np.linalg.norm(a - b) <= 3 for a, b in zip(_band_means(made), ref)), i
