"""캐릭터 알파(docs/character-pet-spec.md) — 호감도 규칙·대사·펫 상태 전환·캡처 제외·캐릭터 탭."""
import datetime
import json
import os
import random
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, paths
from mabinogi_addon.character import affinity as aff
from mabinogi_addon.character import brain as br
from mabinogi_addon.character import lines as ln
from mabinogi_addon.character import roster

ASSETS = paths.resource_dir() / "characters"
DAY = "2026-11-24"


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "LOCAL_CONFIG_PATH", path)
    real_read, real_write = config._read_local_config, config._write_local_config
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: real_read(path))
    monkeypatch.setattr(config, "_write_local_config", lambda data, *a, **k: real_write(data, path))
    return path


# ---- 호감도(명세 3절 3번) ------------------------------------------------------------------------
def test_daily_full_is_twenty_and_each_action_has_its_own_limit():
    a = aff.Affinity()
    got = [a.gain("launch", DAY) for _ in range(2)]
    got += [a.gain("pet", DAY) for _ in range(4)]
    got += [a.gain("alert", DAY) for _ in range(9)]
    got += [a.gain("corner", DAY) for _ in range(6)]
    assert got == [3, 0] + [2, 2, 2, 0] + [1] * 7 + [0, 0] + [1] * 4 + [0, 0]
    assert a.value == a.gained == 20  # 3 + 6 + 7 + 4 = 하루 상한
    assert a.stage == 0


def test_daily_cap_and_100_ceiling_and_midnight_reset():
    a = aff.Affinity(aff.Rules(daily_cap=4))
    assert [a.gain("launch", DAY), a.gain("pet", DAY)] == [3, 1]  # 상한 4에서 잘림
    assert a.gain("alert", DAY) == 0
    a.gain("alert", "2026-11-25")  # 자정 지남 → 오늘 횟수·오른 양 초기화, 값은 그대로
    assert a.value == 5 and a.gained == 1 and a.counts == {"alert": 1}
    b = aff.Affinity(value=99)
    assert b.gain("launch", DAY) == 1 and b.value == 100 and b.stage == 100


def test_repeat_clicks_penalty_once_a_minute_never_below_zero():
    a = aff.Affinity(value=1)
    assert [a.click(t) for t in (0, 1, 2, 3)] == [False] * 4
    assert a.click(4) is True and a.value == 0  # 10초 안 5번 → −1
    assert not any(a.click(5 + t) for t in range(5))  # 1분 안엔 다시 안 내림
    assert a.value == 0
    assert [a.click(100 + t) for t in range(5)][-1] is True and a.value == 0  # 0 아래로 안 내려감
    c = aff.Affinity(value=5)
    assert not any(c.click(t * 3) for t in range(10))  # 3초 간격(10초 안 4번)은 반복 아님


def test_petting_after_daily_three_is_annoyed():
    a = aff.Affinity(value=10)
    assert [a.petted(t, DAY) for t in (0, 1, 2)] == ["gain"] * 3 and a.value == 16
    assert a.petted(3, DAY) == "annoyed" and a.value == 15
    assert a.petted(10, DAY) == "none" and a.value == 15  # 1분에 한 번만


def test_rules_are_settings_values_and_state_round_trips():
    rules = aff.Rules.from_dict({"alert_times": 9, "penalty_gap": 30, "daily_cap": True, "unknown": 1, "pet": -2})
    assert rules.alert_times == 9 and rules.penalty_gap == 30.0 and rules.daily_cap == 20 and rules.pet == 2
    a = aff.Affinity(rules)
    a.gain("alert", DAY)
    b = aff.Affinity.load(json.loads(json.dumps(a.to_dict())), rules)
    assert (b.value, b.day, b.gained, b.counts) == (1, DAY, 1, {"alert": 1})
    assert aff.Affinity.load({"value": 500, "counts": {"x": 1, "pet": "2"}}).value == 100


# ---- 대사 --------------------------------------------------------------------------------------
def test_builtin_lines_cover_every_situation_and_every_quiet_voice_alert():
    data = ln.read(ASSETS / "다래" / "lines.json")
    assert set(ln.SITUATIONS) <= set(data.lines)
    sounds = {p.name for p in (paths.resource_dir() / "sounds" / "조용한 여성").glob("*.mp3")}
    assert sounds and sounds <= set(data.alerts)
    assert data.alerts["비바체 연장.mp3"] == "비바체… 잊은 거 아니지…?"


def test_picker_is_random_but_never_repeats_the_same_line_in_a_row():
    picker = ln.Picker(ln.parse(json.dumps({"schemaVersion": 1, "character": "다래",
                                            "lines": {"idle": ["가", "나", "다"], "one": ["하나"]}}).encode()),
                       random.Random(1))
    seq = [picker.pick("idle") for _ in range(200)]
    assert all(a != b for a, b in zip(seq, seq[1:])) and set(seq) == {"가", "나", "다"}
    assert picker.pick("one") == picker.pick("one") == "하나"  # 한 줄뿐이면 그 줄
    assert picker.pick("missing") is None


def test_lines_parse_drops_bad_lines_and_rejects_bad_files():
    data = ln.parse(json.dumps({"schemaVersion": 1, "character": "다래",
                                "lines": {"a": ["좋아", "x" * 31, "\x07", 3], "b": []},
                                "alerts": {"a.mp3": "알림", "b.mp3": "y" * 40}}).encode())
    assert data.lines == {"a": ("좋아",)} and data.alerts == {"a.mp3": "알림"}
    for bad in (b"[]", b'{"schemaVersion": 2}', b'{"schemaVersion": true, "character": "a", "lines": {"a": ["b"]}}',
                b"x" * (ln.MAX_BYTES + 1)):
        with pytest.raises(ValueError):
            ln.parse(bad)


# ---- 펫 상태 전환(명세 2절 표) ----------------------------------------------------------------------
def _brain(**kw):
    b = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(3), **kw)
    b.pos = (300.0, 700.0)
    return b


def _run(b, t0, seconds, front, step=0.05):
    events, t = [], t0
    while t < t0 + seconds:
        t += step
        events += b.tick(t, front)
    return t, events


def test_every_animation_frame_exists_in_assets():
    names = {n for frames, _t, _l in br.ANIMS.values() for n in frames}
    missing = [n for n in names if not (ASSETS / "다래" / f"{n}.png").exists()]
    assert not missing


def test_game_front_walks_to_corner_crouches_and_dozes_then_rises_when_game_goes_back():
    b = _brain(corner=(900.0, 700.0))
    t, events = _run(b, 0, 0.5, False)
    t, events = _run(b, t, 4.5, True)
    assert ("say", "game_enter") in events and b.pos == (900.0, 700.0)
    assert b.state in br.SITTING
    t, _ = _run(b, t, 6, True)
    assert b.state == "sit_doze" and b.zzz()  # 졸림 5초 → 꾸벅 졸기(Zzz)
    t, events = _run(b, t, 2, False)
    assert ("say", "game_exit") in events and b.state in ("rise", "stand", "walk")
    assert not b.zzz()


def test_brief_focus_change_does_not_move_the_pet():
    b = _brain()
    t, _ = _run(b, 0, 0.5, True)  # 1초 안 짧은 전환은 무시
    t, _ = _run(b, t, 0.5, False)
    assert b._goal == "roam"


def test_clicks_surprise_standing_notice_sitting_and_wake_dozing():
    b = _brain()
    b.press(1, 300, 600)
    assert b.release(1) == [("click",), ("say", "click_stand")] and b.state == "surprise"
    b._go("sit_drowsy", 2)
    b.press(2, 300, 640)
    assert b.release(2)[-1] == ("say", "click_sit") and b.state == "sit_notice"
    b._go("sit_doze", 3)
    b.press(3, 300, 640)
    assert b.release(3)[-1] == ("say", "click_sleep") and b.state == "wake"
    _run(b, 3, 2, False)
    assert b.state in ("stand", "walk")  # 깜짝 깨어 일어나 서 있기


def test_drag_then_drop_falls_lands_and_gets_up():
    b = _brain()
    b.press(0, 300, 600)
    b.move(0.1, 303, 602)
    assert not b.dragging()  # 6px 안 움직임은 아직 클릭
    b.move(0.2, 400, 300)
    assert b.dragging() and b.state == "drag" and b.pos == (400.0, 400.0)
    assert b.release(0.3) == [] and b.state == "fall"
    t, events = _run(b, 0.3, 1.0, False)
    assert b.pos[1] == 700 and ("say", "dropped") in events
    _run(b, t, 3, False)
    assert b.state in ("stand", "walk")


def test_drop_while_game_is_front_saves_new_corner_and_sits_there():
    b = _brain()
    t, _ = _run(b, 0, 1.2, True)
    x, y = b.pos
    b.press(t, x, y - 100)
    b.move(t, 120, 200)
    events = b.release(t)
    assert events[0] == ("corner_saved", 120.0, 300.0) and b.corner == (120.0, 300.0)
    _run(b, t, 3, True)
    assert b.state in br.SITTING and b.pos == (120.0, 300.0)


def test_rubbing_head_pets_and_releasing_completes():
    b = _brain()
    t, events = 1.0, []
    for i in range(8):
        t += 0.1
        events += b.hover(t, 300 + (10 if i % 2 else -10), True)
    assert ("say", "pet_start") in events and b.state == "pet_in"
    for i in range(30):  # 문지르는 동안 반복
        t += 0.1
        b.hover(t, 300 + (10 if i % 2 else -10), True)
        events += b.tick(t, False)
    assert b.state == "pet_loop" and ("say", "pet_during") in events
    t, events = _run(b, t, 1.2, False)  # 손 뗌
    assert ("pet_done",) in events and ("say", "pet_end") in events and b.state == "pet_out"


def test_hover_below_head_or_while_sitting_does_not_pet():
    b = _brain()
    assert not any(b.hover(1 + i * 0.1, 300 + (10 if i % 2 else -10), False) for i in range(8))
    b._go("sit_drowsy", 2)
    assert not any(b.hover(3 + i * 0.1, 300 + (10 if i % 2 else -10), True) for i in range(8))


def test_corner_time_event_every_thirty_minutes_while_sitting_in_game():
    b = _brain(corner=(300.0, 700.0))
    t, _ = _run(b, 0, 2, True)
    t, events = _run(b, t, 1800, True, step=0.5)
    assert events.count(("corner_time",)) == 1


def test_alert_notice_pose():
    b = _brain()
    b.notify(1)
    assert b.state == "alert"
    b._go("sit_half", 2)
    b.notify(2)
    assert b.state == "sit_notice"


# ---- 창·탭·연결 ---------------------------------------------------------------------------------
def test_pet_window_is_excluded_from_capture_and_takes_no_focus(app, monkeypatch):
    from PySide6.QtCore import Qt

    from mabinogi_addon.system import capture_exclusion
    from mabinogi_addon.ui import overlay_capture
    from mabinogi_addon.ui.pet_window import PetWindow, load_frames

    calls = []
    monkeypatch.setattr(capture_exclusion, "available", lambda: True)
    monkeypatch.setattr(capture_exclusion, "set_excluded", lambda hwnd, on: calls.append(on) or True)
    assert "PetWindow" in overlay_capture.OVERLAYS
    w = PetWindow(_brain(), load_frames("다래"), roster.DARE.color)
    try:
        assert overlay_capture.is_overlay(w)
        w.show()
        app.processEvents()
        assert True in calls  # 뜨자마자 판독 캡처에서 뺌
        flags = w.windowFlags()
        assert flags & Qt.WindowType.WindowDoesNotAcceptFocus and flags & Qt.WindowType.WindowStaysOnTopHint
        assert w.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    finally:
        w.close()


def test_pet_window_draws_figure_190px_and_follows_feet(app):
    from mabinogi_addon.ui.pet_window import FOOT, WIN_H, PetWindow, load_frames

    clock = [5.0]
    b = _brain()
    w = PetWindow(b, load_frames("다래"), roster.DARE.color, clock=lambda: clock[0])
    try:
        w.grab()
        assert round(w._sprite.height()) == br.FIGURE_H  # 서 있을 때 키 190
        assert (w.x() + w.width() / 2, w.y() + WIN_H - FOOT) == b.pos
        w.say("응… 안녕.")
        assert w.bubble() == "응… 안녕."
        clock[0] += 10
        w.step()
        assert w.bubble() is None
    finally:
        w.close()


def test_sound_listener_raises_affinity_and_notices_only_for_chosen_voice(app, cfg, monkeypatch):
    from mabinogi_addon.ui import character_controller as cc
    from mabinogi_addon.ui import notifier

    config.save_voice_pack("조용한 여성")
    ctrl = cc.CharacterController()
    try:
        sounds = paths.resource_dir() / "sounds"
        notifier._announce("vivace", sounds / "조용한 여성" / "비바체 연장.mp3")
        notifier._announce("vivace", sounds / "비바체 연장.mp3")  # 기본 녹음 — 다른 목소리
        notifier._announce("preview", sounds / "조용한 여성" / "투아림 부스트 발동 직전.mp3")  # 미리듣기
        assert ctrl.affinity.value == 1
        assert config.load_affinity("조용한 여성")["counts"] == {"alert": 1}
    finally:
        ctrl.shutdown()
    notifier._announce("vivace", sounds / "조용한 여성" / "비바체 연장.mp3")
    assert ctrl.affinity.value == 1  # 끈 뒤엔 안 받음


def test_launch_bonus_once_a_day_and_greeting(app, cfg):
    from mabinogi_addon.ui import character_controller as cc

    config.save_voice_pack("조용한 여성")
    ctrl = cc.CharacterController()
    try:
        now = datetime.datetime(2026, 11, 24, 13, 0)
        ctrl.start(now)
        ctrl.start(now)
        assert ctrl.affinity.value == 3 and config.load_pet_last_seen() == "2026-11-24"
    finally:
        ctrl.shutdown()
    g = cc.greeting
    assert g("2026-11-24", now) is None
    assert g("2026-11-20", now) == "hello_long" and g("2026-11-23", now) == "hello"
    assert g("2026-11-23", datetime.datetime(2026, 11, 24, 2)) == "night"
    assert g("", datetime.datetime(2026, 11, 24, 7)) == "morning"


def test_character_tab_cards_choose_voice_and_toggle_pet(app, cfg, monkeypatch):
    from mabinogi_addon.ui import character_tab as ct

    played = []
    monkeypatch.setattr(ct.CharacterTab, "_play_sample", lambda self: played.append(config.load_voice_pack()))
    tab = ct.CharacterTab()
    changed, toggled = [], []
    tab.voice_pack_changed.connect(lambda: changed.append(1))
    tab.pet_toggled.connect(toggled.append)
    assert [c.character.name for c in tab.cards] == ["다래", "???", "???", "???", "???"]
    assert not any(c.selected() for c in tab.cards)  # 기본 녹음 — 고른 카드 없음
    tab.cards[3].clicked.emit(tab.cards[3].character)  # 미정 카드도 그 목소리로 선택
    assert config.load_voice_pack() == "화난 여성" and played == ["화난 여성"] and changed == [1]
    assert [c.selected() for c in tab.cards] == [False, False, False, True, False]
    tab.choose(roster.DARE)
    assert tab.cards[0].selected() and "돌아다녀요" in tab.pet_hint.text()
    tab.pet_switch.setChecked(True)
    assert toggled == [True] and config.load_pet_on() is True
    tab.grab()


def test_tab_min_width_is_96_for_seven_tabs():
    from mabinogi_addon.ui import main_window

    assert "min-width: 96px" in main_window._tab_qss(True) and "104px" not in main_window._tab_qss(False)


def test_settings_tab_no_longer_has_voice_choice():
    source = (Path(__file__).resolve().parents[1] / "src/mabinogi_addon/ui/settings_tab.py").read_text(encoding="utf-8")
    assert "list_voice_packs" not in source and "알림 음량" in source


def test_frame_sizes_match_standing_height():
    from mabinogi_addon.image_io import imread
    import cv2

    stand = imread(ASSETS / "다래" / "stand_0.png", cv2.IMREAD_UNCHANGED)
    walk = [imread(p, cv2.IMREAD_UNCHANGED).shape[0] for p in sorted((ASSETS / "다래").glob("walk_*.png"))]
    assert stand.shape[0] == 285 and all(abs(h - 285) <= 3 for h in walk)  # 서 있는 키로 맞춤(시트마다 머리 크기 달라도)
