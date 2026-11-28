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
CASES = [("아리아", None), ("다래", None), ("레나", None), ("이안", None),   # Starline은 영상 걷기 14장(11-27, 아래 따로)
         ("아리아", "tshirt"), ("이안", "vest_tie")]
HEAD = 0.42


def _read(path):
    path = Path(path)
    if not path.is_file() and path.suffix == ".png" and path.with_suffix(".webp").is_file():
        path = path.with_suffix(".webp")   # Starline 영상판(11-27)은 WebP
    image = image_io.imread(path, cv2.IMREAD_UNCHANGED)
    assert image is not None, path
    return image


def _folder(name, outfit):
    if name in ("다래", "레나") and outfit is None:   # 다래·레나 기본 옷은 영상판(0.60.0) — 예전 시트 걷기는 앱 밖 보관(착장 기준)
        return ROOT / f"docs/characters/assets/{name}/시트_앱크기"
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
    loops = {"DARE": (br.DARE_SHEET, 1.2, 100.0),   # 착장(예전 시트) — 영상판 다래 걷기는 test_dare_video "ARIA": (br.ARIA, 1.32, 90.0), "LENA": (br.LENA_SHEET, 1.32, 85.5),
             "IAN": (br.IAN, 1.2, 66.0)}
    for key, (profile, loop, speed) in loops.items():
        names, times, looping = profile.anims["walk"]
        assert names == tuple(f"walk_{i}" for i in range(8)) and looping, key
        assert len(times) == 8 and sum(times) == pytest.approx(loop), key
        assert profile.walk_speed == speed, key


def test_starline_video_walk_fourteen_frames():
    """Starline 영상 걷기(11-27): 14장 0.1초(한 바퀴 1.4초), 장마다 꽉 맞춘 그림 — 키가 서 있기 ±3%, 이웃 장 키 차 ≤ 3%.
    빠르기 = 한 바퀴 두 걸음 약 112px × 1.15 ÷ 1.4초 = 92."""
    names, times, looping = br.STARLINE.anims["walk"]
    assert names == tuple(f"walk_{i}" for i in range(14)) and looping and times == (0.1,) * 14
    assert br.STARLINE.walk_speed == 92.0
    folder = CHARS / "Starline"
    assert sorted(p.name for p in folder.glob("walk_*.webp")) == sorted(f"walk_{i}.webp" for i in range(14))
    stand = _read(folder / "stand_0.png").shape[0]
    heights = [_read(folder / f"walk_{i}.png").shape[0] for i in range(14)]
    assert all(abs(h - stand) / stand <= 0.03 for h in heights), heights
    for a, b in zip(heights, heights[1:] + heights[:1]):
        assert abs(a - b) / a <= 0.03, heights
