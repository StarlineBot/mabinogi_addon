"""Starline 영상판(사용자 11-27 — docs/characters/Starline_영상모션_작업표.md): 15동작, 0.1초 간격, 기획이 크기·높이·색까지 끝낸 그림."""
from __future__ import annotations

import random
from pathlib import Path

import cv2
import numpy as np

from mabinogi_addon import image_io
from mabinogi_addon.character import brain as br
from mabinogi_addon.character import motions as mo

SL = Path(__file__).resolve().parents[1] / "src/mabinogi_addon/assets/characters/Starline"
SB = br.STARLINE


def _read(name):
    image = image_io.imread(SL / f"{name}.webp", cv2.IMREAD_UNCHANGED)
    assert image is not None, name
    return image


def _used():
    names = {n for frames, _t, _l in SB.anims.values() for n in frames}
    return names | {n for m in mo.of("Starline") for n in m.names()}


def test_every_used_frame_exists_and_nothing_extra():
    """쓰는 장이 다 있고, 앱 폴더엔 쓰는 장(+카드·테두리)만 — 예전 시트 그림이 남지 않음."""
    used = _used()
    on_disk = {p.stem for p in SL.glob("*.webp")}
    assert {p.stem for p in SL.glob("*.png")} == {"card", "frame"}   # 장은 모두 WebP(11-27), PNG는 카드·테두리만
    assert used == on_disk, (sorted(used - on_disk)[:5], sorted(on_disk - used)[:5])


def test_all_video_steps_are_tenth_of_a_second():
    """영상 장은 0.1초 간격 — 한 장만 오래 보여 주는 자리(떨어지기·알림·앉아서 클릭·자리만)는 예외."""
    single = {"fall", "alert", "sit_notice", "surprise"}
    for state, (frames, times, _loop) in SB.anims.items():
        if state in single or state in ("talk", "talk_end"):
            continue
        assert set(times) == {0.1}, state
    assert len(SB.anims["stand"][0]) == 30 and SB.anims["stand"][2]
    assert SB.anims["drag"][0] == tuple(f"drag_{i}" for i in (6, 7, 8, 9, 14, 15, 16, 17))   # 귀 끝 잘린 10~13 뺌
    assert SB.anims["fall"][0] == ("land_4",) and SB.anims["land"][0][0] == "land_12"
    assert SB.anims["pet_in"][0][-1] == "pet_6" and SB.anims["pet_loop"][0] == tuple(f"pet_{i}" for i in range(7, 21))


def test_same_action_frames_share_one_canvas():
    """동작 안 장은 같은 틀 크기 — 아래·가운데 맞춰 그리면 그대로 위치가 맞음(걷기·말하기 합성 장은 따로)."""
    for prefix in ("stand", "flame", "laugh", "chin", "sneeze", "pet", "crouch", "rise", "drag", "land",
                   "motion_flame_shot", "motion_hat_magic"):
        shapes = {_read(p.stem).shape for p in SL.glob(f"{prefix}_*.webp") if p.stem.rsplit("_", 1)[0] == prefix}
        assert len(shapes) == 1, (prefix, shapes)
    assert _read("crouch_0").shape == _read("rise_0").shape   # 앉기 끝 → 일어나기 첫 장 이어짐


def test_idle_picks_flame_laugh_or_chin_and_returns_to_stand():
    """가만히 서 있으면 대기 불꽃·웃음·턱괴기 셋 중 무작위(서기 → 서기). 클릭 대사 '불꽃' 줄은 불꽃 때만."""
    assert SB.idle_states == ("flame", "laugh", "chin")
    seen = set()
    for seed in range(30):
        b = br.Brain(br.Floor(0, 2000, 700), rng=random.Random(seed), profile=SB)
        b.pos = (1000.0, 700.0)
        b._next_walk, b._next_idle, b._next_rare = 1e9, 1e9, 1e9
        b._next_extra = 0.01
        t = 0.0
        while t < 0.3:
            t += 0.05
            b.tick(t, False)
        seen.add(b.state)
        while t < 4.0:
            t += 0.05
            b.tick(t, False)
        assert b.state == "stand"
    assert seen == {"flame", "laugh", "chin"}
    b = br.Brain(br.Floor(0, 2000, 700), rng=random.Random(1), profile=SB)
    b.pos = (1000.0, 700.0)
    b._go("laugh", 1.0)
    b._extra_until = 5.0
    b.press(1.0, 1000, 600)
    assert b.release(1.0)[-1] == ("say", "click_stand")


def test_sneeze_bubble_on_frame_22_and_sit_loop_ping_pong():
    assert SB.rare_say == (22, "sneeze") and len(SB.anims["sneeze"][0]) == 30
    sit = SB.anims["sit_loop"][0]
    assert sit[0] == "crouch_16" and "crouch_29" in sit and sit[-1] == "crouch_17"   # 16→29→17, 다시 16(이음매 없음)
    assert SB.anims["crouch"][0][-1] == "crouch_15"


def test_talk_mouth_only_frames_keep_one_body():
    """말하기: 입 다문 몸(talk_base = 영상 10번)에 작은 입·큰 입만 — 입 둘레 밖은 똑같고, 입은 달라야 함(몸 튐 없음)."""
    base = _read("talk_base_0")
    for key in ("m1", "m2"):
        other = _read(f"talk_{key}_0")
        assert other.shape == base.shape
        diff = np.abs(other.astype(int) - base.astype(int)).max(-1) > 3
        ys, xs = np.nonzero(diff)
        assert diff.sum() > 40, key
        assert 80 <= xs.min() and xs.max() <= 130 and 100 <= ys.min() and ys.max() <= 140, (key, xs.min(), xs.max(), ys.min(), ys.max())
    assert (_read("talk_blink_0") == base).all()   # 영상에 깜빡이는 장 없음 → base 그대로


def test_motion_frames_thirty_and_hold():
    flame, hat = mo.MOTIONS["Starline"]
    assert (flame.count, flame.frame, flame.hold) == (30, 0.1, ((9, 1.0),))
    assert (hat.count, hat.frame, hat.hold) == (30, 0.1, ((7, 1.0),))


def test_lazy_frames_keep_memory_close_to_other_characters():
    """350장을 다 풀면 72MB(+화면용 사본) → 늘 쓰는 장(서기·걷기·말하기)만 미리, 나머지는 최근 40장만 — 모든 동작을 다 돌려도
    원본 + 화면용 합 약 29MB(다른 캐릭터 16~24MB). 다른 캐릭터는 예전처럼 다 읽음(dict)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from mabinogi_addon.ui import pet_window as pw

    frames = pw.load_frames("Starline", SB)
    assert isinstance(frames, pw.LazyFrames) and len(frames) == len(_used())
    assert {f"stand_{i}" for i in range(30)} | {f"walk_{i}" for i in range(14)} <= frames.pinned
    assert "laugh_3" in frames and "nope" not in frames and frames.get("nope") is None
    w = pw.PetWindow(br.Brain(br.Floor(0, 1600, 700), profile=SB), frames, "#3A0729")
    try:
        for name in list(frames):
            assert w._image(name) is not None, name
        size = sum(frames[n].sizeInBytes() for n in frames.loaded()) + sum(i.sizeInBytes() for i in w._scaled.values())
        assert len(frames.loaded()) <= len(frames.pinned) + pw.LAZY_KEEP
        assert size / 2 ** 20 < 40, size / 2 ** 20
        assert w._image("laugh_0") is not None   # 버린 장도 다시 읽힘
    finally:
        w.close()
    assert isinstance(pw.load_frames("다래", br.DARE), dict)


def test_anchors_put_each_action_on_the_stand_feet():
    """동작 틀마다 발 자리가 달라 바뀔 때 튐(QA식 측정 11-27) → anchors.json: 쓰다듬기 +7·모자 마술 +5(옆), 앉기·일어나기 +10·
    착지 (+2, +13)(아래). 그린 뒤 서 있는 발 아래 끝이 서기와 2px 안."""
    import json

    anchors = json.loads((SL / "anchors.json").read_text(encoding="utf-8"))
    for name in ("pet_0", "motion_hat_magic_0", "crouch_0", "rise_29", "land_29"):
        assert name in anchors, name

    def foot_bottom(name):
        a = _read(name)[..., 3] > 40
        return a.shape[0] - 1 - np.nonzero(a.any(1))[0].max() - anchors.get(name, (0, 0))[1]   # 그린 뒤 바닥과의 틈

    for name in ("stand_0", "crouch_0", "rise_29", "land_29", "pet_0", "motion_hat_magic_0"):
        assert abs(foot_bottom(name)) <= 2, (name, foot_bottom(name))
    assert all(abs(v) < 200 for xy in anchors.values() for v in xy)


def test_stand_mouth_stays_closed_grin():
    """사용자 11-27(QA 전달) '가만히 서 있는데 입이 말하듯 움직임': 서 있기 30장 입을 0번(다문 웃음) 하나로 — 얼굴로 맞춘
    입 상자(머리가 숨쉬며 ~6px 오르내려 고정 상자는 옷깃이 들어옴)의 어두운 픽셀 수 범위 ≤ 15, 입 상자가 0번과 거의 같음."""
    from scripts.build_starline_video import MOUTH_BOX, face_shift

    stand = [_read(f"stand_{i}") for i in range(30)]
    x, y, w, h = MOUTH_BOX
    counts, diffs = [], []
    ref = stand[0][y:y + h, x:x + w, :3].astype(int)
    inner = np.zeros((h, w), bool)
    cv2.ellipse(inner.view(np.uint8), (w // 2, h // 2), (w // 2 - 6, h // 2 - 6), 0, 0, 360, 1, -1)
    for im in stand:
        dx, dy = face_shift(stand[0], im)
        box = im[y + dy:y + dy + h, x + dx:x + dx + w, :3]
        counts.append(int((cv2.cvtColor(np.ascontiguousarray(box), cv2.COLOR_BGR2GRAY) < 90).sum()))
        diffs.append(min(float(np.abs(im[y + dy + j:y + dy + j + h, x + dx + i:x + dx + i + w, :3].astype(int) - ref)[inner].mean())
                         for i in (-1, 0, 1) for j in (-1, 0, 1)))   # 저장(WebP) 뒤 다시 잰 맞춤은 ±1px 흔들림
    assert max(counts) - min(counts) <= 15, counts
    assert max(diffs) <= 8, [round(d, 1) for d in diffs]
