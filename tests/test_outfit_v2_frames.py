"""프레임표 v2 착장 펫 SD(기획 11-26, docs/characters/새옷_전체프레임_한번에.md) — 호감도 50 레나 '연구실 차림'(lab)·다래 '프릴 잠옷 원피스'
(frill_pajama), 호감도 100 이안 '길드 고위 정복'·아리아 '가벼운 여름 드레스'·다래 '하얀 오프숄더'·레나 '빨간 원피스'.

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
OUTFITS = {   # (캐릭터, 옷) → (펫 프로필, 모션 이름 두 개, 색 기준)
    ("레나", "lab"): (br.LENA, ("motion_grimoire", "motion_float_sit"), "stand_0"),
    ("다래", "frill_pajama"): (br.DARE, ("motion_sheep_doll", "motion_bubbles"), "stand_0"),
    ("이안", "guild_uniform"): (br.IAN, ("motion_tidy", ("motion_tea", 6)), "stand_1"),   # 차 6장(조끼와 같음)
    ("아리아", "summer_dress"): (br.ARIA, ("motion_water", "motion_wreath"), "stand_0"),
    ("다래", "white_offshoulder"): (br.DARE, ("motion_sheep_doll", "motion_bubbles"), "stand_0"),
    ("레나", "red_dress"): (br.LENA, ("motion_grimoire", "motion_float_sit"), "stand_0"),
}
HAT = {("아리아", "summer_dress")}   # 밀짚모자 — 머리(위 42%) 배율은 이 옷 전 칸 중앙값으로 나눠 봄(빌드와 같음)


def _read(path):
    image = image_io.imread(path, cv2.IMREAD_UNCHANGED)
    assert image is not None, path
    return image


def _head(frame):
    ys, xs = np.where(frame[..., 3] > 128)
    tight = frame[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return tight[:round(tight.shape[0] * 0.42)]


def _names(folder):
    """동작 프레임 이름(호감도 모션 제외 — 기본 옷 모션(11-26)과 옷 모션은 그림이 달라 따로 봄)."""
    return {p.stem for p in folder.glob("*.png") if p.stem not in ("card", "frame") and not p.stem.startswith("motion_")}


# 머리는 맞지만 자세가 낮아 키만 6% 넘게 다른 칸(렌더 확인 11-26): 다래 sleep_5 엎드림 — 기본 옷 머리카락·꼬리 장식이 더 내려옴(163 vs 176)
# 다래 오프숄더 sleep_1·wake_3도 같은 까닭(−7.6%, 렌더 확인). 아리아 여름 드레스는 밀짚모자만큼 키가 큼(getup·walk_2 +6~8%).
HEIGHT_TOL = {("다래", "sleep_5"): 0.08, ("다래", "sleep_1"): 0.08, ("다래", "wake_3"): 0.08}
HAT_HEIGHT_TOL = 0.08
# 한 동작 안 배율을 하나로 맞춘 뒤(QA 11-26) 옷 그림 자체의 머리가 그 동작 다른 칸보다 6~9% 큰 칸 — 칸마다 따로 맞추면
# 동작 안에서 크기가 들쭉날쭉해지므로 이 칸들은 머리 0.90까지(그림 그대로, 렌더 확인)
HEAD_TOL = {("아리아", "summer_dress", "pet_3"): 0.90, ("아리아", "summer_dress", "getup_2"): 0.90,
            ("다래", "white_offshoulder", "sleep_1"): 0.90, ("다래", "white_offshoulder", "sleep_7"): 0.90,
            ("다래", "white_offshoulder", "wake_3"): 0.90}
_MEDIANS: dict = {}


def _hat_median(char, outfit):
    if (char, outfit) not in HAT:
        return 1.0
    if (char, outfit) not in _MEDIANS:
        names = _names(CHARS / char)
        _MEDIANS[(char, outfit)] = float(np.median([
            best_scale(_head(_read(CHARS / char / f"{n}.png")), _head(_read(CHARS / char / "outfits" / outfit / f"{n}.png")),
                       0.85, 1.15, 61) for n in names]))
    return _MEDIANS[(char, outfit)]


FRAMES = [(c, o, n) for (c, o) in OUTFITS for n in sorted(_names(CHARS / c))]


@pytest.mark.parametrize("char,outfit", list(OUTFITS))
def test_outfit_has_every_base_frame_and_motions(char, outfit):
    profile, motions, _ref = OUTFITS[(char, outfit)]
    folder = CHARS / char / "outfits" / outfit
    counts = [(m, 8) if isinstance(m, str) else m for m in motions]
    every = {p.stem for p in folder.glob("*.png")} - {"card"}
    assert every == _names(CHARS / char) | {f"{m}_{i}" for m, n in counts for i in range(n)}
    used = {n for frames, _t, _l in profile.anims.values() for n in frames}
    assert not [n for n in used if not (folder / f"{n}.png").is_file()]   # 펫이 쓰는 모든 동작이 이 폴더에


@pytest.mark.parametrize("char,outfit,name", FRAMES, ids=[f"{c}-{o}-{n}" for c, o, n in FRAMES])
def test_outfit_frame_matches_base_head_and_height(char, outfit, name):
    if char == "다래" and name.startswith("drag_"):
        pytest.skip("다래 끌기는 후광 폭으로 맞춤(QA 11-26) — test_dare_drag_halo_width_steady가 봄")
    if outfit == "summer_dress" and name.startswith("pet_"):
        pytest.skip("여름 드레스 쓰다듬기는 모자 아래 띠 폭으로 맞춤(QA 11-26) — test_aria_summer_dress_pet_matches_tshirt_band가 봄")
    base, dressed = _read(CHARS / char / f"{name}.png"), _read(CHARS / char / "outfits" / outfit / f"{name}.png")
    k = best_scale(_head(base), _head(dressed), 0.85, 1.15, 61) / _hat_median(char, outfit)
    assert HEAD_TOL.get((char, outfit, name), 0.95) <= k <= 1.05, k
    tol = HAT_HEIGHT_TOL if (char, outfit) in HAT else HEIGHT_TOL.get((char, name), 0.06)
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

    ref = tones(folder / f"{OUTFITS[(char, outfit)][2]}.png")
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

    profile, _m, ref = OUTFITS[(char, outfit)]
    base = pet_window.load_frames(char, profile)
    dressed = pet_window.load_frames(char, profile, outfit)
    assert set(base) == set(dressed)
    assert all(base[n].size() != dressed[n].size() or base[n] != dressed[n] for n in (ref, "walk_0", "pet_0"))


def test_one_scale_per_animation_group():
    """QA 11-26: 같은 동작 묶음 칸은 머리 배율이 하나(중앙값) — 걷기·모션·말하기 세트·앉기 각각."""
    from scripts.build_outfit_frames import group_of, group_scales
    assert [group_of(n) for n in ("walk_3", "motion_water_2", "talk_a_m1_0", "talk_base_0", "talk_happy_1", "sit_doze_0",
                                  "stand_1", "sleep_8")] == ["walk", "motion_water", "talk_a", "talk", "talk", "sit", "stand", "sleep"]
    img = np.zeros((2, 2, 4), np.uint8)
    pending = [("walk_0", img, 1.0, 0.98), ("walk_1", img, 1.1, 1.04), ("walk_2", img, 0.9, 1.00), ("pet_0", img, 1.0, 0.9)]
    got = {n: k for n, _i, k in group_scales(pending, True)}
    assert got == pytest.approx({"walk_0": 1.0, "walk_1": 1.1, "walk_2": 0.9, "pet_0": 0.9})   # 키 배율 × 묶음 머리 1.00
    motion = [("motion_water_0", img, 1.0, 0.98), ("motion_water_1", img, 1.0, 1.04)]
    assert [k for _n, _i, k in group_scales(motion, True)] == pytest.approx([0.98, 1.04])   # 모션은 칸마다(사용자 11-26)
    hat = {n: k for n, _i, k in group_scales(pending, "median")}
    assert hat["walk_0"] == pytest.approx(1.0 / 0.99)                                         # 전 칸 중앙값 0.99로 나눔


@pytest.mark.parametrize("char,outfit", list(OUTFITS))
def test_drag_and_pet_height_close_to_base_range(char, outfit):
    """QA 11-26 다래 오프숄더 잡아 들기 크기 들쭉날쭉: 끌기·쓰다듬기 키 범위 ≤ 2.5%(기본 캐릭터가 더 크면 그만큼)."""
    def spread(folder, prefix):
        hs = [_read(p).shape[0] for p in folder.glob(f"{prefix}_*.png")]
        return (max(hs) - min(hs)) / min(hs)
    for prefix in ("drag", "pet"):
        if char == "다래" and prefix == "drag":
            continue   # 키는 drag_0만 다리를 펴서 달라 — 후광 폭으로 봄
        if outfit == "summer_dress" and prefix == "pet":
            continue   # 쓰다듬을 때 모자가 눌려 키가 바뀜(263~284) — 모자 아래 띠 폭으로 봄
        allowed = max(0.025, spread(CHARS / char, prefix) + 0.005)
        assert spread(CHARS / char / "outfits" / outfit, prefix) <= allowed, prefix


@pytest.mark.parametrize("char,outfit", list(OUTFITS))
def test_walk_height_range_within_two_percent(char, outfit):
    heights = [_read(CHARS / char / "outfits" / outfit / f"walk_{i}.png").shape[0] for i in range(8)]
    assert (max(heights) - min(heights)) / min(heights) <= 0.021, heights


def test_lena_lab_walk_face_taken_from_base_walk():
    """QA 11-26: 레나 연구실 차림 걷기 얼굴 옆선 — 기본 걷기 얼굴을 옮겨 붙임(scripts/outfit_face_fix). 고치기 전 피부 모양 IoU
    0.70~0.77 → 기준 장 0.78(귀는 옷 그림 것이라 1이 아님)."""
    from scripts.outfit_face_fix import align
    ious = [align(_read(CHARS / "레나" / f"walk_{i}.png"), _read(CHARS / "레나" / "outfits" / "lab" / f"walk_{i}.png"))[1]
            for i in range(8)]
    # 머리는 walk_0 한 장을 모든 장에 붙임(아래 테스트) — 기준 장은 기본 walk_0 얼굴, 나머지는 기본 걷기 장마다의 얼굴과 조금 다름
    assert ious[0] >= 0.78 and min(ious) >= 0.74, ious


@pytest.mark.parametrize("outfit", ["frill_pajama", "white_offshoulder"])
def test_dare_drag_halo_width_steady(outfit):
    """QA 11-26 다래 오프숄더 잡아 들기 크기 들쭉날쭉(후광 폭 142→163): 끌기 묶음 안 후광 폭 범위 ≤ 3%,
    후광 폭 ÷ 서 있기 후광 폭이 기본 다래 같은 칸과 ±3%."""
    from scripts.build_outfit_frames import halo_width
    base, dressed = CHARS / "다래", CHARS / "다래" / "outfits" / outfit
    widths = [halo_width(_read(dressed / f"drag_{i}.png")) for i in range(4)]
    assert (max(widths) - min(widths)) / min(widths) <= 0.03, widths
    for i, w in enumerate(widths):
        mine = w / halo_width(_read(dressed / "stand_0.png"))
        ref = halo_width(_read(base / f"drag_{i}.png")) / halo_width(_read(base / "stand_0.png"))
        assert abs(mine / ref - 1) <= 0.03, (i, mine, ref)


def test_aria_summer_dress_pet_matches_tshirt_band():
    """QA 11-26 여름 드레스 쓰다듬기 때 얼굴이 4~7% 커짐(모자로 머리 실루엣 못 씀): 모자 아래 띠(키 25~55%) 폭 ÷ 티셔츠 같은 칸이
    서 있기 비(0.955)와 ±0.02."""
    from scripts.build_outfit_frames import band_width
    summer, tshirt = CHARS / "아리아" / "outfits" / "summer_dress", CHARS / "아리아" / "outfits" / "tshirt"
    for name in ["stand_0", "stand_1"] + [f"pet_{i}" for i in range(6)]:
        r = band_width(_read(summer / f"{name}.png")) / band_width(_read(tshirt / f"{name}.png"))
        assert abs(r - 0.955) <= 0.02, (name, r)


def test_lena_lab_walk_head_is_one_drawing():
    """QA 11-26 '레나 lab 걷기 머리가 자글자글': 머리(정수리 ~ 턱 아래)는 walk_0 한 장을 장마다 정렬해 붙임 — 다시 붙여도
    머리 영역이 거의 그대로(평균 |ΔL| ≤ 2)."""
    from scripts.outfit_face_fix import CUT, FEATHER, unify_head
    frames = [_read(CHARS / "레나" / "outfits" / "lab" / f"walk_{i}.png") for i in range(8)]
    again = unify_head(frames)
    for i, (a, b) in enumerate(zip(frames, again)):
        top = round(a.shape[0] * CUT) - FEATHER
        la = cv2.cvtColor(np.ascontiguousarray(a[:top, :, :3]), cv2.COLOR_BGR2LAB)[..., 0].astype(float)
        lb = cv2.cvtColor(np.ascontiguousarray(b[:top, :, :3]), cv2.COLOR_BGR2LAB)[..., 0].astype(float)
        solid = (a[:top, :, 3] > 200) & (b[:top, :, 3] > 200)
        assert np.abs(la - lb)[solid].mean() * 100 / 255 <= 2, i


def test_dare_offshoulder_drag_body_width_close_to_base():
    """QA 11-26 오프숄더 잡을 때 몸이 커지는 칸(drag_0 다른 자세) → drag_1로 대신: 몸통 폭(키 40~70%) 180/180/184/192.
    drag_3은 치마가 더 퍼진 그림이라 192 — 범위 6.7%(기본 다래 2.5%), 전 drag_0 198이 있던 때(10%)보다 줄어든 값으로 고정."""
    def body(frame):
        h = frame.shape[0]
        xs = np.where((frame[round(h * 0.4):round(h * 0.7), :, 3] > 128).any(axis=0))[0]
        return xs.max() - xs.min() + 1

    def spread(folder):
        ws = [body(_read(folder / f"drag_{i}.png")) for i in range(4)]
        return (max(ws) - min(ws)) / min(ws)
    assert spread(CHARS / "다래" / "outfits" / "white_offshoulder") <= spread(CHARS / "다래") + 0.045
