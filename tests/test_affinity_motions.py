"""호감도 모션(25·75 보상 — docs/characters/호감도_모션.md '앱 동작', 11-26 게이지 배포)."""
import os
import random

import cv2
import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mabinogi_addon import image_io, paths  # noqa: E402
from mabinogi_addon.character import brain as br  # noqa: E402
from mabinogi_addon.character import motions as mo  # noqa: E402
from scripts.silhouette import best_scale  # noqa: E402

CHARS = paths.resource_dir() / "characters"
FOLDERS = {"아리아": br.ARIA, "다래": br.DARE, "레나": br.LENA, "이안": br.IAN, "Starline": br.STARLINE}
STAND = {"이안": "stand_1"}


def _read(path):
    image = image_io.imread(path, cv2.IMREAD_UNCHANGED)
    assert image is not None, path
    return image


def _head(frame):
    ys, xs = np.where(frame[..., 3] > 128)
    tight = frame[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return tight[:round(tight.shape[0] * 0.42)]


# ---- 그림 ------------------------------------------------------------------------------------
@pytest.mark.parametrize("folder", list(FOLDERS))
def test_base_motion_frames_exist_for_25_and_75_with_standing_head(folder):
    assert [m.stage for m in mo.of(folder)] == [25, 75]
    stand = _head(_read(CHARS / folder / f"{STAND.get(folder, 'stand_0')}.png"))
    for m in mo.of(folder):
        for name in m.names():
            k = best_scale(stand, _head(_read(CHARS / folder / f"{name}.png")), 0.8, 1.25, 91)
            assert 0.95 <= k <= 1.05, (name, k)


# ---- 순서·해금 --------------------------------------------------------------------------------
def test_sequence_start_loop_end():
    rng = random.Random(1)
    water = mo.MOTIONS["아리아"][0]
    for _ in range(20):
        names = [n for n, _d in water.sequence(rng)]
        assert names[:2] == ["motion_water_0", "motion_water_1"] and names[-4:] == [f"motion_water_{i}" for i in range(4, 8)]
        assert len(names) - 6 in (4, 6)                       # 반복 구간(2장) 2~3번
    tidy = mo.MOTIONS["이안"][0]
    assert [n for n, _d in tidy.sequence(rng)] == list(tidy.names())   # 반복 설명 없음 → 한 번
    float_sit = mo.MOTIONS["레나"][1]
    total = sum(d for _n, d in float_sit.sequence(rng))
    assert 10.0 - 3 * mo.FRAME <= total - 5 * mo.FRAME <= 20.0 + 3 * mo.FRAME     # 공중 앉기 반복 10~20초(한 바퀴 단위로 반올림)


def test_unlocked_by_stage_new_one_double_and_needs_frames():
    frames = mo.frame_names("아리아")
    assert mo.unlocked("아리아", 0, frames) == {}
    assert mo.unlocked("아리아", 25, frames) == {"motion_water": 2.0}
    assert mo.unlocked("아리아", 75, frames) == {"motion_water": 1.0, "motion_wreath": 2.0}
    assert mo.unlocked("아리아", 75, frames - {"motion_wreath_3"}) == {"motion_water": 1.0}   # 옷에 그림이 없으면 빠짐
    assert mo.unlocked("???", 100, frames) == {}


# ---- 펫 동작 ---------------------------------------------------------------------------------
def _brain(profile=br.DARE, seed=2, stage=25, folder="다래"):
    b = br.Brain(br.Floor(0, 1920, 1000), rng=random.Random(seed), profile=profile)
    b.pos = (900.0, 1000.0)
    weights = mo.unlocked(folder, stage, mo.frame_names(folder))
    b.set_motions({m.key: m for m in mo.of(folder) if m.key in weights}, weights)
    return b


def _run(b, seconds, start=0.0, game=False, dt=0.05, every=None):
    states, t = [], start
    while t < start + seconds:
        b.tick(t, game)
        if every:
            every(b, t)
        states.append((b.state, b.motion_key if b.state == "motion" else None))
        t += dt
    return states


def test_no_motion_before_unlock():
    b = _brain(stage=0)
    assert "motion" not in {s for s, _k in _run(b, 600)}


def test_unlocked_motion_shows_up_while_standing_and_ends_standing():
    b = _brain(stage=25)
    states = _run(b, 900)
    assert ("motion", "motion_sheep_doll") in states
    i = next(i for i, s in enumerate(states) if s[0] == "motion")
    after = next(s for s in states[i:] if s[0] != "motion")
    assert after[0] in ("stand", "walk")


def test_ian_idle_mixes_watch_and_motions_new_one_twice():
    b = _brain(br.IAN, seed=4, stage=75, folder="이안")
    picks = {"watch": 0, "motion_tidy": 0, "motion_tea": 0}
    for _ in range(3000):
        b.state, b._goal = "stand", "roam"
        b._pick_idle(0.0)
        picks[b.motion_key if b.state == "motion" else b.state] += 1
    assert picks["motion_tea"] > picks["motion_tidy"] * 1.6 and picks["motion_tea"] > picks["watch"] * 1.6


@pytest.mark.parametrize("interrupt", ["click", "drag", "talk", "game"])
def test_motion_stops_at_once(interrupt):
    b = _brain(stage=25)
    b.state, b._goal = "stand", "roam"
    assert b.play_motion("motion_sheep_doll", 1.0)
    if interrupt == "click":
        b.press(1.1, 900, 950)
        b.release(1.2)
        assert b.state == "surprise"
    elif interrupt == "drag":
        b.press(1.1, 900, 950)
        b.move(1.2, 960, 900)
        assert b.state == "drag"
    elif interrupt == "talk":
        assert b.talk(1.2, 10)
        assert b.state != "motion"
    else:
        _run(b, 3, start=1.2, game=True)
        assert b.state != "motion" and b._goal == "corner"


def test_no_motion_in_corner_and_stage_up_motion_waits_for_line():
    b = _brain(stage=25)
    _run(b, 30, game=True)
    assert b.state in b.profile.sitting and not b.play_motion("motion_sheep_doll", 30.0)
    states = _run(b, 600, start=30.0, game=True)
    assert "motion" not in {s for s, _k in states}
    c = _brain(stage=25)
    c.state, c._goal = "stand", "roam"
    c.talk(0.0, 12)                                  # 구간 오름 대사 중
    c.show_motion("motion_sheep_doll", 0.1)
    assert c.state != "motion"
    states = _run(c, 10, start=0.2)
    assert ("motion", "motion_sheep_doll") in states   # 말이 끝나고 서면 바로


# ---- 창·컨트롤러 -----------------------------------------------------------------------------
@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_load_frames_takes_motions_only_from_worn_outfit(app, tmp_path, monkeypatch):
    from PySide6.QtGui import QImage

    from mabinogi_addon.ui import pet_window
    root = tmp_path / "res"
    base = root / "characters" / "다래"
    (base / "outfits" / "plain").mkdir(parents=True)
    img = QImage(4, 4, QImage.Format.Format_ARGB32)
    img.fill(0xFF00FF00)
    for name in ("stand_0", "motion_sheep_doll_0"):
        img.save(str(base / f"{name}.png"))
    monkeypatch.setattr(pet_window.paths, "resource_dir", lambda: root)
    assert "motion_sheep_doll_0" in pet_window.load_frames("다래", br.DARE)
    assert "motion_sheep_doll_0" not in pet_window.load_frames("다래", br.DARE, "plain")   # 옷에 없으면 빠짐(기본 옷 것으로 안 대신)


def test_controller_stage_up_unlocks_and_shows_motion(app, tmp_path, monkeypatch):
    from mabinogi_addon import config
    from mabinogi_addon.ui import character_controller as cc
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "LOCAL_CONFIG_PATH", path)
    real_read, real_write = config._read_local_config, config._write_local_config
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: real_read(path))
    monkeypatch.setattr(config, "_write_local_config", lambda data, *a, **k: real_write(data, path))
    config.save_voice_pack("조용한 여성")
    config.save_character(pet=True, affinity=("조용한 여성", {"rules": 2, "value": 10}))
    ctrl = cc.CharacterController()
    ctrl.set_enabled(True)
    ctrl.start()
    try:
        w = ctrl.window
        assert w is not None and w.brain.motions == {}
        shown = []
        monkeypatch.setattr(w.brain, "show_motion", lambda key, now: shown.append(key))
        config.save_character(affinity=("조용한 여성", {"rules": 2, "value": 25, "cleared": 1}))
        ctrl.reload_affinity()
        assert set(w.brain.motions) == {"motion_sheep_doll"} and w.brain.motion_weights == {"motion_sheep_doll": 2.0}
        assert shown == ["motion_sheep_doll"]
    finally:
        ctrl.shutdown()
        if ctrl.window is not None:
            ctrl.window.close()


def test_creator_motion_buttons_play_now(app, tmp_path, monkeypatch):
    """기획 11-26: 제작자 '모션 바로 보기' — 지금 캐릭터·옷에 그림이 있는 모션 버튼, 누르면 펫이 바로 한 번(해금 무관)."""
    from PySide6.QtWidgets import QPushButton

    from mabinogi_addon import config
    from mabinogi_addon.ui import character_controller as cc
    from mabinogi_addon.ui import character_tab as ct
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "LOCAL_CONFIG_PATH", path)
    real_read, real_write = config._read_local_config, config._write_local_config
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: real_read(path))
    monkeypatch.setattr(config, "_write_local_config", lambda data, *a, **k: real_write(data, path))
    config.save_voice_pack("조용한 여성")
    config.save_character(pet=True)
    tab = ct.CharacterTab()
    buttons = lambda: [b.text() for b in tab.motion_box.findChildren(QPushButton)]  # noqa: E731
    assert tab.motion_box.isHidden() and buttons() == []          # 비제작자는 없음
    tab.set_creator(True)
    assert buttons() == ["♥ 25 모션", "♥ 75 모션"]
    ctrl = cc.CharacterController()
    ctrl.set_enabled(True)
    ctrl.start()
    tab.motion_requested.connect(ctrl.preview_motion)
    try:
        brain = ctrl.window.brain
        brain.state, brain._goal = "stand", "roam"
        next(b for b in tab.motion_box.findChildren(QPushButton) if b.text() == "♥ 75 모션").click()
        assert brain.state == "motion" and brain.motion_key == "motion_bubbles"   # 75 해금 전이어도 바로
    finally:
        ctrl.shutdown()
        if ctrl.window is not None:
            ctrl.window.close()


def test_sheep_doll_hug_frame_holds():
    """사용자 11-26: 다래 양인형 — 6번(안아 올림) 2.1초 머문 뒤 7번(서 있기). 반복 구간 규칙은 그대로."""
    sheep = mo.MOTIONS["다래"][0]
    seq = sheep.sequence(random.Random(1))
    assert seq[-2] == ("motion_sheep_doll_6", 2.1) and seq[-1] == ("motion_sheep_doll_7", mo.FRAME)
    loop = [n for n, _d in seq[2:-4]]
    assert len(loop) in (4, 6) and set(loop) == {"motion_sheep_doll_2", "motion_sheep_doll_3"}
    assert all(d == mo.FRAME for n, d in seq if n != "motion_sheep_doll_6")
