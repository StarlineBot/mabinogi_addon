"""레나 '연구실 차림'(호감도 50, key lab) 펫 SD — 기획 11-26(docs/characters/새옷_전체프레임_한번에.md '레나 · 연구실 차림').

프레임표 v2(3×4) + 바뀐 옷, 칸마다 머리(위 42%) 맞춤. 기본 레나와 같은 프레임 이름 전부 + 모션 2개(마법서·공중앉기 8장씩).
"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.character import brain as br
from scripts.silhouette import best_scale

CHARS = Path(__file__).resolve().parents[1] / "src/mabinogi_addon/assets/characters"
BASE, LAB = CHARS / "레나", CHARS / "레나/outfits/lab"
MOTIONS = {f"motion_grimoire_{i}" for i in range(8)} | {f"motion_float_sit_{i}" for i in range(8)}


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


def test_lab_has_every_base_frame_and_motions():
    assert _names(LAB) == _names(BASE) | MOTIONS
    used = {n for frames, _t, _l in br.LENA.anims.values() for n in frames}
    assert not [n for n in used if not (LAB / f"{n}.png").is_file()]   # 펫이 쓰는 모든 동작이 이 폴더에


@pytest.mark.parametrize("name", sorted(_names(BASE)))
def test_lab_frame_matches_base_head_and_height(name):
    base, lab = _read(BASE / f"{name}.png"), _read(LAB / f"{name}.png")
    k = best_scale(_head(base), _head(lab), 0.85, 1.15, 61)
    assert 0.95 <= k <= 1.05, k
    assert abs(lab.shape[0] - base.shape[0]) / base.shape[0] <= 0.06, (lab.shape[0], base.shape[0])


def test_lab_tones_match_its_stand():
    """머리(남색)·피부 시트 간 차 맞춤(harmonize_colors, 기준 = 이 옷 stand_0): 어두운·중간 톤 Lab 평균 ΔE ≤ 10."""
    def tones(path):
        f = _read(path)
        a = f[..., 3] > 200
        lab = cv2.cvtColor(np.ascontiguousarray(f[..., :3]), cv2.COLOR_BGR2LAB).astype(np.float64)
        return [lab[a & (lab[..., 0] < 80)].mean(0), lab[a & (lab[..., 0] >= 80) & (lab[..., 0] <= 170)].mean(0)]

    ref = tones(LAB / "stand_0.png")
    for path in LAB.glob("*.png"):
        if path.stem == "card":
            continue
        dark, mid = tones(path)
        assert np.linalg.norm(dark - ref[0]) <= 10 and np.linalg.norm(mid - ref[1]) <= 10, path.stem


def test_wearing_lab_swaps_pet_frames():
    """연구실 차림을 입으면 펫 창 프레임이 착장 폴더 그림으로(없는 프레임 없음)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    from mabinogi_addon.ui import pet_window

    base = pet_window.load_frames("레나", br.LENA)
    lab = pet_window.load_frames("레나", br.LENA, "lab")
    assert set(base) == set(lab)
    assert all(base[n].size() != lab[n].size() or base[n] != lab[n] for n in ("stand_0", "walk_0", "magic_0"))
