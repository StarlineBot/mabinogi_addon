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


def test_corner_minute_event_every_minute_while_sitting_in_game():
    b = _brain(corner=(300.0, 700.0))
    t, _ = _run(b, 0, 2, True)
    t, events = _run(b, t, 600, True, step=0.5)
    assert events.count(("corner_minute",)) == 10
    t, events = _run(b, t, 120, False, step=0.5)
    assert ("corner_minute",) not in events[4:]  # 게임 밖이면 안 셈


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
    assert tab.cards[1]._quest == "퀘스트: 처음 쓰다듬기 · 0/1번"
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
