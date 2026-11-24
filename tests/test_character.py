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


# ---- 호감도(명세 3절 3번 — 사용자 최종 규칙 11-24 c8797ef) ----------------------------------------
def test_daily_full_is_ten_and_each_action_has_its_own_limit():
    a = aff.Affinity()
    got = [a.launched(DAY), a.launched(DAY)]
    got += [a.gain("pet", DAY) for _ in range(4)]
    got += [a.alerted(DAY) for _ in range(5)]
    got += [a.corner_minute(DAY) for _ in range(120)]
    assert got[:11] == [2, 0, 1, 1, 1, 0, 1, 1, 1, 0, 0]
    assert sum(got[11:]) == 2 and got[11 + 29] == 1 and got[11 + 59] == 1  # 30분마다 +1, 하루 2번
    assert a.value == a.gained == 10  # 2 + 3 + 3 + 2 = 하루 상한
    assert a.totals == {"alerts": 5, "corner_minutes": 120} and a.streak == 1


def test_stops_at_segment_end_until_quest_then_continues():
    a = aff.Affinity(value=24)
    a.alerted(DAY)
    a.alerted(DAY)
    assert a.value == 25 and a.stage == 0 and a.cleared == 0  # 25에서 멈춤(0→25 퀘스트 = 처음 쓰다듬기 아직)
    assert a.quest_text() == "퀘스트: 처음 쓰다듬기 · 0/1번"
    assert a.petted(1, DAY) == "gain"  # 쓰다듬기 퀘스트 깸 → 다음 구간, 그 +1이 이어서 쌓임
    assert a.cleared == 1 and a.stage == 25 and a.value == 26
    assert a.quest_text() == "퀘스트: 구석에서 함께 1시간 · 0/60분"


def test_quest_progress_counts_ahead_and_unlocks_on_arrival():
    a = aff.Affinity()
    a.totals = {"pets": 1, "corner_minutes": 75}  # 미리 깨 둔 두 퀘스트
    a.value = 49
    a._settle()
    assert a.cleared == 1 and a.value == 49  # 25를 넘은 값 + 미리 깬 쓰다듬기 → 25→50 구간
    a.gain("launch", DAY)
    assert a.value == 51 and a.cleared == 2  # 50 도착 즉시 미리 깬 구석 60분으로 넘어가 이어 쌓임
    d = aff.Affinity(value=49)
    d.gain("launch", DAY)
    assert d.value == 25 and d.cleared == 0  # 퀘스트 없이 저장된 값은 구간 끝으로 맞춤
    b = aff.Affinity.load({"value": 50, "cleared": 1, "totals": {"pets": 1, "corner_minutes": 75}})
    assert b.cleared == 2 and b.stage == 50 and "목소리 알림 10번 · 0/10번" in b.quest_text()
    c = aff.Affinity.load({"value": 75, "cleared": 3, "streak": 6})
    assert c.quest_text() == "퀘스트: 7일 연속 켜기 · 6/7일"


def test_launch_streak_counts_consecutive_days_and_resets_on_gap():
    a = aff.Affinity()
    for d in ("2026-11-20", "2026-11-21", "2026-11-22"):
        a.launched(d)
    assert a.streak == 3
    a.launched("2026-11-22")
    assert a.streak == 3  # 같은 날 다시 켜도 그대로
    a.launched("2026-11-24")
    assert a.streak == 1  # 하루 빠짐 → 다시 1일


def test_hundred_needs_seven_day_streak_quest():
    a = aff.Affinity.load({"value": 99, "cleared": 3, "streak": 6, "lastLaunch": "2026-11-23"})
    a.alerted(DAY)
    assert a.value == 100 and a.stage == 75  # 100에 닿았지만 7일 연속 퀘스트 전
    a.launched(DAY)
    assert a.streak == 7 and a.cleared == 4 and a.stage == 100 and a.quest_text() == "퀘스트: 모두 깼어요"


def test_midnight_reset_keeps_value_and_quest_totals():
    a = aff.Affinity(aff.Rules(daily_cap=3))
    assert [a.launched(DAY), a.gain("pet", DAY), a.alerted(DAY)] == [2, 1, 0]  # 상한 3에서 잘림
    a.alerted("2026-11-25")  # 자정 지남 → 오늘 횟수·오른 양 초기화
    assert a.value == 4 and a.gained == 1 and a.counts == {"alert": 1} and a.totals == {"alerts": 2}


def test_repeat_penalty_once_a_minute_never_below_zero_or_segment_start():
    a = aff.Affinity(value=1)
    assert [a.click(t) for t in (0, 1, 2, 3)] == [False] * 4
    assert a.click(4) is True and a.value == 0  # 10초 안 5번 → −1
    assert not any(a.click(5 + t) for t in range(5))  # 1분 안엔 다시 안 내림
    assert [a.click(100 + t) for t in range(5)][-1] is True and a.value == 0  # 0 아래로 안 내려감
    b = aff.Affinity.load({"value": 26, "cleared": 1})
    for t in (0, 100, 200):
        for i in range(5):
            b.click(t + i)
    assert b.value == 25  # 지금 구간 시작점(25) 아래로 안 내려감
    c = aff.Affinity(value=5)
    assert not any(c.click(t * 3) for t in range(10))  # 3초 간격(10초 안 4번)은 반복 아님


def test_petting_after_daily_three_is_annoyed():
    a = aff.Affinity.load({"value": 10, "cleared": 0})
    assert [a.petted(t, DAY) for t in (0, 1, 2)] == ["gain"] * 3 and a.value == 13 and a.totals["pets"] == 3
    assert a.petted(3, DAY) == "annoyed" and a.value == 12
    assert a.petted(10, DAY) == "none" and a.value == 12  # 1분에 한 번만


def test_creator_set_value_clears_quests_up_to_that_stage():
    a = aff.Affinity()
    a.set_value(50)
    assert a.cleared == 2 and a.stage == 50 and a.quest_text().startswith("퀘스트: 목소리 알림")
    a.set_value(42)
    assert a.cleared == 1 and a.value == 42
    a.set_value(100)
    assert a.cleared == 4 and a.stage == 100
    a.set_value(0)
    assert a.cleared == 0


def test_rules_are_settings_values_and_state_round_trips():
    rules = aff.Rules.from_dict({"alert_times": 9, "penalty_gap": 30, "daily_cap": True, "unknown": 1, "pet": -2,
                                 "quest_corner_minutes": 90})
    assert rules.alert_times == 9 and rules.penalty_gap == 30.0 and rules.daily_cap == 10 and rules.pet == 1
    a = aff.Affinity(rules)
    a.alerted(DAY)
    a.launched(DAY)
    b = aff.Affinity.load(json.loads(json.dumps(a.to_dict())), rules)
    assert (b.value, b.day, b.gained, b.counts, b.totals, b.streak, b.last_launch) == \
        (3, DAY, 3, {"alert": 1, "launch": 1}, {"alerts": 1}, 1, DAY)
    assert aff.Affinity.load({"value": 500, "counts": {"x": 1, "pet": "2"}}).value == 25
    assert aff.Affinity.load({"value": 30, "cleared": 1}, rules).quest_text() == "퀘스트: 구석에서 함께 90분 · 0/90분"


# ---- 대사 --------------------------------------------------------------------------------------
def test_builtin_lines_cover_every_situation_and_every_quiet_voice_alert():
    data = ln.read(ASSETS / "다래" / "lines.json")
    assert set(ln.SITUATIONS) <= set(data.lines)
    from mabinogi_addon.ui.notifier import alert_files
    sounds = alert_files(paths.resource_dir() / "sounds" / "조용한 여성")
    assert sounds and sounds <= set(data.alerts)
    assert data.alerts["비바체 연장.mp3"] == "비바체… 잊은 거 아니지…?"
    moods = {line.mood for items in data.lines.values() for line in items}
    assert moods == set(ln.MOODS)  # 보통·설명·생각·기쁨 모두 쓰임


def test_picker_is_random_but_never_repeats_the_same_line_in_a_row():
    picker = ln.Picker(ln.parse(json.dumps({"schemaVersion": 1, "character": "다래",
                                            "lines": {"idle": ["가", "나", "다"], "one": ["하나"]}}).encode()),
                       random.Random(1))
    seq = [picker.pick("idle").text for _ in range(200)]
    assert all(a != b for a, b in zip(seq, seq[1:])) and set(seq) == {"가", "나", "다"}
    assert picker.pick("one") == picker.pick("one") == ln.Line("하나")  # 한 줄뿐이면 그 줄
    assert picker.pick("missing") is None


def test_lines_parse_drops_bad_lines_and_rejects_bad_files():
    data = ln.parse(json.dumps({"schemaVersion": 1, "character": "다래",
                                "lines": {"a": ["좋아", "x" * 31, "\x07", 3, {"text": "음…", "mood": "think"},
                                                {"text": "와", "mood": "angry"}, {"mood": "happy"}], "b": []},
                                "alerts": {"a.mp3": "알림", "b.mp3": "y" * 40}}).encode())
    assert data.lines == {"a": (ln.Line("좋아"), ln.Line("음…", "think"), ln.Line("와"))}  # 모르는 분위기 = 보통
    assert data.alerts == {"a.mp3": "알림"}
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


def test_corner_minute_event_every_minute_while_sitting_in_game():
    b = _brain(corner=(300.0, 700.0))
    t, _ = _run(b, 0, 2, True)
    t, events = _run(b, t, 600, True, step=0.5)
    assert events.count(("corner_minute",)) == 10
    t, events = _run(b, t, 120, False, step=0.5)
    assert ("corner_minute",) not in events[4:]  # 게임 밖이면 안 셈


@pytest.mark.parametrize("mood,frames", [
    ("normal", {"talk_small_0", "talk_big_0", "talk_closed_0"}),
    ("explain", {"talk_hand_up_0", "talk_hand_out_0", "talk_point_0"}),
    ("think", {"talk_think_0"}),
    ("happy", {"talk_smile_0"}),
    ("angry", {"talk_small_0", "talk_big_0", "talk_closed_0"}),
])
def test_talking_picks_frames_by_mood_then_closes_mouth(mood, frames):
    b = _brain()
    b._target = (800.0, 700.0)
    b._go("walk", 0)
    assert b.talk(1.0, 10, mood) is True and b._target is None  # 걷다 멈추고 말함
    seen = {b.frame(1.0 + i * 0.05) for i in range(14)}  # 10글자 × 0.07초 = 0.7초 동안
    assert seen == frames
    _run(b, 1.0, 0.75, False)
    assert b.state == "talk_end" and b.frame(1.8) == "talk_end_0"
    _run(b, 1.75, 1.0, False)
    assert b.state in ("stand", "walk")


def test_talking_while_sitting_or_busy_keeps_the_picture():
    b = _brain()
    for state in ("sit_drowsy", "sit_doze", "crouch", "land", "pet_loop", "drag"):
        b._go(state, 1)
        assert b.talk(1, 8, "happy") is False and b.state == state


def test_click_while_talking_is_surprise():
    b = _brain()
    b.talk(1, 20)
    b.press(1.1, 300, 600)
    assert b.release(1.1)[-1] == ("say", "click_stand") and b.state == "surprise"


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
        w.say(ln.Line("응… 안녕.", "happy"))
        assert w.bubble() == "응… 안녕." and w.bubble_shown() == "응"  # 한 글자씩
        assert b.state == "talk_happy" and b.frame(clock[0]) == "talk_smile_0"
        clock[0] += 0.15
        assert w.bubble_shown() == "응… "[:3]
        clock[0] += 1
        w.step()
        assert w.bubble_shown() == "응… 안녕." and b.state == "talk_end"  # 다 나옴 → 입 다묾
        clock[0] += 10
        w.step()
        assert w.bubble() is None and b.state in ("stand", "walk")
    finally:
        w.close()


def test_sound_listener_raises_affinity_and_notices_only_for_chosen_voice(app, cfg, monkeypatch):
    from mabinogi_addon.ui import character_controller as cc
    from mabinogi_addon.ui import notifier

    config.save_voice_pack("조용한 여성")
    ctrl = cc.CharacterController()
    sounds = paths.resource_dir() / "sounds"
    notifier._announce("vivace", sounds / "조용한 여성" / "비바체 연장.mp3")
    assert ctrl.affinity.value == 0  # 제작자 아님(알파는 제작자 전용) — 아무것도 안 함
    ctrl.set_enabled(True)
    try:
        notifier._announce("vivace", sounds / "조용한 여성" / "비바체 연장.mp3")
        notifier._announce("vivace", sounds / "비바체 연장.mp3")  # 기본 녹음 — 다른 목소리
        notifier._announce("preview", sounds / "조용한 여성" / "투아림 부스트 발동 직전.mp3")  # 미리듣기
        assert ctrl.affinity.value == 1
        saved = config.load_affinity("조용한 여성")
        assert saved["counts"] == {"alert": 1} and saved["totals"] == {"alerts": 1}
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
        assert ctrl.affinity.value == 0  # 비제작자: 켜기 보너스·인사 없음
        ctrl.set_enabled(True)
        ctrl.start(now)
        ctrl.start(now)
        assert ctrl.affinity.value == 2 and ctrl.affinity.streak == 1 and config.load_pet_last_seen() == "2026-11-24"
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
    assert [c.character.name for c in tab.cards] == ["다래", "아리아", "???", "???", "이안"]
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


def test_creator_sets_affinity_directly_with_number_and_stage_buttons(app, cfg, monkeypatch):
    from mabinogi_addon.ui import character_tab as ct

    config.save_character(affinity=("조용한 여성", {"value": 3, "day": DAY, "gained": 3, "counts": {"launch": 1},
                                                   "totals": {"alerts": 4}}))
    tab = ct.CharacterTab()
    edited = []
    tab.affinity_edited.connect(lambda: edited.append(1))
    editor = tab.editors[0]
    assert editor.spin.value() == 3 and [b.text() for b in editor.buttons] == ["0", "25", "50", "75", "100"]
    editor.buttons[3].click()
    saved = config.load_affinity("조용한 여성")
    assert saved["value"] == 75 and saved["cleared"] == 3  # 0→25·25→50·50→75 퀘스트 깬 것으로
    assert saved["gained"] == 3 and saved["counts"] == {"launch": 1} and saved["totals"] == {"alerts": 4}  # 하루 상한과 무관
    assert tab.cards[0]._affinity == 75 and tab.cards[0]._quest == "퀘스트: 7일 연속 켜기 · 0/7일" and edited == [1]
    assert tab.cards[1]._quest == "퀘스트: 아리아를 처음으로 쓰다듬어 주기 · 0/1번"  # 고른 캐릭터 이름
    assert tab.cards[2]._quest == "퀘스트: 처음 쓰다듬기 · 0/1번"  # 이름 없는 캐릭터
    editor.spin.setValue(42)
    assert config.load_affinity("조용한 여성")["value"] == 42
    tab.editors[4].buttons[4].click()
    assert config.load_affinity("차분한 남성")["value"] == 100


def test_settings_voice_choice_hides_for_creator_and_follows_character_tab(app, cfg):
    from mabinogi_addon.ui.settings_tab import SettingsTab

    tab = SettingsTab(None)
    tab.set_voice_visible(False)
    assert not tab._voice_box.isVisibleTo(tab)
    config.save_voice_pack("조용한 여성")
    tab.sync_voice_choice()
    assert tab._voice_pack.currentData() == "조용한 여성"
    tab.set_voice_visible(True)
    assert tab._voice_box.isVisibleTo(tab)


def test_frame_sizes_match_standing_height():
    from mabinogi_addon.image_io import imread
    import cv2

    stand = imread(ASSETS / "다래" / "stand_0.png", cv2.IMREAD_UNCHANGED)
    walk = [imread(p, cv2.IMREAD_UNCHANGED).shape[0] for p in sorted((ASSETS / "다래").glob("walk_*.png"))]
    assert stand.shape[0] == 285 and all(abs(h - 285) <= 3 for h in walk)  # 서 있는 키로 맞춤(시트마다 머리 크기 달라도)


# ---- 아리아(부드러운 여성, 사용자 11-24 알파 포함 — docs/characters/아리아.md) -------------------------------
ARIA = ASSETS / "아리아"


def _aria(**kw):
    b = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(5), profile=br.ARIA, **kw)
    b.pos = (300.0, 700.0)
    return b


def test_aria_roster_card_and_frames():
    aria = roster.by_pack("부드러운 여성")
    assert (aria.name, aria.known, aria.has_pet, aria.color) == ("아리아", True, True, "#F5A25D")
    assert (ASSETS / aria.card).is_file() and roster.folder(aria) == "아리아"
    assert [c.name for c in roster.ROSTER][:2] == ["다래", "아리아"]
    names = {n for frames, _t, _l in br.ARIA.anims.values() for n in frames}
    assert not [n for n in names if not (ARIA / f"{n}.png").exists()]


def test_aria_standing_height_drag_edges_and_walk_hair_color():
    import cv2
    from mabinogi_addon.image_io import imread

    stand = imread(ARIA / "stand_0.png", cv2.IMREAD_UNCHANGED)
    assert stand.shape[0] == 285
    for name in ("hair_0", "walk_0", "talk_closed_0", "surprise_0", "getup_2", "rise_2"):
        assert abs(imread(ARIA / f"{name}.png", cv2.IMREAD_UNCHANGED).shape[0] - 285) <= 3, name
    for name in ("drag_0", "drag_1"):  # 옅은 막(알파 1~40)을 지워 가장자리는 투명
        a = imread(ARIA / f"{name}.png", cv2.IMREAD_UNCHANGED)[..., 3]
        corners = [a[0, 0], a[0, -1], a[-1, 0], a[-1, -1]]
        assert max(corners) == 0 and ((a > 0) & (a <= 40)).mean() < 0.02  # 막이 남으면 네 귀퉁이·옅은 칸이 차 있음

    import numpy as np

    def top_lab(frame):
        top = frame[: int(frame.shape[0] * 0.18)]
        solid = top[..., 3] > 220
        lab = cv2.cvtColor(top[..., :3].copy(), cv2.COLOR_BGR2LAB).reshape(-1, 3)[solid.reshape(-1)]
        return np.median(lab.astype(float), axis=0)

    walk = imread(ARIA / "walk_0.png", cv2.IMREAD_UNCHANGED)
    d = top_lab(walk) - top_lab(stand)
    delta = float(np.sqrt(((d * np.array([100 / 255, 1, 1])) ** 2).sum()))  # OpenCV Lab(8비트) → L 0~100
    assert delta < 4, delta  # 걷기 정수리 머리색을 서 있기에 맞춤


def test_aria_lines_have_stroke_click_and_no_sleep_click():
    data = ln.read(ARIA / "lines.json")
    assert data.character == "아리아"
    assert set(ln.SITUATIONS) - {"click_sleep"} <= set(data.lines)
    assert "idle_extra_click" in data.lines and "click_sleep" not in data.lines  # 머리 쓰다듬는 중 클릭(공통 이름)
    from mabinogi_addon.ui.notifier import alert_files
    sounds = alert_files(paths.resource_dir() / "sounds" / "부드러운 여성") - {"파티 알림.mp3"}
    assert len(data.alerts) == 11 and sounds == set(data.alerts)
    assert data.alerts["비바체 연장.mp3"] == "비바체~ 잊은 거 아니지?"
    assert data.lines["annoyed_click"][0].text == "으응… 너무 자주 누르면 어지러워."


def test_aria_sits_without_dozing_and_smiles_when_clicked():
    b = _aria(corner=(900.0, 700.0))
    t, _ = _run(b, 0, 0.5, False)
    t, _ = _run(b, t, 5, True)
    assert b.state in br.ARIA.sitting
    seen = set()
    for _ in range(400):
        t += 0.05
        b.tick(t, True)
        seen.add(b.frame(t))
        assert b.state not in ("sit_doze", "wake") and not b.zzz()
    assert {"sit_0", "sit_1", "sit_2", "sit_3"} <= seen  # 머리 안고 앉아 웃음 반복
    b.press(t, 900, 640)
    assert b.release(t)[-1] == ("say", "click_sit") and b.frame(t) == "sit_1"  # 앉아서 클릭 = 웃음


def test_aria_alternates_stand_and_hair_stroke_and_walking_cuts_it():
    b = _aria()
    b._next_walk = 1e9
    t, _ = _run(b, 0, 16, False)
    assert b.state == "hairstroke" or b._extra_until > 0  # 8~15초 안에 머리 쓰다듬기 시작
    t, _ = _run(b, t, 4.0, False)
    assert b.state == "stand"  # 1~2바퀴(약 1.9초씩) 뒤 서 있기로
    b._go("hairstroke", t)
    b._extra_until = t + 10
    b._next_walk = t
    t, _ = _run(b, t, 0.1, False)
    assert b.state == "walk"  # 걸을 차례면 바로 끊음


def test_aria_click_while_stroking_hair_says_stroke_click():
    b = _aria()
    b._go("hairstroke", 1)
    b._extra_until = 10
    b.press(1.2, 300, 600)
    assert b.release(1.2) == [("click",), ("say", "idle_extra_click")] and b.state == "surprise"
    b._go("stand", 2)
    b.press(2.1, 300, 600)
    assert b.release(2.1)[-1] == ("say", "click_stand")


def test_aria_think_mood_falls_back_to_normal_mouth():
    b = _aria()
    assert b.talk(1, 10, "think") and b.state == "talk_normal"
    assert b.talk(2, 10, "happy") and b.state == "talk_happy"


def test_idle_timing_is_a_settings_value():
    p = br.ARIA.with_timing({"gap": [3, 4], "laps": [2, 2]})
    assert p.idle_gap == (3.0, 4.0) and p.idle_laps == (2, 2)
    assert br.ARIA.with_timing({"gap": [5, 1]}).idle_gap == (8.0, 15.0)  # 잘못된 값은 무시


def test_choosing_other_character_swaps_the_pet(app, cfg, monkeypatch):
    from mabinogi_addon.ui import character_controller as cc

    config.save_voice_pack("조용한 여성")
    config.save_character(pet=True)
    ctrl = cc.CharacterController()
    ctrl.set_enabled(True)
    try:
        ctrl.start(datetime.datetime(2026, 11, 24, 13))
        assert ctrl.window is not None and ctrl.window.brain.profile.doze_state == "sit_doze"  # 다래
        first = ctrl.window
        config.save_voice_pack("부드러운 여성")
        ctrl.voice_changed()
        assert ctrl.window is not None and ctrl.window is not first and ctrl.window.brain.profile.idle_extra == "hairstroke"
        assert ctrl.window.tint.name() == "#f5a25d" and ctrl.picker().data.character == "아리아"
        config.save_voice_pack("화난 여성")
        ctrl.voice_changed()
        assert ctrl.window is None  # 그림 없는 캐릭터 → 펫 없음
    finally:
        ctrl.shutdown()


def test_quest_text_uses_character_name_with_particles():
    a = aff.Affinity()
    assert a.quest_text("아리아") == "퀘스트: 아리아를 처음으로 쓰다듬어 주기 · 0/1번"
    assert a.quest_text("???") == "퀘스트: 처음 쓰다듬기 · 0/1번"
    b = aff.Affinity.load({"value": 30, "cleared": 1})
    assert b.quest_text("다래") == "퀘스트: 구석에서 다래와 함께 1시간 · 0/60분"
    c = aff.Affinity.load({"value": 55, "cleared": 2})
    assert c.quest_text("아리아") == "퀘스트: 아리아 목소리로 알림 10번 · 0/10번"
    assert aff._has_final("곰") and not aff._has_final("다래")


def test_card_preview_plays_pack_greeting_first_without_flat_fallback(tmp_path, monkeypatch):
    """카드 인사 녹음(사용자 11-24): 그 팩에 인사.mp3가 있으면 그것, 없으면 투아림 알림. 기본 녹음 인사로 폴백하지 않음."""
    from mabinogi_addon.ui import notifier

    sounds = tmp_path / "sounds"
    (sounds / "인사 있음").mkdir(parents=True)
    (sounds / "인사 없음").mkdir()
    for folder in (sounds / "인사 있음", sounds / "인사 없음", sounds):
        (folder / notifier.SAMPLE_FILE).write_bytes(b"x")
    (sounds / "인사 있음" / "인사.mp3").write_bytes(b"x")
    (sounds / "인사.mp3").write_bytes(b"x")  # 팩 밖(기본 녹음) 인사는 쓰지 않음
    monkeypatch.setattr(notifier, "SOUND_DIR", sounds)
    monkeypatch.setattr(config, "load_voice_pack", lambda *a, **k: "인사 없음")
    assert notifier.greeting_path("인사 있음") == sounds / "인사 있음" / "인사.mp3"
    assert notifier.greeting_path("인사 없음") == sounds / "인사 없음" / notifier.SAMPLE_FILE
    assert notifier.alert_files(sounds / "인사 있음") == {notifier.SAMPLE_FILE}  # 인사는 알림 파일로 안 셈


def test_card_click_plays_greeting_of_chosen_pack(app, cfg, monkeypatch):
    from mabinogi_addon.ui import character_tab as ct
    from mabinogi_addon.ui import notifier

    played = []
    monkeypatch.setattr(notifier, "greeting_path", lambda pack: played.append(pack) or Path("없음.mp3"))
    tab = ct.CharacterTab()
    tab.choose(roster.DARE)
    assert played == ["조용한 여성"]


def test_tuarim_extra_alert_uses_second_recording_slot(tmp_path, monkeypatch):
    """투아림 추가 알림 자리(사용자 11-24): '…2.mp3'가 팩에 있으면 그것, 없으면 첫 알림 소리. 팩 바꾸면 둘 다 갱신."""
    from types import SimpleNamespace

    from mabinogi_addon.ui import notifier, tuarim_tab

    sounds = tmp_path / "sounds"
    for pack in ("둘 있음", "하나만"):
        (sounds / pack).mkdir(parents=True)
        (sounds / pack / tuarim_tab.TUARIM_SOUND).write_bytes(b"x")
    (sounds / "둘 있음" / "투아림 부스트 발동 직전2.mp3").write_bytes(b"x")
    monkeypatch.setattr(notifier, "SOUND_DIR", sounds)
    pack = {"name": "둘 있음"}
    monkeypatch.setattr(config, "load_voice_pack", lambda *a, **k: pack["name"])
    assert tuarim_tab._tuarim_sounds() == {"tuarim": sounds / "둘 있음" / tuarim_tab.TUARIM_SOUND,
                                           "tuarim2": sounds / "둘 있음" / "투아림 부스트 발동 직전2.mp3"}
    played, loaded = [], []
    fake = SimpleNamespace(_paused=False, _thresholds=[80, 95], _sounds=[True, True],
                           _notifier=SimpleNamespace(play=lambda key: played.append(key) or True,
                                                     set_sounds=loaded.append))
    tuarim_tab.TuarimTab._play(fake, 80)
    tuarim_tab.TuarimTab._play(fake, 95)
    assert played == ["tuarim", "tuarim2"]
    pack["name"] = "하나만"
    tuarim_tab.TuarimTab.refresh_sound(fake)
    assert loaded[-1] == {"tuarim": sounds / "하나만" / tuarim_tab.TUARIM_SOUND,
                          "tuarim2": sounds / "하나만" / tuarim_tab.TUARIM_SOUND}  # 2 없으면 첫 알림 소리


def test_second_alert_bubble_falls_back_to_first_line_and_counts_as_alert(app, cfg):
    from mabinogi_addon.ui import character_controller as cc
    from mabinogi_addon.ui import notifier

    picker = ln.Picker(ln.read(ARIA / "lines.json"))
    assert picker.alert("투아림 부스트 발동 직전2.mp3") == picker.alert("투아림 부스트 발동 직전.mp3")
    assert picker.alert("비바체 연장2.mp3").text == "비바체, 잊으면 안 돼!"  # 있는 2차 줄은 그대로
    config.save_voice_pack("부드러운 여성")
    ctrl = cc.CharacterController()
    ctrl.set_enabled(True)
    try:
        notifier._announce("tuarim2", paths.resource_dir() / "sounds" / "부드러운 여성" / "투아림 부스트 발동 직전2.mp3")
        assert ctrl.affinity.totals == {"alerts": 1}  # 추가 알림도 같은 '알림 받기'
    finally:
        ctrl.shutdown()


# ---- 호감도 구간 대사(사용자 11-24 '대사는 일단 넣어' — 목소리는 녹음 뒤) -----------------------------------
def _doc(lines, version=2):
    return json.dumps({"schemaVersion": version, "character": "다래", "lines": lines}).encode()


def test_lines_schema_reads_old_and_new_stage_voice_keys():
    old = ln.parse(_doc({"idle": ["가"]}, version=1))
    assert old.lines["idle"] == (ln.Line("가"),)
    data = ln.parse(_doc({"idle": [
        {"text": "가", "stage": 25, "voice": "대사/구간_25.mp3"},
        {"text": "나", "stage": 30},                  # 모르는 구간 → 0
        {"text": "다", "stage": "50"},                # 문자열 → 0
        {"text": "라", "voice": "../밖.mp3"},          # 팩 밖 경로 → 버림
        {"text": "마", "voice": "C:/x.mp3"},
        {"text": "바", "voice": "대사/소리.wav"},
        {"text": "x" * 31, "stage": 25},              # 30자 넘으면 그 줄만 버림
    ], "stage_up": [{"text": "올랐다", "stage": 25}]}))
    got = {line.text: (line.stage, line.voice) for line in data.lines["idle"]}
    assert got == {"가": (25, "대사/구간_25.mp3"), "나": (0, None), "다": (0, None), "라": (0, None),
                   "마": (0, None), "바": (0, None)}
    assert data.lines["stage_up"][0].stage == 25
    with pytest.raises(ValueError):
        ln.parse(_doc({"idle": ["가"]}, version=3))


def test_pick_uses_only_unlocked_stages_and_doubles_the_current_one():
    data = ln.parse(_doc({"idle": [
        {"text": "영", "stage": 0}, {"text": "이오", "stage": 25}, {"text": "오십", "stage": 50}]}))
    picker = ln.Picker(data, random.Random(11))
    assert {picker.pick("idle", 0).text for _ in range(50)} == {"영"}
    picker = ln.Picker(data, random.Random(11))
    seq = [picker.pick("idle", 25).text for _ in range(3000)]
    assert set(seq) == {"영", "이오"} and all(a != b for a, b in zip(seq, seq[1:]))
    # 연속 금지 때문에 두 줄이면 번갈아 — 세 줄(구간 50)에서 지금 구간 줄이 2배인지 본다
    picker = ln.Picker(data, random.Random(11))
    seq = [picker.pick("idle", 50).text for _ in range(6000)]
    share = seq.count("오십") / len(seq)
    assert 0.37 < share < 0.44, share  # 2:1:1 가중 + 연속 금지 → 정상 상태 0.40(가중치 없으면 0.33)


def test_both_characters_have_24_stage_lines_and_voices_kept():
    for name, extra_voice in (("다래", "자다깸"), ("아리아", "머리정리")):
        data = ln.read(ASSETS / name / "lines.json")
        staged = [line for items in data.lines.values() for line in items if line.stage > 0]
        assert len(staged) == 24 and sorted({line.stage for line in staged}) == [25, 50, 75, 100]
        ups = data.lines["stage_up"]
        assert [line.stage for line in ups] == [25, 50, 75, 100]
        assert [line.voice for line in ups] == [f"대사/구간_{s}.mp3" for s in (25, 50, 75, 100)]
        voices = {line.voice for items in data.lines.values() for line in items if line.voice}
        assert len(voices) == 14 and f"대사/{extra_voice}.mp3" in voices  # 0구간 10줄 + 구간 오름 4줄
        assert {"hello", "click_stand", "pet_end", "game_exit", "idle"} <= {
            k for k, items in data.lines.items() if any(line.stage == 100 for line in items)}


class _FakeWindow:
    def __init__(self):
        self.said = []
        self.brain = br.Brain(br.Floor(0, 1000, 700))

    def say(self, line, mood="normal"):
        self.said.append(line.text if line is not None and not isinstance(line, str) else line)


def test_stage_up_once_highest_only_no_drop_line_and_silent_without_pet(app, cfg):
    from mabinogi_addon.ui import character_controller as cc
    from mabinogi_addon.ui import character_tab as ct

    config.save_voice_pack("조용한 여성")
    ctrl = cc.CharacterController()
    ctrl.set_enabled(True)
    tab = ct.CharacterTab()
    tab.affinity_edited.connect(ctrl.reload_affinity)
    ctrl.window = fake = _FakeWindow()
    try:
        tab.set_affinity("조용한 여성", 25)  # 제작자 구간 버튼으로 올림
        assert fake.said == ["…너, 생각보다 괜찮은 사람이네."]
        tab.set_affinity("조용한 여성", 100)  # 50·75를 건너뜀 → 가장 높은 구간 것 하나만
        assert fake.said[-1] == "…이 열쇠, 너한테 줄게. 내 마음 열쇠야." and len(fake.said) == 2
        tab.set_affinity("조용한 여성", 50)  # 내려감 → 말 없음
        assert len(fake.said) == 2
        assert ctrl._pick("hello").stage <= 50
        ctrl.window = None  # 펫 꺼짐 → 말하지 않고 밀린 것도 안 쌓음
        tab.set_affinity("조용한 여성", 75)
        ctrl.window = fake
        tab.set_affinity("조용한 여성", 75)
        assert len(fake.said) == 2
    finally:
        ctrl.window = None
        ctrl.shutdown()


def test_quest_clear_triggers_stage_up_line(app, cfg):
    from mabinogi_addon.ui import character_controller as cc

    config.save_voice_pack("부드러운 여성")
    config.save_character(affinity=("부드러운 여성", {"value": 25}))
    ctrl = cc.CharacterController()
    ctrl.set_enabled(True)
    ctrl.window = fake = _FakeWindow()
    try:
        ctrl._on_events([("pet_done",)])  # 처음 쓰다듬기 → 0→25 퀘스트 깸 → 구간 25
        assert ctrl.affinity.stage == 25 and fake.said == ["우리 꽤 친해진 것 같지? 헤헤"]
    finally:
        ctrl.window = None
        ctrl.shutdown()


# ---- 대사 목소리 재생(사용자 11-24 — docs/character-pet-spec.md '대사 목소리 재생') ----------------------------
class _FakeVoice:
    def __init__(self):
        self.played, self.stops = [], 0
        self.on_duration = None

    def play(self, path):
        self.played.append(path)
        return True

    def stop(self):
        self.stops += 1


@pytest.fixture
def voiced(app, cfg, tmp_path, monkeypatch):
    """임시 sounds 폴더(다래 팩에 대사/구간_25.mp3·대사/클릭.mp3만) + 가짜 펫 창·재생기."""
    from mabinogi_addon.ui import character_controller as cc
    from mabinogi_addon.ui import notifier

    sounds = tmp_path / "sounds"
    (sounds / "조용한 여성" / "대사").mkdir(parents=True)
    for name in ("구간_25.mp3", "클릭.mp3"):
        (sounds / "조용한 여성" / "대사" / name).write_bytes(b"x")
    (sounds / "대사").mkdir()
    (sounds / "대사" / "켜기_1.mp3").write_bytes(b"x")  # 팩 밖(기본 녹음) — 쓰지 않음
    monkeypatch.setattr(notifier, "SOUND_DIR", sounds)
    config.save_voice_pack("조용한 여성")
    ctrl = cc.CharacterController()
    ctrl.set_enabled(True)
    ctrl.voice = _FakeVoice()
    ctrl.window = _FakeWindow()
    yield ctrl, sounds
    ctrl.window = None
    ctrl.shutdown()


def test_voice_plays_only_existing_file_in_chosen_pack(voiced):
    ctrl, sounds = voiced
    ctrl._say(ln.Line("응…? 불렀어…?", voice="대사/클릭.mp3"))
    ctrl._say(ln.Line("왔어…? 기다렸어… 조금.", voice="대사/켜기_1.mp3"))  # 팩에 없음 → 기본 폴더로 안 감
    ctrl._say(ln.Line("…졸려."))  # 목소리 없는 줄
    assert ctrl.voice.played == [sounds / "조용한 여성" / "대사" / "클릭.mp3"]
    assert ctrl.window.said == ["응…? 불렀어…?", "왔어…? 기다렸어… 조금.", "…졸려."]  # 말풍선은 언제나
    assert ctrl.voice.stops >= 3  # 새 말풍선마다 앞 소리 멈춤


def test_voice_switch_off_and_pause_keep_bubbles_silent(voiced):
    ctrl, _ = voiced
    config.save_character(voiceLines=False)
    ctrl._say(ln.Line("응…? 불렀어…?", voice="대사/클릭.mp3"))
    config.save_character(voiceLines=True)
    ctrl.set_paused(True)
    ctrl._say(ln.Line("응…? 불렀어…?", voice="대사/클릭.mp3"))
    assert ctrl.voice.played == [] and len(ctrl.window.said) == 2
    ctrl.set_paused(False)
    ctrl._say(ln.Line("응…? 불렀어…?", voice="대사/클릭.mp3"))
    assert len(ctrl.voice.played) == 1


def test_alert_sound_stops_dialogue_voice(voiced):
    from mabinogi_addon.ui import notifier

    ctrl, sounds = voiced
    before = ctrl.voice.stops
    notifier._announce("vivace", sounds / "조용한 여성" / "비바체 연장.mp3")
    assert ctrl.voice.stops == before + 1


def test_stage_up_line_plays_its_voice(voiced):
    ctrl, sounds = voiced
    ctrl.affinity.set_value(25)
    ctrl._check_stage()
    assert ctrl.window.said == ["…너, 생각보다 괜찮은 사람이네."]
    assert ctrl.voice.played == [sounds / "조용한 여성" / "대사" / "구간_25.mp3"]


def test_voice_player_skips_while_alert_plays_or_volume_zero(app, monkeypatch, tmp_path):
    from mabinogi_addon.ui import notifier, voice_lines

    path = tmp_path / "a.mp3"
    path.write_bytes(b"x")
    player = voice_lines.VoiceLinePlayer()
    monkeypatch.setattr(notifier, "alert_playing", lambda: True)
    assert player.play(path) is False  # 알림 우선
    monkeypatch.setattr(notifier, "alert_playing", lambda: False)
    monkeypatch.setattr(notifier, "master_volume", lambda: 0)
    assert player.play(path) is False  # 알림 음량 0%
    assert voice_lines.voice_file("조용한 여성", "../부드러운 여성/인사.mp3") is None  # 팩 밖으로 못 나감


def test_talking_picture_lasts_as_long_as_the_voice(app):
    from mabinogi_addon.ui.pet_window import PetWindow, load_frames

    clock = [10.0]
    b = _brain()
    w = PetWindow(b, load_frames("다래"), roster.DARE.color, clock=lambda: clock[0])
    try:
        w.say(ln.Line("응… 안녕."))  # 6글자 → 글자 기준 약 0.4초
        w.hold_talk(2.5)  # 가짜 소리 길이 2.5초
        clock[0] += 1.5
        w.step()
        assert b.state == "talk_normal"  # 글자는 끝났지만 소리 동안 입 움직임 유지
        clock[0] += 1.2
        w.step()
        assert b.state == "talk_end"
        w.say(ln.Line("오늘도… 같이 있자."))
        w.hold_talk(0.1)  # 소리가 짧으면 글자 기준 그대로
        assert b._talk_until >= clock[0] + 0.6
    finally:
        w.close()


def test_character_tab_has_voice_lines_switch_default_on(app, cfg):
    from mabinogi_addon.ui import character_tab as ct

    tab = ct.CharacterTab()
    assert tab.voice_switch.text() == "대사 목소리" and tab.voice_switch.isChecked()
    tab.voice_switch.setChecked(False)
    assert config.load_voice_lines() is False


# ---- 이안(차분한 남성, 사용자 11-24 알파 포함 — docs/characters/이안.md) ----------------------------------------
IAN_DIR = ASSETS / "이안"


def _ian(**kw):
    b = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(9), profile=br.IAN, **kw)
    b.pos = (300.0, 700.0)
    return b


def test_ian_roster_card_frames_and_heights():
    import cv2
    from mabinogi_addon.image_io import imread

    ian = roster.by_pack("차분한 남성")
    assert (ian.name, ian.known, ian.has_pet, ian.color) == ("이안", True, True, "#3B5B9A")
    assert (ASSETS / ian.card).is_file() and [c.name for c in roster.ROSTER][-1] == "이안"
    names = {n for frames, _t, _l in br.IAN.anims.values() for n in frames}
    assert not [n for n in names if not (IAN_DIR / f"{n}.png").exists()]
    h = lambda n: imread(IAN_DIR / f"{n}.png", cv2.IMREAD_UNCHANGED).shape  # noqa: E731
    for name in ("stand_0", "stand_1", "watch_2", "walk_0", "land_2", "crouch_0", "talk_point_0", "talk_alert_0"):
        assert abs(h(name)[0] - 285) <= 3, name
    assert abs(h("rise_0")[1] - h("crouch_2")[1]) <= 3  # 일어나기 첫 장 = 쪼그림 폭
    assert h("rise_2")[0] == 285  # 끝 = 서 있는 키
    assert abs(h("sit_0")[0] - h("crouch_2")[0]) <= 4  # 앉아 기다리기 = 웅크리기 끝 높이


def test_ian_lines_have_alerts_stage_lines_and_watch_click():
    data = ln.read(IAN_DIR / "lines.json")
    assert data.character == "이안" and "click_sleep" not in data.lines
    assert set(ln.SITUATIONS) - {"click_sleep"} <= set(data.lines) and "idle_extra_click" in data.lines
    from mabinogi_addon.ui.notifier import alert_files
    sounds = alert_files(paths.resource_dir() / "sounds" / "차분한 남성") - {"파티 알림.mp3"}
    assert len(data.alerts) == 11 and sounds == set(data.alerts)
    staged = [line for items in data.lines.values() for line in items if line.stage > 0]
    assert len(staged) == 24 and [line.stage for line in data.lines["stage_up"]] == [25, 50, 75, 100]
    voices = {line.voice: (key, line.text) for key, items in data.lines.items() for line in items if line.voice}
    names = ["켜기_1", "켜기_2", "오랜만", "밤", "게임시작", "게임끝", "휴식", "쓰다듬기끝", "클릭", "시계",
             "구간_25", "구간_50", "구간_75", "구간_100"]
    assert set(voices) == {f"대사/{n}.mp3" for n in names}  # 녹음목록.md '이안' 표 14줄(사용자 11-24 오디오 추가)
    assert voices["대사/시계.mp3"] == ("idle_extra_click", "시각 확인 중이었습니다.")
    assert voices["대사/켜기_1.mp3"] == ("hello", "오셨습니까. 오늘 일정 시작하죠.")
    assert voices["대사/구간_100.mp3"] == ("stage_up", "이 시계, 이제 당신 시간에 맞추겠습니다.")


def test_ian_never_dozes_or_gets_up_and_lands_straight_to_standing():
    b = _ian()
    b.press(0, 300, 600)
    b.move(0.1, 300, 300)
    assert b.state == "drag"
    assert b.release(0.2) == [] and b.state == "fall"
    t, events = _run(b, 0.2, 0.8, False)
    assert b.state == "land" and ("say", "dropped") in events
    seen = set()
    while t < 3:
        t += 0.05
        b.tick(t, False)
        seen.add(b.state)
    assert "getup" not in seen and b.state in ("stand", "walk", "watch")  # 착지 → 바로 서기
    b2 = _ian(corner=(900.0, 700.0))
    t, _ = _run(b2, 0, 6, True)
    for _ in range(400):
        t += 0.05
        b2.tick(t, True)
        assert b2.state not in ("sit_doze", "wake", "getup") and not b2.zzz()
    assert b2.state in br.IAN.sitting


def test_ian_alternates_watch_and_click_while_watching():
    b = _ian()
    b._next_walk = 1e9
    t, _ = _run(b, 0, 16, False)
    assert b.state == "watch" or b._extra_until > 0
    b._go("watch", t)
    b._extra_until = t + 5
    b.press(t, 300, 600)
    assert b.release(t) == [("click",), ("say", "idle_extra_click")]  # 시계 보는 중 클릭


def test_ian_standing_click_looks_up_then_talks():
    b = _ian()
    b.press(1, 300, 600)
    assert b.release(1)[-1] == ("say", "click_stand") and b.frame(1) == "pet_0"  # 시선 위 0.5초
    assert b.talk(1, 10, "normal") is False  # 클릭 반응 중엔 바로 안 바꾸고
    _run(b, 1, 0.55, False)
    assert b.state == "talk_normal" and b.frame(1.6) in ("stand_0", "stand_1")  # 끝나면 말하기로 이어감
    d = _brain()  # 다래는 그대로(놀람 뒤 서 있기)
    d.press(1, 300, 600)
    d.release(1)
    d.talk(1, 10)
    _run(d, 1, 1.0, False)
    assert d.state in ("stand", "walk")


def test_ian_alert_points_at_watch():
    b = _ian()
    b.notify(1)
    assert b.state == "alert" and b.frame(1) == "talk_alert_0"
    _run(b, 1, 2.0, False)
    assert b.state in ("stand", "walk", "watch")


def test_walk_values_come_from_character_data_and_corner_rush_speeds_up_steps():
    """걷기 미끄러짐(사용자 11-24): 캐릭터별 프레임 시간·속도, 이안 0.2초·75px/초."""
    assert br.IAN.walk_speed == 75.0 and br.IAN.anims["walk"][1] == (0.2,) * 6
    for profile in (br.DARE, br.ARIA, br.IAN):
        cycle = sum(profile.anims["walk"][1])
        assert 60 <= profile.walk_speed <= 90 and 80 <= profile.walk_speed * cycle <= 125  # 한 바퀴 거리 ≈ 보폭
    b = _ian()
    b._walk_to((800.0, 700.0), 0)
    _run(b, 0, 1.0, False)
    assert abs(b.pos[0] - 375.0) < 6  # 75px/초(첫 틱은 시간 0)
    b2 = _ian(corner=(900.0, 700.0))
    _run(b2, 0, 2.0, True)
    assert b2.state == "walk" and b2._walk_rate > 1.5  # 구석으로 서두를 땐 걸음 그림도 빨리


def test_ian_fall_and_land_keep_head_size():
    """이안 떨어지기·착지(사용자 11-24 '낙하가 어색'): 떨어지기 머리 폭 = 서 있기 머리 폭, 착지는 첫 장 머리 폭 → 끝 서 있는 키."""
    import cv2
    import numpy as np
    from mabinogi_addon.image_io import imread

    def head_width(name):
        a = imread(IAN_DIR / f"{name}.png", cv2.IMREAD_UNCHANGED)[..., 3] > 100
        cols = np.where(a[: int(a.shape[0] * 0.4)].any(0))[0]
        return cols.max() - cols.min()

    stand = head_width("stand_1")
    for name in ("fall_0", "fall_1", "land_0"):
        assert abs(head_width(name) - stand) / stand <= 0.03, name
    assert imread(IAN_DIR / "land_2.png", cv2.IMREAD_UNCHANGED).shape[0] == 285
