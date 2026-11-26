"""프레임표 v2 착장 펫 SD(기획 11-26, docs/characters/새옷_전체프레임_한번에.md) — 레나 '연구실 차림'(lab)·다래 '프릴 잠옷 원피스'(frill_pajama).

프레임표 v2(3×4) + 바뀐 옷, 칸마다 머리(위 42%) 맞춤. 기본 캐릭터와 같은 프레임 이름 전부 + 모션 2개(8장씩).
"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.character import brain as br
from scripts.silhouette import best_scale

CHARS = Path(__file__).resolve().parents[1] / "src/mabinogi_addon/assets/characters"
OUTFITS = {   # (캐릭터, 옷) → (펫 프로필, 모션 이름 두 개)
    ("레나", "lab"): (br.LENA, ("motion_grimoire", "motion_float_sit")),
    ("다래", "frill_pajama"): (br.DARE, ("motion_sheep_doll", "motion_bubbles")),
}


def _read(path):
    image = image_io.imread(path, cv2.IMREAD_UNCHANGED)
    assert image is not None, path
    return image


def _head(frame):
    ys, xs = np.where(frame[..., 3] > 128)
    tight = frame[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return tight[:round(tight.shape[0] * 0.42)]


def _names(folder):
    return {p.stem for p in folder.glob("*.png") if p.stem not in ("card", "frame")}


# 머리는 맞지만 자세가 낮아 키만 6% 넘게 다른 칸(렌더 확인 11-26): 다래 sleep_5 엎드림 — 기본 옷 머리카락·꼬리 장식이 더 내려옴(163 vs 176)
HEIGHT_TOL = {("다래", "sleep_5"): 0.08}
FRAMES = [(c, o, n) for (c, o) in OUTFITS for n in sorted(_names(CHARS / c))]


@pytest.mark.parametrize("char,outfit", list(OUTFITS))
def test_outfit_has_every_base_frame_and_motions(char, outfit):
    profile, motions = OUTFITS[(char, outfit)]
    folder = CHARS / char / "outfits" / outfit
    assert _names(folder) == _names(CHARS / char) | {f"{m}_{i}" for m in motions for i in range(8)}
    used = {n for frames, _t, _l in profile.anims.values() for n in frames}
    assert not [n for n in used if not (folder / f"{n}.png").is_file()]   # 펫이 쓰는 모든 동작이 이 폴더에


@pytest.mark.parametrize("char,outfit,name", FRAMES, ids=[f"{c}-{o}-{n}" for c, o, n in FRAMES])
def test_outfit_frame_matches_base_head_and_height(char, outfit, name):
    base, dressed = _read(CHARS / char / f"{name}.png"), _read(CHARS / char / "outfits" / outfit / f"{name}.png")
    k = best_scale(_head(base), _head(dressed), 0.85, 1.15, 61)
    assert 0.95 <= k <= 1.05, k
    tol = HEIGHT_TOL.get((char, name), 0.06)
    assert abs(dressed.shape[0] - base.shape[0]) / base.shape[0] <= tol, (dressed.shape[0], base.shape[0])


@pytest.mark.parametrize("char,outfit", list(OUTFITS))
def test_outfit_tones_match_its_stand(char, outfit):
    """머리·피부 시트 간 차 맞춤(harmonize_colors, 기준 = 이 옷 stand_0): 어두운·중간 톤 Lab 평균 ΔE ≤ 10."""
    folder = CHARS / char / "outfits" / outfit

    def tones(path):
        f = _read(path)
        a = f[..., 3] > 200
        lab = cv2.cvtColor(np.ascontiguousarray(f[..., :3]), cv2.COLOR_BGR2LAB).astype(np.float64)
        return [lab[a & (lab[..., 0] < 80)].mean(0), lab[a & (lab[..., 0] >= 80) & (lab[..., 0] <= 170)].mean(0)]

    ref = tones(folder / "stand_0.png")
    for path in folder.glob("*.png"):
        if path.stem == "card":
            continue
        dark, mid = tones(path)
        assert np.linalg.norm(dark - ref[0]) <= 10 and np.linalg.norm(mid - ref[1]) <= 10, path.stem


@pytest.mark.parametrize("char,outfit", list(OUTFITS))
def test_wearing_outfit_swaps_pet_frames(char, outfit):
    """옷을 입으면 펫 창 프레임이 착장 폴더 그림으로(없는 프레임 없음)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    from mabinogi_addon.ui import pet_window

    profile = OUTFITS[(char, outfit)][0]
    base = pet_window.load_frames(char, profile)
    dressed = pet_window.load_frames(char, profile, outfit)
    assert set(base) == set(dressed)
    assert all(base[n].size() != dressed[n].size() or base[n] != dressed[n] for n in ("stand_0", "walk_0", "pet_0"))
