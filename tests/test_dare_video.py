"""다래 영상판(기획 11-28 — docs/status.md '다래 영상판 원본크기·DEV 넘김'): 원본크기 30장 0.1초, 그리기 배율은 Starline과 같음,
착장은 예전 시트 그림 그대로."""
from __future__ import annotations

import os
import random
from pathlib import Path

import cv2
import numpy as np

from mabinogi_addon import image_io
from mabinogi_addon.character import brain as br
from mabinogi_addon.character import motions as mo

CHARS = Path(__file__).resolve().parents[1] / "src/mabinogi_addon/assets/characters"
DA = CHARS / "다래"
DB = br.DARE


def _read(folder, name):
    image = image_io.imread(CHARS / folder / f"{name}.webp", cv2.IMREAD_UNCHANGED)
    assert image is not None, name
    return image


def _alpha_h(image) -> int:
    rows = np.nonzero((image[..., 3] > 128).any(1))[0]
    return int(rows[-1] - rows[0])


def _used():
    names = {n for frames, _t, _l in DB.anims.values() for n in frames}
    return names | {n for m in mo.of("다래") for n in m.names()}


def _app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_every_used_frame_exists_and_nothing_extra():
    """매핑의 모든 장이 WebP로 있고(장 누락 0), 앱 폴더엔 쓰는 장 + 카드·테두리만(예전 기본 옷 PNG 없음)."""
    on_disk = {p.stem for p in DA.glob("*.webp")}
    assert {p.stem for p in DA.glob("*.png")} == {"card", "frame"}
    assert _used() == on_disk, (sorted(_used() - on_disk)[:5], sorted(on_disk - _used())[:5])


def test_mapping_matches_plan_table():
    """기획 장 매핑 표(11-28)."""
    def idx(state):
        return [int(n.rsplit("_", 1)[1]) for n in DB.anims[state][0]]
    assert idx("stand") == list(range(30)) and idx("walk") == list(range(15, 29))
    assert idx("surprise") == idx("alert") == list(range(30))
    assert idx("pet_in") == [0, 1, 2, 3] and idx("pet_out") == list(range(22, 30))
    assert idx("pet_loop") == [*range(4, 22), *range(20, 4, -1)]   # 4→21→5 왕복
    assert idx("drag") == [*range(30), *range(28, 0, -1)]
    assert DB.anims["fall"][0] == ("land_3",) and idx("land") == list(range(4, 30))
    assert idx("crouch") == list(range(21)) and idx("sit_loop") == list(range(21, 28))
    assert idx("sleep_down") == list(range(20)) and idx("sleep_loop") == list(range(20, 28))
    assert DB.anims["sleep_up"][0][0].startswith("sleepup_") and idx("sleep_up") == list(range(30))
    assert idx("wake") == idx("rise") == list(range(30))   # 일어나기도 졸다 깨어 일어남(기획 11-28 — 20~29는 자세가 툭 바뀜)
    for state, (frames, times, _loop) in DB.anims.items():
        if state not in ("fall", "sit_notice", "talk", "talk_end"):
            assert set(times) == {0.1}, state
    sheep, bubbles = mo.of("다래")
    assert (sheep.count, sheep.frame, dict(sheep.hold), sheep.loop) == (30, 0.1, {15: 1.0}, None)
    assert (bubbles.count, bubbles.frame, bubbles.loop) == (30, 0.1, None)


def test_draw_scale_same_as_starline_and_height_is_0787():
    """화면 px/저장 px = Starline과 같음(190 × 1.15 / 524), 그래서 다래 서기 키 ≈ Starline × 0.787(±2%) — 따로 줄이거나 키우지 않음."""
    import json
    stand_h = json.loads((DA / "frames.json").read_text(encoding="utf-8"))["standH"]
    sl_h = json.loads((CHARS / "Starline" / "frames.json").read_text(encoding="utf-8"))["standH"]
    assert stand_h == br.DARE_STAND_H == 412
    # 깨기·일어나기(7_깨기)만 0.98로 그림 — 앉은 자세에서 원본이 졸기보다 약 3.5% 크게 찍힘(기획 11-28, 그림 파일은 그대로)
    assert json.loads((DA / "frames.json").read_text(encoding="utf-8"))["drawScale"] == {"wake": 0.98}
    assert abs(br.FIGURE_H / stand_h * DB.scale - br.FIGURE_H / sl_h * br.STARLINE_SCALE) < 1e-3 * br.FIGURE_H / sl_h
    ratio = _alpha_h(_read("다래", "stand_0")) / _alpha_h(_read("Starline", "stand_0"))
    assert abs(ratio / 0.787 - 1) <= 0.02, ratio
    drawn = br.FIGURE_H / stand_h * DB.scale * _alpha_h(_read("다래", "stand_0"))
    assert 168 <= drawn <= 176   # dpr1 키 약 172px(Starline 약 218)


def test_action_edges_keep_height_and_head_with_stand():
    """서기 ↔ 각 동작 첫·끝 장(기준 장): 앱이 그리는 키 ±3%·머리 실루엣 ±3%."""
    from scripts.silhouette import best_scale

    def head(image):
        ys, xs = np.nonzero(image[..., 3] > 128)
        tight = image[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        return tight[:round(tight.shape[0] * 0.35)]

    stand = _read("다래", "stand_0")
    for name in ("surprise_0", "surprise_29", "pet_0", "pet_29", "drag_0", "land_29", "crouch_0", "sleepup_29",
                 "wake_29", "motion_sheep_doll_0", "motion_sheep_doll_29", "motion_bubbles_0", "motion_bubbles_29",
                 "talk_base_0"):
        other = _read("다래", name)
        assert abs(_alpha_h(other) / _alpha_h(stand) - 1) <= 0.03, name
        assert abs(best_scale(head(stand), head(other), 0.85, 1.15, 31) - 1) <= 0.03, name


def test_anchors_put_reference_frames_on_stand_feet():
    """동작 상자째 놓고, 기준 장 발 바닥·가운데가 서기와 같은 자리(빌드가 잰 오프셋, 저장 px 2 안)."""
    import json

    from scripts.qa_frame_check import shape
    anchors = json.loads((DA / "anchors.json").read_text(encoding="utf-8"))
    ref = shape(_read("다래", "stand_0"), (0, 0))
    for name in ("surprise_0", "pet_0", "drag_0", "land_29", "crouch_0", "sleepup_29", "wake_29", "talk_base_0",
                 "motion_sheep_doll_0", "motion_bubbles_0"):
        got = shape(_read("다래", name), tuple(anchors.get(name, (0, 0))))
        assert abs(got.foot_y - ref.foot_y) <= 1 and abs(got.foot_x - ref.foot_x) <= 1, (name, got.foot_y, got.foot_x)
    assert len({tuple(anchors[f"pet_{i}"]) for i in range(30)}) == 1   # 같은 동작은 한 오프셋(장마다 다시 맞추지 않음)


def test_talk_mouth_only_frames_keep_one_body():
    """말하기는 Starline 방식 — 입 다문 0번 몸에 25·26번 입만(입 둘레 밖은 픽셀 그대로)."""
    base = _read("다래", "talk_base_0")
    for key in ("m1", "m2"):
        other = _read("다래", f"talk_{key}_0")
        diff = (np.abs(other.astype(int) - base.astype(int)).max(-1) > 0) & ((base[..., 3] > 0) | (other[..., 3] > 0))
        ys, xs = np.nonzero(diff)
        assert diff.any() and ys.min() >= 194 and ys.max() < 218 and xs.min() >= 146 and xs.max() < 178, key


def _video(**kw):
    b = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(3), profile=DB, **kw)
    b.pos = (300.0, 700.0)
    return b


def _run(b, t, seconds, front, step=0.05):
    seen = []
    end = t + seconds
    while t < end:
        t += step
        b.tick(t, front)
        seen.append(b.state)
    return t, seen


def test_corner_dozes_click_wakes_then_sits_again_and_game_end_rises():
    """구석: 웅크리기 0~20 → 졸기 21~27 반복(Zzz) → 클릭 = 깨기 0~29 → 서기 → (게임 중) 다시 웅크림. 게임 끝 = 일어나기."""
    b = _video(corner=(900.0, 700.0))
    t, seen = _run(b, 0, 20, True)
    assert "crouch" in seen and b.state == "sit_loop" and b.zzz()
    x, y = b.pos
    b.press(t, x, y - 60)
    assert ("say", "click_sleep") in b.release(t) and b.state == "wake"
    t, seen = _run(b, t, 6, True)
    n = seen.count("wake")
    assert 58 <= n <= 60 and seen[n] in ("stand", "crouch") and b.state in ("crouch", "sit_loop")   # 3초 깨기 → 서자마자 다시 웅크림
    t, seen = _run(b, t, 3, True)
    t, seen = _run(b, t, 6, False)   # 1.5초 뒤 게임 밖 → 일어나기 3초 → 서기
    assert "rise" in seen and seen[seen.index("rise") - 1] == "sit_loop" and "stand" in seen


def test_lying_down_wakes_standing_then_crouches_again_in_game():
    """엎드려 자기: 졸기 중 3~6분마다 엎드림 0~19 → 숨쉬기 20~27 → 엎드려 깨기 7B(일어나 섬) → 게임 중이면 다시 웅크려 졸기,
    게임이 끝나면 엎드려 깨기 → 서기(예전 '앉은 뒤 일어나기' 없음)."""
    b = _video(corner=(900.0, 700.0))
    t, seen = 0.0, []
    while t < 900 and "sleep_up" not in seen:
        t, more = _run(b, t, 1.0, True, step=0.25)
        seen += more
    assert "sleep_down" in seen and "sleep_loop" in seen
    t, more = _run(b, t, 6, True)
    after = seen[seen.index("sleep_up"):] + more
    assert "crouch" in after and b.state in ("crouch", "sit_loop")
    c = _video(corner=(900.0, 700.0))
    t = 0.0
    while c.state != "sleep_loop":
        t += 0.25
        c.tick(t, True)
    t, seen = _run(c, t, 6, False)
    assert "sleep_up" in seen and seen[seen.index("sleep_up") - 1] == "sleep_loop" and "stand" in seen and "rise" not in seen


def test_outfits_keep_sheet_pictures_and_profile():
    """착장(프릴 잠옷·오프숄더)은 영상판 그림이 없어 예전 시트 한 벌 — 그 옷 폴더 그림만, 예전 크기·시트 프로필·8장 모션."""
    _app()
    from mabinogi_addon.ui import pet_window as pw

    assert br.profile_for("다래") is DB and br.profile_for("다래", True) is br.DARE_SHEET
    assert br.profile_for("아리아", True) is br.ARIA
    for outfit in ("frill_pajama", "white_offshoulder"):
        assert pw.dressed("다래", outfit)
        frames = pw.load_frames("다래", outfit=outfit)
        assert isinstance(frames, dict) and not hasattr(frames, "frame_h")   # 예전 기준 키(FRAME_DIR_H)
        names = {n for f, _t, _l in br.DARE_SHEET.anims.values() for n in f}
        assert names <= set(frames) and "motion_sheep_doll_7" in frames and "motion_sheep_doll_8" not in frames
    base = pw.load_frames("다래")
    assert isinstance(base, pw.LazyFrames) and base.frame_h == 412 and set(base) == _used()


def test_lazy_frames_memory_like_starline():
    """다래 344장도 늘 쓰는 장만 미리 읽고 나머지는 그때그때 — 모든 장을 한 번씩 다 그려도 원본 + 화면용 40MB 아래."""
    _app()
    from mabinogi_addon.ui import pet_window as pw

    frames = pw.load_frames("다래", DB)
    w = pw.PetWindow(br.Brain(br.Floor(0, 1600, 700), profile=DB), frames, "#B48CE6")
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
    assert check("다래") == []   # 착장은 예전 시트 그림 그대로(바꾸지 않음) — 이 검사 대상 밖
