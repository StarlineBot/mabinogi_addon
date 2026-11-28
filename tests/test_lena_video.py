"""레나 영상판(기획 11-28 — docs/status.md '레나 원본크기'): 원본크기 30장 0.1초, 그리기 배율은 Starline·다래와 같음,
착장은 예전 시트 그림 그대로. 호감도 75 공중 앉기 = 구석 앉기 장 + 머리 하나 높이 떠오르기."""
from __future__ import annotations

import json
import os
import random
from pathlib import Path

import cv2
import numpy as np

from mabinogi_addon import image_io
from mabinogi_addon.character import brain as br
from mabinogi_addon.character import motions as mo

CHARS = Path(__file__).resolve().parents[1] / "src/mabinogi_addon/assets/characters"
LA = CHARS / "레나"
LB = br.LENA


def _read(folder, name):
    image = image_io.imread(CHARS / folder / f"{name}.webp", cv2.IMREAD_UNCHANGED)
    assert image is not None, name
    return image


def _alpha_h(image) -> int:
    rows = np.nonzero((image[..., 3] > 128).any(1))[0]
    return int(rows[-1] - rows[0])


def _used():
    names = {n for frames, _t, _l in LB.anims.values() for n in frames}
    return names | {n for m in mo.of("레나") for n in m.names()}


def _app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_every_used_frame_exists_and_nothing_extra():
    on_disk = {p.stem for p in LA.glob("*.webp")}
    assert {p.stem for p in LA.glob("*.png")} == {"card", "frame"}
    assert _used() == on_disk, (sorted(_used() - on_disk)[:5], sorted(on_disk - _used())[:5])


def test_mapping_matches_plan_table():
    def idx(state):
        return [int(n.rsplit("_", 1)[1]) for n in LB.anims[state][0]]
    assert idx("stand") == [*range(30), *range(28, 0, -1)]   # 0→29→1 왕복
    assert idx("walk") == list(range(10, 25))
    assert LB.anims["alert"][:2] == (("talk_alert_0",), (1.5,))
    assert idx("pet_in") == list(range(6)) and idx("pet_loop") == list(range(6, 12)) and idx("pet_out") == list(range(12, 30))
    assert idx("drag_in") == list(range(8)) and idx("drag") == [*range(8, 30), *range(28, 8, -1)]
    assert LB.anims["fall"][0] == ("land_7",) and idx("land") == list(range(8, 30))
    assert idx("crouch") == idx("sit_loop") == idx("rise") == idx("magic") == list(range(30))
    assert LB.anims["sit_loop"][0][0] == "sit_0" and LB.anims["rise"][0][0] == "rise_0"
    assert not LB.pet_shake and LB.notice_holds and LB.rare_extra == "magic" and LB.click_talks
    assert LB.sit_float == (14.0, 3.0, 2.4, 0.4)   # 구석 떠 있기 그대로
    grimoire, float_sit = mo.of("레나")
    assert (grimoire.count, grimoire.frame, dict(grimoire.hold)) == (60, 0.1, {29: 1.0})
    assert float_sit.lift == (55.0, 5.0, 2.4, 30, 30) and float_sit.frame == 0.1


def test_draw_scale_same_as_starline_and_height_is_0782():
    stand_h = json.loads((LA / "frames.json").read_text(encoding="utf-8"))["standH"]
    sl_h = json.loads((CHARS / "Starline" / "frames.json").read_text(encoding="utf-8"))["standH"]
    assert stand_h == br.LENA_STAND_H
    assert abs(br.FIGURE_H / stand_h * LB.scale - br.FIGURE_H / sl_h * br.STARLINE_SCALE) < 1e-3 * br.FIGURE_H / sl_h
    ratio = _alpha_h(_read("레나", "stand_0")) / _alpha_h(_read("Starline", "stand_0"))
    assert abs(ratio / 0.782 - 1) <= 0.02, ratio


def test_action_edges_keep_height_and_head_with_stand():
    from scripts.silhouette import best_scale

    def head(image):
        ys, xs = np.nonzero(image[..., 3] > 128)
        tight = image[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        return tight[:round(tight.shape[0] * 0.35)]

    stand = _read("레나", "stand_0")
    for name in ("pet_0", "pet_29", "drag_0", "land_29", "crouch_0", "rise_29", "magic_0", "magic_29",
                 "motion_grimoire_0", "motion_grimoire_59", "talk_base_0", "talk_end2_0"):
        other = _read("레나", name)
        assert abs(_alpha_h(other) / _alpha_h(stand) - 1) <= 0.03, name
        assert abs(best_scale(head(stand), head(other), 0.85, 1.15, 31) - 1) <= 0.03, name


def test_anchors_put_reference_frames_on_stand_feet():
    from scripts.qa_frame_check import shape
    anchors = json.loads((LA / "anchors.json").read_text(encoding="utf-8"))
    ref = shape(_read("레나", "stand_0"), (0, 0))
    for name in ("pet_0", "drag_0", "land_29", "crouch_0", "rise_29", "magic_0", "motion_grimoire_0", "motion_grimoire_59"):
        got = shape(_read("레나", name), tuple(anchors.get(name, (0, 0))))
        assert abs(got.foot_y - ref.foot_y) <= 1 and abs(got.foot_x - ref.foot_x) <= 1, (name, got.foot_y, got.foot_x)
    assert len({tuple(anchors.get(f"land_{i}", (0, 0))) for i in range(7, 30)}) == 1   # 상자째(엎어진 장도 같은 오프셋)


def test_talk_mouth_only_frames_keep_one_body():
    base = _read("레나", "talk_base_0")
    for key in ("m1", "m2"):
        other = _read("레나", f"talk_{key}_0")
        diff = (np.abs(other.astype(int) - base.astype(int)).max(-1) > 0) & ((base[..., 3] > 0) | (other[..., 3] > 0))
        ys, xs = np.nonzero(diff)
        assert diff.any() and ys.min() >= 156 and ys.max() < 182 and xs.min() >= 134 and xs.max() < 168, key


def _brain(**kw):
    b = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(3), profile=LB, **kw)
    b.pos = (300.0, 700.0)
    return b


def test_grab_plays_hang_start_once_then_kicks_back_and_forth():
    b = _brain()
    b.press(1.0, 300, 600)
    b.move(1.1, 340, 560)
    assert b.state == "drag"
    assert [b.frame(1.1 + i * 0.1 + 0.01) for i in range(8)] == [f"drag_{i}" for i in range(8)]   # 매달리기 시작 한 번
    loop = [b.frame(1.1 + 0.8 + i * 0.1 + 0.01) for i in range(42)]
    assert loop[:22] == [f"drag_{i}" for i in range(8, 30)] and loop[22:] == [f"drag_{i}" for i in range(28, 8, -1)]
    assert b.frame(1.1 + 0.8 + 4.2 + 0.01) == "drag_8"   # 다시 8부터(0~7은 안 나옴)


def test_float_sit_motion_rises_head_high_and_comes_down():
    """호감도 75 공중 앉기(사용자 11-28 '앉기에서 위로 띄우기만 하면 공중 앉기'): 구석 앉기 장 동안 0 → 55px(키 190 기준 × 배율),
    가만히 반복 동안 ±5 둥둥, 내려오기 장 동안 55 → 0. 구석 앉기의 떠 있기(14px)는 그대로."""
    b = _brain()
    _grimoire, float_sit = mo.of("레나")
    b.set_motions({float_sit.key: float_sit}, {float_sit.key: 1.0})
    b.state, b._goal = "stand", "roam"
    assert b.play_motion(float_sit.key, 10.0)
    total = sum(d for _n, d in b._motion_seq)
    k = LB.scale
    assert b.float_offset(10.0) == 0.0
    assert abs(b.float_offset(11.5) + 55 * k * 0.5) < 0.5            # 앉기 절반 = 절반 올라감
    mid = [b.float_offset(13.0 + i * 0.1) for i in range(int((total - 6.5) * 10))]
    assert all(-(55 + 5.01) * k <= v <= -(55 - 5.01) * k for v in mid) and max(mid) - min(mid) > 8 * k   # 둥둥
    assert abs(b.float_offset(10.0 + total - 1.5) + 55 * k * 0.5) < 0.5   # 내려오기 절반
    assert abs(b.float_offset(10.0 + total - 0.01)) < 0.5
    assert b.frame(10.05) == "crouch_0" and b.frame(10.0 + total - 0.05) == "rise_29"


def test_outfits_keep_sheet_pictures_and_profile():
    _app()
    from mabinogi_addon.ui import pet_window as pw

    assert br.profile_for("레나") is LB and br.profile_for("레나", True) is br.LENA_SHEET
    assert br.LENA_SHEET.scale == 0.95 and br.LENA_SHEET.pet_shake   # 착장은 예전 그대로
    for outfit in ("lab", "red_dress"):
        frames = pw.load_frames("레나", outfit=outfit)
        assert isinstance(frames, dict)
        names = {n for f, _t, _l in br.LENA_SHEET.anims.values() for n in f}
        assert names <= set(frames) and "motion_grimoire_7" in frames and "motion_grimoire_8" not in frames
    base = pw.load_frames("레나")
    assert isinstance(base, pw.LazyFrames) and base.frame_h == br.LENA_STAND_H and set(base) == _used()


def test_lazy_frames_memory_like_starline():
    _app()
    from mabinogi_addon.ui import pet_window as pw

    frames = pw.load_frames("레나", LB)
    w = pw.PetWindow(br.Brain(br.Floor(0, 1600, 700), profile=LB), frames, "#5B6BC9")
    try:
        for name in list(frames):
            assert w._image(name) is not None, name
        size = sum(frames[n].sizeInBytes() for n in frames.loaded()) + sum(i.sizeInBytes() for i in w._scaled.values())
        assert len(frames.loaded()) <= len(frames.pinned) + pw.LAZY_KEEP
        assert size / 2 ** 20 < 40, size / 2 ** 20
    finally:
        w.close()


def test_qa_frame_check_passes():
    from scripts.qa_frame_check import check
    assert check("레나") == []
