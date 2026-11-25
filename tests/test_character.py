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
def growth(monkeypatch):
    """호감도 쌓기 규칙 테스트용 — 베타(11-24)엔 꺼 두었으므로(aff.GROWTH) 켜고 확인."""
    monkeypatch.setattr(aff, "GROWTH", True)


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
def test_daily_full_is_ten_and_each_action_has_its_own_limit(growth):
    a = aff.Affinity()
    got = [a.launched(DAY), a.launched(DAY)]
    got += [a.gain("pet", DAY) for _ in range(4)]
    got += [a.alerted(DAY) for _ in range(5)]
    got += [a.corner_minute(DAY) for _ in range(120)]
    assert got[:11] == [2, 0, 1, 1, 1, 0, 1, 1, 1, 0, 0]
    assert sum(got[11:]) == 2 and got[11 + 29] == 1 and got[11 + 59] == 1  # 30분마다 +1, 하루 2번
    assert a.value == a.gained == 10  # 2 + 3 + 3 + 2 = 하루 상한
    assert a.totals == {"alerts": 5, "corner_minutes": 120} and a.streak == 1


def test_stops_at_segment_end_until_quest_then_continues(growth):
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


def test_launch_streak_counts_consecutive_days_and_resets_on_gap(growth):
    a = aff.Affinity()
    for d in ("2026-11-20", "2026-11-21", "2026-11-22"):
        a.launched(d)
    assert a.streak == 3
    a.launched("2026-11-22")
    assert a.streak == 3  # 같은 날 다시 켜도 그대로
    a.launched("2026-11-24")
    assert a.streak == 1  # 하루 빠짐 → 다시 1일


def test_hundred_needs_seven_day_streak_quest(growth):
    a = aff.Affinity.load({"value": 99, "cleared": 3, "streak": 6, "lastLaunch": "2026-11-23"})
    a.alerted(DAY)
    assert a.value == 100 and a.stage == 75  # 100에 닿았지만 7일 연속 퀘스트 전
    a.launched(DAY)
    assert a.streak == 7 and a.cleared == 4 and a.stage == 100 and a.quest_text() == "퀘스트: 모두 깼어요"


def test_midnight_reset_keeps_value_and_quest_totals(growth):
    a = aff.Affinity(aff.Rules(daily_cap=3))
    assert [a.launched(DAY), a.gain("pet", DAY), a.alerted(DAY)] == [2, 1, 0]  # 상한 3에서 잘림
    a.alerted("2026-11-25")  # 자정 지남 → 오늘 횟수·오른 양 초기화
    assert a.value == 4 and a.gained == 1 and a.counts == {"alert": 1} and a.totals == {"alerts": 2}


def test_repeat_penalty_once_a_minute_never_below_zero_or_segment_start(growth):
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


def test_petting_after_daily_three_is_annoyed(growth):
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


def test_rules_are_settings_values_and_state_round_trips(growth):
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
    assert data.alerts["비바체 연장.mp3"] == ("비바체… 잊은 거 아니지…?",)
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
    assert data.alerts == {"a.mp3": ("알림",)}
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


def test_pet_needs_two_round_trips_of_20px_within_two_seconds():
    """사용자 11-24 '마우스만 지나가도 쓰다듬는 모션': 한 방향으로 20px 이상 간 뒤 돌아서야 1번, 왕복 2번(전환 3번)·2초 안."""
    def run(xs, dt=0.1, heads=None):
        b = _brain()
        events, t = [], 1.0
        for i, x in enumerate(xs):
            t += dt
            events += b.hover(t, x, True if heads is None else heads[i])
        return ("say", "pet_start") in events

    assert not run([200 + i * 8 for i in range(20)])                     # 한 방향으로 지나가기
    assert not run([300 + (5 if i % 2 else -5) for i in range(40)])      # 떨림 ±5(10px 되돌림)
    assert not run([300 + (3 if i % 2 else -3) for i in range(40)])
    assert not run([280, 300, 320, 300, 280, 300, 320])                  # 왕복 1번 반(전환 2번)
    assert run([280, 300, 320, 300, 280, 300, 320, 300])                 # 왕복 2번(전환 3번)
    assert not run([280, 300, 320, 300, 280, 300, 320, 300], dt=0.6)     # 천천히 — 전환 사이가 2초 창 밖
    xs = [280, 320, 280, 320, 300, 300, 280, 320, 280]                   # 전환 2번 뒤 머리를 벗어나면 처음부터
    assert not run(xs, heads=[True] * 4 + [False] + [True] * 4)
    assert run(xs)
    assert run([280, 320, 280, 320, 280])                                # 크게 빨리


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
    ("normal", {"talk_mid_0", "talk_m1_0", "talk_m2_0", "talk_emph_0", "talk_emph2_0"}),  # 20자 → 중간 강조
    ("explain", {"talk_mid_0", "talk_emph_0", "talk_emph2_0", "talk_m1_0", "talk_base_0", "talk_m2_0"}),
    ("think", {"talk_think_0"}),
    ("happy", {"talk_smile_0"}),
    ("angry", {"talk_mid_0", "talk_m1_0", "talk_m2_0", "talk_emph_0", "talk_emph2_0"}),
])
def test_talking_picks_frames_by_mood_then_closes_mouth(mood, frames):
    """새 말하기(사용자 11-24): 사이 → 입만 바꾸기, 설명은 첫머리 강조, 생각·기쁨은 그 그림, 끝은 base → 사이 → 서기."""
    b = _brain()
    b._target = (800.0, 700.0)
    b._go("walk", 0)
    assert b.talk(1.0, 20, mood) is True and b._target is None  # 걷다 멈추고 말함
    until = b._talk_until
    seen = {b.frame(1.0 + i * 0.05) for i in range(int((until - 1.0) / 0.05))}
    seen.discard("talk_blink_0")
    assert frames <= seen <= frames | {"talk_base_0"}
    _run(b, 1.0, until - 1.0 + 0.1, False)
    assert b.state == "talk_end"
    end0 = b._t0
    assert b.frame(end0 + 0.1) == "talk_base_0" and b.frame(end0 + 0.4) == "talk_mid_0"
    _run(b, until, 1.0, False)
    assert b.state in ("stand", "walk")


def test_talk_start_order_emphasis_once_and_blinks():
    b = _brain()
    b.talk(10.0, 30, "normal")  # 30글자 → 2.1초
    assert b.frame(10.05) == "talk_mid_0"  # 서기 → 사이
    assert b.frame(10.25) == "talk_m1_0"  # → 입만 바꾸기(m1·m2·m1·base)
    seq = [b.frame(10.2 + 0.2 * i + 0.01) for i in range(30)]
    assert sum(1 for x, y in zip(seq, seq[1:]) if y == "talk_emph_0" and x != "talk_emph_0") == 1  # 강조 한 문장 1번
    short = _brain()
    short.talk(0.0, 8, "normal")  # 12자 미만 → 강조 없음
    assert short._emph_at is None
    gaps = [y - x for x, y in zip(b._blinks, b._blinks[1:])]
    assert all(3.0 <= g <= 5.0 for g in gaps) and 3.0 <= b._blinks[0] - 10.2 <= 5.0


def test_aria_picks_talk_set_a_or_b_each_time():
    b = _aria()
    picked = set()
    for i in range(40):
        b._go("stand", i * 10)
        b.talk(i * 10.0, 10)
        picked.add(b._talk_set["base"])
    assert picked == {"talk_a_base_0", "talk_b_base_0"}


@pytest.mark.parametrize("profile,folder", [(br.DARE, "다래"), (br.ARIA, "아리아"), (br.IAN, "이안"), (br.LENA, "레나"),
                                            (br.STARLINE, "Starline")])
def test_every_picture_change_is_instant_no_ghost(app, profile, folder):
    """잔상 없음(사용자 11-24 '클릭·착지·손짓 때 잔상' — QA ghost_survey: 덮기 전환이 포즈가 다른 두 그림을 0.13초 겹침).
    덮기 전환을 없애 모든 캐릭터·시나리오(서서 클릭·말 4분위기·강조·대기 동작·알림·끌기→착지·쓰다듬기·구석→일어나기)에서
    그리는 그림은 늘 한 장."""
    from mabinogi_addon.ui.pet_window import PetWindow, load_frames

    clock = [5.0]
    b = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(3), profile=profile)
    b.pos = (300.0, 700.0)
    w = PetWindow(b, load_frames(folder, profile), "#888888", clock=lambda: clock[0])
    seen = set()

    def run(seconds, front=False, each=None):
        for i in range(int(seconds * 60)):
            clock[0] += 1 / 60
            if each:
                each(i)
            w._game_front = lambda: front
            w.step()
            layers = w.layers(clock[0])
            assert len(layers) == 1 and layers[0][1] == 1.0, layers
            seen.add(layers[0][0])

    try:
        b._next_walk = 1e9
        run(0.3)
        b.press(clock[0], 300, 600)
        w.events.emit(b.release(clock[0]))
        for mood in ("normal", "explain", "think", "happy"):
            b.talk(clock[0], 24, mood)
            run(2.5)
        b._next_extra = clock[0]
        run(3)
        b.notify(clock[0])
        run(2)
        b.press(clock[0], 300, 600)
        run(0.5, each=lambda i: b.move(clock[0], 300 + i * 3, 600 - i * 4))
        b.release(clock[0])
        run(3)
        x0 = b.pos[0]
        run(3, each=lambda i: b.hover(clock[0], x0 + (25 if (i // 6) % 2 else -25), True))
        run(2.5)
        b.corner = (900.0, 700.0)
        run(9, front=True)
        run(3, front=False)
    finally:
        w.close()
    assert any(n.startswith("talk_") for n in seen) and any(n.startswith(("land", "pet")) for n in seen)


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


def test_sound_listener_raises_affinity_and_notices_only_for_chosen_voice(growth, app, cfg, monkeypatch):
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


def test_launch_bonus_once_a_day_and_greeting(growth, app, cfg):
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
    monkeypatch.setattr(ct.CharacterTab, "_play_sample", lambda self, pack: played.append(pack))
    tab = ct.CharacterTab()
    changed, toggled = [], []
    tab.voice_pack_changed.connect(lambda: changed.append(1))
    tab.pet_toggled.connect(toggled.append)
    # 카드 순서(사용자 11-24): Starline → 레나 → 다래 → 이안 → 아리아 → 나머지
    assert [c.character.name for c in tab.cards] == ["Starline", "레나", "다래", "이안", "아리아", "???"]
    assert not any(c.selected() for c in tab.cards)  # 기본 녹음 — 고른 카드 없음
    tab.cards[5].clicked.emit(tab.cards[5].character)  # 누르면 인사만(사용자 11-25 B안) — 선택은 그대로
    assert config.load_voice_pack() == "" and played == ["자연스러운 여성"] and changed == []
    assert tab.cards[5].pending() and tab.cards[5].apply_button.isVisibleTo(tab.cards[5])
    tab.cards[5].apply_button.click()                  # 카드 안 '이 캐릭터로 적용' → 미정 카드도 그 목소리로
    assert config.load_voice_pack() == "자연스러운 여성" and changed == [1] and played == ["자연스러운 여성"]
    assert [c.selected() for c in tab.cards] == [False, False, False, False, False, True]
    assert not tab.cards[5].pending()
    tab.choose(roster.DARE)
    assert tab.cards[2].selected() and "돌아다녀요" in tab.pet_hint.text()
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
    editor = tab.editors[2]   # 다래(카드 순서 11-24)
    assert editor.spin.value() == 3 and [b.text() for b in editor.buttons] == ["0", "25", "50", "75", "100"]
    editor.buttons[3].click()
    saved = config.load_affinity("조용한 여성")
    assert saved["value"] == 75 and saved["cleared"] == 3  # 0→25·25→50·50→75 퀘스트 깬 것으로
    assert saved["gained"] == 3 and saved["counts"] == {"launch": 1} and saved["totals"] == {"alerts": 4}  # 하루 상한과 무관
    assert tab.cards[2]._affinity == 75 and tab.cards[2]._quest == "퀘스트: 7일 연속 켜기 · 0/7일" and edited == [1]
    assert tab.cards[4]._quest == "퀘스트: 아리아를 처음으로 쓰다듬어 주기 · 0/1번"  # 고른 캐릭터 이름
    assert tab.cards[5]._quest == "퀘스트: 처음 쓰다듬기 · 0/1번"  # 이름 없는 캐릭터
    editor.spin.setValue(42)
    assert config.load_affinity("조용한 여성")["value"] == 42
    tab.editors[3].buttons[4].click()   # 이안
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
    assert [c.name for c in roster.ROSTER] == ["Starline", "레나", "다래", "이안", "아리아", "???"]   # 카드 순서(사용자 11-24)
    names = {n for frames, _t, _l in br.ARIA.anims.values() for n in frames}
    assert not [n for n in names if not (ARIA / f"{n}.png").exists()]


def test_aria_standing_height_drag_edges_and_walk_hair_color():
    import cv2
    from mabinogi_addon.image_io import imread

    stand = imread(ARIA / "stand_0.png", cv2.IMREAD_UNCHANGED)
    assert stand.shape[0] == 285
    for name in ():  # 11-24부터 서 있는 계열은 키 대신 머리 폭으로 맞춤 — test_standing_frames_keep_head_size_within_5_percent
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
    assert len(data.alerts) == 12 and sounds <= set(data.alerts)   # 11 + 투아림 2차 말풍선(11-24, 녹음은 나중)
    assert data.alerts["비바체 연장.mp3"] == ("비바체~ 잊은 거 아니지?",)
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
    assert b.talk(1, 10, "think") and b.state == "talk"  # 생각 그림 없음 → 보통 말하기
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
        config.save_voice_pack("자연스러운 여성")
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
    assert a.quest_text("Starline") == "퀘스트: Starline을 처음으로 쓰다듬어 주기 · 0/1번"   # 읽는 소리 '스타라인'
    assert b.quest_text("Starline") == "퀘스트: 구석에서 Starline과 함께 1시간 · 0/60분"


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
    tab.preview(roster.DARE)
    assert played == ["조용한 여성"]
    tab.choose(roster.DARE)            # 적용은 인사를 다시 안 틂
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


def test_second_alert_bubble_falls_back_to_first_line_and_counts_as_alert(growth, app, cfg):
    from mabinogi_addon.ui import character_controller as cc
    from mabinogi_addon.ui import notifier

    picker = ln.Picker(ln.parse(json.dumps({"schemaVersion": 2, "character": "x", "lines": {"idle": ["a"]},
                                            "alerts": {"투아림 부스트 발동 직전.mp3": "곧 터져"}}).encode()))
    assert picker.alert("투아림 부스트 발동 직전2.mp3") == picker.alert("투아림 부스트 발동 직전.mp3")  # 2차 줄 없으면 1차
    picker = ln.Picker(ln.read(ARIA / "lines.json"))
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


def test_quest_clear_triggers_stage_up_line(growth, app, cfg):
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
        assert b.state == "talk"  # 글자는 끝났지만 소리 동안 입 움직임 유지
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
    assert (ASSETS / ian.card).is_file() and [c.name for c in roster.ROSTER][3] == "이안"
    names = {n for frames, _t, _l in br.IAN.anims.values() for n in frames}
    assert not [n for n in names if not (IAN_DIR / f"{n}.png").exists()]
    h = lambda n: imread(IAN_DIR / f"{n}.png", cv2.IMREAD_UNCHANGED).shape  # noqa: E731
    for name in ("stand_0", "stand_1", "crouch_0"):  # 나머지 서 있는 계열은 머리 폭 기준(아래 ±5% 테스트)
        assert abs(h(name)[0] - 285) <= 3, name
    assert abs(h("rise_0")[1] - h("crouch_2")[1]) <= 3  # 일어나기 첫 장 = 쪼그림 폭
    assert abs(_head(IAN_DIR / "rise_2.png") / _head(IAN_DIR / "stand_1.png") - 1) <= 0.05  # 끝 = 서 있는 머리 폭
    # 앉아 기다리기: 머리 폭 구간에 머리카락·어깨가 섞여 머리 폭으론 얼굴이 8% 커졌음(사용자 11-25) → 얼굴 템플릿으로 맞춤
    # (test_ian_sit_face_matches_crouch_and_rise). 머리 폭은 그만큼 작게 나옴(0.94)
    assert 0.90 <= _head(IAN_DIR / "sit_0.png") / _head(IAN_DIR / "stand_1.png") <= 1.0
    for n in ("talk_end1_0", "talk_end2_0"):  # v2 말 끝 두 장
        assert n in br.IAN.anims["talk_end"][0]


def test_ian_lines_have_alerts_stage_lines_and_watch_click():
    data = ln.read(IAN_DIR / "lines.json")
    assert data.character == "이안" and "click_sleep" not in data.lines
    assert set(ln.SITUATIONS) - {"click_sleep"} <= set(data.lines) and "idle_extra_click" in data.lines
    from mabinogi_addon.ui.notifier import alert_files
    sounds = alert_files(paths.resource_dir() / "sounds" / "차분한 남성") - {"파티 알림.mp3"}
    assert len(data.alerts) == 12 and sounds <= set(data.alerts)   # 11 + 투아림 2차 말풍선(11-24, 녹음은 나중)
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


def test_ian_standing_click_talks_right_away():
    """이안 서서 클릭(사용자 11-24): 쓰다듬기 첫 장(머리 크기 달라 튐) 없이 바로 말하기 — 사이 → 입."""
    b = _ian()
    b.press(1, 300, 600)
    assert b.release(1)[-1] == ("say", "click_stand") and b.state == "stand"
    assert b.talk(1, 10, "normal") is True and b.frame(1.05) == "talk_mid_0" and b.frame(1.25) == "talk_m1_0"
    assert "pet_0" not in {b.frame(1 + i * 0.05) for i in range(20)}
    d = _brain()  # 다래는 그대로(놀람 뒤 서 있기)
    d.press(1, 300, 600)
    d.release(1)
    assert d.state == "surprise" and d.talk(1, 10) is False


def test_ian_alert_points_at_watch():
    b = _ian()
    b.notify(1)
    assert b.state == "alert" and b.frame(1) == "talk_alert_0"
    _run(b, 1, 2.0, False)
    assert b.state in ("stand", "walk", "watch")


def test_walk_values_come_from_character_data_and_corner_rush_speeds_up_steps():
    """걷기 미끄러짐(사용자 11-24): 캐릭터별 프레임 시간·속도, 이안 v2 0.18초·62px/초(보폭 67px), 다래 새 걷기(11-25) 100px/초(디딘 발 장마다 약 21px 그리기 크기)."""
    assert br.IAN.walk_speed == 62.0 and br.IAN.anims["walk"][1] == (0.18,) * 6
    for profile in (br.DARE, br.ARIA, br.IAN, br.LENA, br.STARLINE):
        cycle = sum(profile.anims["walk"][1])
        assert 60 <= profile.walk_speed <= 100 and 60 <= profile.walk_speed * cycle <= 125  # 한 바퀴 거리 ≈ 보폭
    b = _ian()
    b._walk_to((800.0, 700.0), 0)
    _run(b, 0, 1.0, False)
    assert abs(b.pos[0] - 362.0) < 6  # 62px/초(첫 틱은 시간 0)
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
    assert abs(head_width("land_2") - stand) / stand <= 0.05  # 끝 = 서 있는 머리 폭


def test_ian_falls_with_one_frame():
    """이안 떨어지기(사용자 11-24): 두 장을 번갈면 두근거려 보여 fall_0 한 장만."""
    assert br.IAN.anims["fall"][0] == ("fall_0",)


def test_frame_anchor_loader_is_harmless_without_or_with_bad_file(app, tmp_path):
    """기준점 불러오기는 범용으로 남김(이안 떨어지기 한 장 결정 뒤 파일 없음) — 없거나 잘못되면 발 밑 그대로."""
    from mabinogi_addon.ui import pet_window

    assert pet_window._anchors(tmp_path) == {}
    (tmp_path / "anchors.json").write_text('{"a": [1, 2], "b": [1], "c": ["x", 1], "d": [999, 0], "e": [true, 0]}', encoding="utf-8")
    assert pet_window._anchors(tmp_path) == {"a": (1.0, 2.0)}
    (tmp_path / "anchors.json").write_text("not json", encoding="utf-8")
    assert pet_window._anchors(tmp_path) == {}
    assert not any((ASSETS / folder / "anchors.json").exists() for folder in ("다래", "아리아", "이안", "레나", "Starline"))
    frames = pet_window.load_frames("이안", br.IAN)
    w = pet_window.PetWindow(_ian(), frames, "#3B5B9A")
    try:
        assert all(w._frame_rect(image).bottom() == w.height() - 6 for image in frames.values())
    finally:
        w.close()


@pytest.mark.parametrize("folder,prefix", [("다래", "talk_"), ("아리아", "talk_a_"), ("아리아", "talk_b_"), ("이안", "talk_"),
                                           ("레나", "talk_"), ("Starline", "talk_")])
def test_mouth_only_frames_differ_only_around_the_mouth(folder, prefix):
    """입만 바꾸기(빌드 합성, 사용자 11-24): talk_base·m1·m2는 입 둘레 작은 곳 밖에서 알파·색이 똑같다."""
    import cv2
    import numpy as np
    from mabinogi_addon.image_io import imread

    base = imread(ASSETS / folder / f"{prefix}base_0.png", cv2.IMREAD_UNCHANGED)
    for key in ("m1", "m2"):
        other = imread(ASSETS / folder / f"{prefix}{key}_0.png", cv2.IMREAD_UNCHANGED)
        assert other.shape == base.shape
        diff = np.abs(other.astype(int) - base.astype(int)).max(-1) > 0
        ys, xs = np.where(diff)
        assert diff.any()  # 입은 달라야 함
        h, w = base.shape[:2]
        assert xs.max() - xs.min() < w * 0.25 and ys.max() - ys.min() < h * 0.13  # 입 둘레 밖은 0 차이
        assert h * 0.3 < ys.mean() < h * 0.65  # 얼굴(입) 높이


@pytest.mark.parametrize("profile", [br.DARE, br.ARIA, br.IAN, br.LENA, br.STARLINE])
def test_corner_without_saved_spot_is_nearest_screen_edge(profile):
    """사용자 11-24: 끌어서 정한 구석이 없으면 가까운 화면 끝(왼쪽일 수도) — 앉은 동안 유지, 다시 게임이 오면 다시 정함."""
    b = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(2), profile=profile)
    b.pos = (300.0, 700.0)
    b._next_walk = 1e9
    t, _ = _run(b, 0, 1.3, True)
    assert b.state == "walk" and b.facing_left  # 왼쪽 끝으로 걸어감(걷기 그림 뒤집기)
    t, _ = _run(b, t, 6, True)
    assert b.pos == (150.0, 700.0) and b.state in profile.sitting  # 왼쪽 끝(창 폭 절반 안쪽)에 앉음
    b.pos = (900.0, 700.0)  # 앉은 동안 다시 계산하지 않음(좌우로 안 튐)
    assert b.home() == (150.0, 700.0)
    b.pos = (150.0, 700.0)
    t, _ = _run(b, t, 3, False)  # 게임이 뒤로
    b.pos = (800.0, 700.0)
    b._go("stand", t)
    t, _ = _run(b, t, 6, True)  # 다시 앞 — 지금 자리(오른쪽) 기준
    assert b.pos == (850.0, 700.0) and b.state in profile.sitting


def test_saved_corner_still_wins_over_nearest_edge():
    b = _brain(corner=(400.0, 500.0))
    b.pos = (100.0, 700.0)
    t, _ = _run(b, 0, 6, True)
    assert b.pos == (400.0, 500.0)



def _head(path):
    import cv2
    import numpy as np
    from mabinogi_addon.image_io import imread

    a = imread(path, cv2.IMREAD_UNCHANGED)[..., 3] > 40
    cols = np.where(a[: int(a.shape[0] * 0.3)].any(0))[0]
    return cols.max() - cols.min() + 1


# 서 있는 계열(머리가 보이는 선 자세) — 사용자 11-24 '동작마다 머리 크기가 달라짐'
STANDING_FRAMES = {
    "아리아": ("stand", "walk", "surprise", "pet", "hair", "drag", "talk_a_", "talk_b_", "talk_happy", "talk_laugh",
             "getup_2", "rise_2", "land_0"),
    "이안": ("stand", "walk", "watch", "pet", "drag", "talk_", "fall_0", "land_2", "rise_2"),
    "레나": ("stand", "walk", "pet", "drag", "talk_", "rise_2", "land_3"),  # 쓰다듬기 시트도 머리 폭으로(사용자 11-24)
}
HEAD_EXEMPT = {
    "pet_0",    # 아리아: 머리 옆 '!' 표시가 위 30% 폭에 들어감(머리는 같은 배율)
    "drag_3",   # 이안: 몸이 기울어진 자세
}


@pytest.mark.parametrize("folder", ["아리아", "이안", "레나"])   # Starline은 후광·토끼귀라 위 30% 폭이 머리가 아님(시트별 키)
def test_standing_frames_keep_head_size_within_5_percent(folder):
    """서 있는 계열 머리 폭(위 30% 폭)이 stand의 ±5% — 다래는 헤일로·뿔 때문에 이 잣대가 머리가 아니라 제외."""
    d = ASSETS / folder
    ref = _head(d / ("stand_1.png" if folder == "이안" else "stand_0.png"))
    bad = {}
    for path in d.glob("*.png"):
        name = path.stem
        if name == "card" or name in HEAD_EXEMPT or not name.startswith(STANDING_FRAMES[folder]):
            continue
        ratio = _head(path) / ref
        if not 0.95 <= ratio <= 1.05:
            bad[name] = round(ratio, 3)
    assert not bad


# ---- 레나(화난 여성, 기획 11-24 '레나는 마무리해서 넘겨줘' — docs/characters/레나.md) ------------------------------
LENA_DIR = ASSETS / "레나"


def _lena(**kw):
    b = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(5), profile=br.LENA, **kw)
    b.pos = (300.0, 700.0)
    return b


def _img(name):
    import cv2
    from mabinogi_addon.image_io import imread
    return imread(LENA_DIR / f"{name}.png", cv2.IMREAD_UNCHANGED)


def test_lena_roster_card_and_every_frame():
    lena = roster.by_pack("화난 여성")
    assert (lena.name, lena.known, lena.has_pet, lena.color) == ("레나", True, True, "#5B6BC9")
    card = _img("card")
    assert abs(card.shape[1] / card.shape[0] - 1199 / 1312) < 0.02  # 가로형 상반신을 다른 카드와 같은 세로 비율로
    names = {n for frames, _t, _l in br.LENA.anims.values() for n in frames}
    assert not [n for n in names if not (LENA_DIR / f"{n}.png").exists()]
    assert _img("stand_0").shape[0] == 285 and _img("rise_2").shape[0] == 285 and _img("crouch_0").shape[0] == 285
    assert abs(_img("sit_0").shape[0] - _img("crouch_2").shape[0]) <= 3  # 앉아 있기 = 웅크리기 끝 높이
    from mabinogi_addon.ui import character_lines_feed
    assert character_lines_feed.REMOTE_NAMES["레나"] == "lena-lines.json"


def test_lena_falls_with_one_frame_and_lands_through_four_to_standing():
    assert br.LENA.anims["fall"][0] == ("fall_0",)
    assert br.LENA.anims["land"][:2] == (("land_0", "land_1", "land_2", "land_3"), (0.6, 0.35, 0.5, 0.8))
    b = _lena()
    b.press(0, 300, 600)
    b.move(0.1, 300, 300)
    b.release(0.2)
    assert b.state == "fall" and b.frame(0.3) == "fall_0"
    t, events = _run(b, 0.2, 0.8, False)
    assert b.state == "land" and ("say", "dropped") in events
    seen = set()
    while t < 4:
        t += 0.05
        b.tick(t, False)
        seen.add(b.state)
    assert "getup" not in seen and b.state in ("stand", "walk")


def test_lena_standing_click_talks_right_away_and_ends_with_two_end_frames():
    b = _lena()
    b.press(1, 300, 600)
    assert b.release(1)[-1] == ("say", "click_stand") and b.state == "stand"
    assert b.talk(1, 6, "normal") is True and b.frame(1.05) == "talk_mid_0" and b.frame(1.25) == "talk_m1_0"
    assert "pet_0" not in {b.frame(1 + i * 0.05) for i in range(20)}
    t, _ = _run(b, 1, 0.85, False)
    assert b.state == "talk_end"
    t0 = b._t0
    assert [b.frame(t0 + x) for x in (0.1, 0.4, 0.6)] == ["talk_base_0", "talk_end1_0", "talk_end2_0"]
    _run(b, t, t0 + 0.75, False)
    assert b.state in ("stand", "walk")
    e = _lena()
    assert e.talk(1, 20, "explain") and e.frame(1.25) == "talk_emph_0"  # 설명 = 손가락 먼저
    for mood in ("think", "happy"):  # 생각·기쁨 그림 없음 → 보통
        m = _lena()
        assert m.talk(1, 6, mood) and m.state == "talk"


def test_lena_sits_without_dozing_click_keeps_sit_picture():
    b = _lena(corner=(900.0, 700.0))
    t, _ = _run(b, 0, 6, True)
    seen = set()
    for _ in range(600):
        t += 0.05
        b.tick(t, True)
        seen.add(b.frame(t))
        assert not b.zzz() and b.state not in ("sit_doze", "wake")
    assert {"sit_0", "sit_1", "sit_2", "sit_3"} <= seen
    frames, times, _loop = br.LENA.anims["sit_loop"]
    zero = sum(d for f, d in zip(frames, times) if f == "sit_0")
    assert zero / sum(times) > 0.7  # 0번이 길게, 나머지는 가끔
    b.press(t, 900, 600)
    assert b.release(t)[-1] == ("say", "click_sit") and b.frame(t) == "sit_0"


def test_lena_pet_sequence_and_one_pixel_shake():
    assert br.LENA.anims["pet_in"][:2] == (("pet_0", "pet_1"), (0.4, 0.4))
    assert br.LENA.anims["pet_out"][:2] == (("pet_5",), (1.6,))
    b = _lena()
    b._go("pet_loop", 0)
    b._last_rub = 0
    shakes = {b.shake(i * 0.13 + 0.01) for i in range(4)}
    assert shakes == {-1, 0, 1}
    b._go("stand", 1)
    assert b.shake(1.2) == 0 and _ian().shake(0.2) == 0


def test_lena_partial_composites_keep_body_identical():
    """부분 합성(빌드): 쓰다듬기 3·4번은 2번과 얼굴 둘레 밖이 같고, 앉아 있기 1·2·3번은 0번과 바뀐 덩어리 밖이 같다."""
    import numpy as np

    for base, others, limit in (("pet_2", ("pet_3", "pet_4"), 0.5), ("sit_0", ("sit_1", "sit_2", "sit_3"), 0.5)):
        a = _img(base)
        for name in others:
            o = _img(name)
            assert o.shape == a.shape
            diff = np.abs(o.astype(int) - a.astype(int)).max(-1) > 0
            assert diff.any() and diff.mean() < 0.15, name
            ys, xs = np.where(diff)
            assert xs.max() - xs.min() < a.shape[1] * limit + 40 and ys.max() - ys.min() < a.shape[0] * limit, name


def test_lena_alert_lines_pick_one_of_two_and_old_string_format_still_reads():
    data = ln.read(LENA_DIR / "lines.json")
    from mabinogi_addon.ui.notifier import alert_files
    sounds = alert_files(paths.resource_dir() / "sounds" / "화난 여성") - {"파티 알림.mp3"}
    assert len(data.alerts) == 12 and sounds <= set(data.alerts)  # 11 + 투아림 2차(한 줄, 11-24)
    assert all(len(v) == 2 for k, v in data.alerts.items() if k != "투아림 부스트 발동 직전2.mp3")
    picker = ln.Picker(data, random.Random(3))
    seen = {picker.alert("비바체 연장.mp3").text for _ in range(40)}
    assert seen == {"비바체, 설마 잊은 거 아니지?", "비바체 또 잊었지? 이런 것도 못 해?"}
    assert picker.alert("투아림 부스트 발동 직전2.mp3").text == "투아림 터진다고! 준비 안 했으면 혼나!"
    old = ln.parse(json.dumps({"schemaVersion": 2, "character": "x", "lines": {"idle": ["a"]},
                               "alerts": {"a.mp3": "알림", "b.mp3": ["하나", "y" * 40, 3], "c.mp3": []}}).encode())
    assert old.alerts == {"a.mp3": ("알림",), "b.mp3": ("하나",)}
    assert ln.Picker(old).alert("a.mp3") == ln.Line("알림")


def test_lena_lines_situations_stage_lines_and_voices():
    data = ln.read(LENA_DIR / "lines.json")
    assert data.character == "레나" and "click_sleep" not in data.lines
    assert set(ln.SITUATIONS) - {"click_sleep"} <= set(data.lines)
    staged = [line for items in data.lines.values() for line in items if line.stage > 0]
    assert len(staged) == 24 and [line.stage for line in data.lines["stage_up"]] == [25, 50, 75, 100]
    voices = {line.voice: (key, line.text) for key, items in data.lines.items() for line in items if line.voice}
    names = ["켜기_1", "켜기_2", "오랜만", "밤", "게임시작", "게임끝", "휴식", "쓰다듬기끝", "클릭", "착지",
             "구간_25", "구간_50", "구간_75", "구간_100"]
    assert set(voices) == {f"대사/{n}.mp3" for n in names}  # 녹음목록.md '레나' 표(인사·투아림2 뺀 14줄)
    assert voices["대사/착지.mp3"] == ("dropped", "…방금 거, 못 본 걸로 해.")
    assert voices["대사/구간_100.mp3"] == ("stage_up", "…이 초커, 너 가져. 잃어버리면 화낼 거야.")


@pytest.mark.parametrize("folder", ["다래", "아리아", "레나", "Starline"])
def test_sheet_colors_match_standing_hair_and_skin(folder):
    """시트 색 맞추기(사용자 11-24 '동작마다 머리색·피부 톤이 다름'): 모든 그림의 머리·피부가 서 있기 대비 ΔE<3."""
    import cv2
    from scripts.color_parts import PARTS, STAND
    from scripts.sheet_colors import report

    d = ASSETS / folder
    frames = {p.stem: _img_of(p) for p in d.glob("*.png") if p.stem != "card"}
    rows = report(frames, frames[STAND[folder]], PARTS[folder])
    bad = {name: row for name, row in rows.items() if any(v is not None and v >= 3 for v in row)}
    assert not bad
    assert sum(row[0] is not None for row in rows.values()) >= len(rows) * 0.9  # 머리는 거의 모든 그림에서 잼
    del cv2


@pytest.mark.parametrize("folder,sheet_path", [
    ("아리아", "아리아/SD/파스텔 치비 소녀 걷기 스프라이트.png"),
    ("아리아", "아리아/SD/투명 배경 치비 캐릭터 4컷 스프라이트.png"),
    ("레나", "레나/SD/레나_쓰다듬기.png"),
    ("다래", "다래/SD/부끄러운 치비 천사 악마 스티커 세트.png"),
    ("Starline", "Starline/SD/Starline_구석_앉아있기.png"),   # 금 동전(마법진)·후광은 그대로
])
def test_sheet_colors_touch_only_hair_and_skin(folder, sheet_path):
    """바뀌는 픽셀은 머리·피부 마스크(+흐림 둘레 5px) 안뿐 — 옷(검정·크림 드레스·리본·장화)·눈은 그대로."""
    import cv2
    import numpy as np
    from scripts.build_aria_frames import clean
    from scripts.build_dare_frames import ROOT, imread, split
    from scripts.color_parts import PARTS, STAND
    from scripts.sheet_colors import apply, colors, diffs, masks

    parts = PARTS[folder]
    targets = colors(_img_of(ASSETS / folder / f"{STAND[folder]}.png"), parts)
    for raw in split(clean(imread(ROOT / "docs/characters/assets" / sheet_path, cv2.IMREAD_UNCHANGED)))[:3]:
        fixed = apply(raw, parts, diffs(raw, parts, targets))
        changed = (fixed != raw).any(-1)
        union = np.zeros(raw.shape[:2], np.uint8)
        for m in masks(raw, parts):
            union |= m.astype(np.uint8)
        near = cv2.dilate(union, np.ones((11, 11), np.uint8)) > 0  # 흐림(σ1.2)이 닿는 둘레
        assert not (changed & ~near).any()
        hsv = cv2.cvtColor(np.ascontiguousarray(raw[..., :3]), cv2.COLOR_BGR2HSV)
        dark = (hsv[..., 2] < 60) & (raw[..., 3] > 0)   # 검은 옷·눈동자·외곽선
        assert not (changed & dark).any()


def _img_of(path):
    import cv2
    from mabinogi_addon.image_io import imread
    return imread(path, cv2.IMREAD_UNCHANGED)


# ---- Starline(장난스러운 남성, 기획 11-24 '음성팩 들어갈 자리만 만들고 같이 알파로' — docs/characters/Starline.md) ----
SL_DIR = ASSETS / "Starline"


def _starline(profile=br.STARLINE, **kw):
    b = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(4), profile=profile, **kw)
    b.pos = (300.0, 700.0)
    return b


def test_starline_roster_english_name_gold_outline_and_frames():
    sl = roster.ROSTER[0]   # 카드 맨 앞(11-24)
    assert (sl.key, sl.name, sl.pack, sl.color, sl.outline) == ("장난스러운 남성", "Starline", "장난스러운 남성", "#3A0729", "#D8AA5E")
    assert len(roster.ROSTER) == 6 and all(c.outline == "#FFFFFF" for c in roster.ROSTER[1:])
    assert sl.name.isascii() and roster.folder(sl) == "Starline"
    card = _img_of(SL_DIR / "card.png")
    assert abs(card.shape[1] / card.shape[0] - 224 / 260) < 0.005   # 손 전체 보이게(기획 11-25) — 카드 비율 그대로
    from mabinogi_addon.ui import character_tab as ct
    assert ct.CARD_FIT_HEIGHT == {"Starline"}
    names = {n for frames, _t, _l in br.STARLINE.anims.values() for n in frames}
    assert not [n for n in names if not (SL_DIR / f"{n}.png").exists()]
    assert _img_of(SL_DIR / "stand_0.png").shape[0] == 285   # 나머지는 머리 크기 기준(아래 ±5% 테스트)
    from mabinogi_addon.ui import character_lines_feed
    assert character_lines_feed.REMOTE_NAMES["Starline"] == "starline-lines.json"


def test_starline_talk_sheet_split_six_loop_and_two_end():
    """말하기(B안 11-24): 반복 시트 6장, 끝 = 시작 2장 거꾸로(손 든 자세 → 중간 = 사이 그림과 같음) → 서기."""
    import cv2
    from scripts.build_aria_frames import clean
    from scripts.build_dare_frames import ROOT, imread, split

    frames = split(clean(imread(ROOT / "docs/characters/assets/Starline/SD/Starline_말하기_반복.png", cv2.IMREAD_UNCHANGED)))
    assert len(frames) == 6   # B안(11-24) 새 반복 시트 — 끝은 시작 2장 거꾸로
    for key in ("base", "m1", "m2", "emph", "emph2", "blink", "mid", "end1", "end2"):
        assert (SL_DIR / f"talk_{key}_0.png").exists()
    assert br.STARLINE.anims["talk_end"][0] == ("talk_base_0", "talk_end1_0", "talk_end2_0")
    import numpy as np
    assert np.array_equal(_img_of(SL_DIR / "talk_end2_0.png"), _img_of(SL_DIR / "talk_mid_0.png"))


def test_starline_flame_idle_click_talks_and_corner():
    b = _starline()
    b._next_walk = 1e9
    t, _ = _run(b, 0, 16, False)
    assert b.state == "flame" or b._extra_until > 0   # 가만히 서 있으면 가끔 손바닥 불꽃
    b._go("flame", t)
    b._extra_until = t + 5
    b.press(t, 300, 600)
    assert b.release(t) == [("click",), ("say", "idle_extra_click")]   # 불꽃 중 클릭
    s = _starline()
    s.press(1, 300, 600)
    assert s.release(1)[-1] == ("say", "click_stand") and s.state == "stand"
    assert s.talk(1, 20, "explain") and s.frame(1.25) == "talk_emph_0"
    c = _starline(corner=(900.0, 700.0))
    t, _ = _run(c, 0, 6, True)
    seen = set()
    for _ in range(100):
        t += 0.05
        c.tick(t, True)
        seen.add(c.frame(t))
        assert not c.zzz()
    assert {"sit_0", "sit_1", "sit_2", "sit_3"} <= seen
    c.press(t, 900, 600)
    assert c.release(t)[-1] == ("say", "click_sit") and c.frame(t) == "sit_0"


def test_starline_lines_alerts_and_stage_lines():
    data = ln.read(SL_DIR / "lines.json")
    assert data.character == "Starline" and "click_sleep" not in data.lines
    assert set(ln.SITUATIONS) - {"click_sleep"} <= set(data.lines) and "idle_extra_click" in data.lines
    assert len(data.alerts) == 13 and {"투아림 부스트 발동 직전2.mp3", "파티 알림.mp3"} <= set(data.alerts)
    staged = [line for items in data.lines.values() for line in items if line.stage > 0]
    assert len(staged) == 24 and [line.stage for line in data.lines["stage_up"]] == [25, 50, 75, 100]
    assert not [line for items in data.lines.values() for line in items if line.voice]   # 녹음 전 — 목소리 키 없음


def test_empty_voice_pack_hidden_from_settings_and_falls_back_to_default(monkeypatch, tmp_path):
    """목소리 팩 자리만(11-24 Starline 처음): 폴더는 있지만 녹음이 없으면 설정 목록에 안 보이고, 알림·카드 미리듣기는 기본 녹음."""
    from mabinogi_addon import config
    from mabinogi_addon.ui import notifier

    tmp_path = tmp_path / "sounds"
    tmp_path.mkdir()
    (tmp_path / "빈 팩").mkdir()
    (tmp_path / "빈 팩" / ".gitkeep").write_bytes(b"")
    (tmp_path / "찬 팩").mkdir()
    (tmp_path / "찬 팩" / "비바체 연장.mp3").write_bytes(b"x")
    for name in ("비바체 연장.mp3", "투아림 부스트 발동 직전.mp3"):
        (tmp_path / name).write_bytes(b"x")
    monkeypatch.setattr(notifier, "SOUND_DIR", tmp_path)
    assert notifier.list_voice_packs() == ["찬 팩"]
    assert notifier.list_voice_packs(include_empty=True) == ["빈 팩", "찬 팩"]
    monkeypatch.setattr(config, "load_voice_pack", lambda *a, **k: "빈 팩")
    assert notifier.sound_path("비바체 연장.mp3") == tmp_path / "비바체 연장.mp3"
    assert notifier.greeting_path("빈 팩") == tmp_path / "투아림 부스트 발동 직전.mp3"


def test_starline_pack_has_recordings_and_shows_in_settings(monkeypatch):
    """Starline 녹음 12개(사용자 11-24 '목소리 추가했어 연결해줘'): 설정 목록에 보임, 투아림 2차는 이 팩 파일, 파티는 기본 녹음."""
    from mabinogi_addon import config
    from mabinogi_addon.ui import notifier

    folder = notifier.SOUND_DIR / "장난스러운 남성"
    files = notifier.alert_files(folder)
    assert len(files) == 12 and "파티 알림.mp3" not in files and "장난스러운 남성" in notifier.list_voice_packs()
    monkeypatch.setattr(config, "load_voice_pack", lambda *a, **k: "장난스러운 남성")
    assert notifier.sound_path("비바체 연장.mp3") == folder / "비바체 연장.mp3"
    assert notifier.second_sound_path("투아림 부스트 발동 직전.mp3") == folder / "투아림 부스트 발동 직전2.mp3"
    assert notifier.sound_path("파티 알림.mp3") == notifier.SOUND_DIR / "파티 알림.mp3"
    data = ln.read(SL_DIR / "lines.json")
    assert files <= set(data.alerts)   # 녹음마다 같은 문장 말풍선


def test_alert_bubble_outlasts_longest_recording():
    """알림은 말하기 그림이 아니라 알림 자세(짧게) + 말풍선 — 말풍선은 가장 짧은 글도 4.5초+글자 시간이라
    Starline 녹음(가장 긴 3.9초)보다 오래 남음(기획 11-24 '녹음이 3초 넘는 게 있어' 확인)."""
    from mabinogi_addon.ui import pet_window

    for folder in ("다래", "아리아", "이안", "레나", "Starline"):
        shortest = min(len(t) for texts in ln.read(ASSETS / folder / "lines.json").alerts.values() for t in texts)
        assert shortest * br.TYPE_SECONDS + pet_window.BUBBLE_SECONDS > 3.9 + 1.0


@pytest.mark.parametrize("folder,first", [("다래", None), ("아리아", None), ("이안", None), ("레나", None)])
def test_tuarim_second_alert_bubble_differs_from_first(folder, first):
    """투아림 추가 알림 말풍선(기획 11-24 '목소리 있는 애들 투아림 2차 대사 정리') — 1차와 다른 줄."""
    data = ln.read(ASSETS / folder / "lines.json")
    second = data.alerts["투아림 부스트 발동 직전2.mp3"]
    assert len(second) == 1 and second[0] not in data.alerts["투아림 부스트 발동 직전.mp3"]


def test_starline_bubble_has_gold_outline(app):
    from mabinogi_addon.ui import pet_window

    frames = pet_window.load_frames("Starline", br.STARLINE)
    w = pet_window.PetWindow(_starline(), frames, "#3A0729", outline="#D8AA5E")
    d = pet_window.PetWindow(_starline(), frames, "#B48CE6", outline="#FFFFFF")
    try:
        assert w.outline is not None and w.outline.name() == "#d8aa5e" and d.outline is None
    finally:
        w.close()
        d.close()


def test_starline_head_size_matches_standing_within_5_percent():
    """Starline 머리 크기(사용자 11-24 Windows '불꽃·잡기·떨어지기는 머리가 작고 착지 때 커짐', B안 긴 체형): 후광·토끼귀로 위 30%
    폭은 못 써서 얼굴 맞추기(점수 0.5 이상) 또는 눈 간격으로 잼 — 시트(동작)마다 중앙값이 서 있기 ±5%, 그림 하나는 ±10%
    (손이 얼굴을 가리거나 귀를 젖힌 장은 재는 값이 흔들림). 예외: 눈 감은 장(talk_blink·sit_3 — 얼굴 맞추기가 틀어짐),
    걷기(옆모습 — None)."""
    from scripts.build_starline_frames import eye_gap, face_crop, head_ratio

    stand = _img_of(SL_DIR / "stand_0.png")
    face, eyes = face_crop(stand), eye_gap(stand)
    sheets, bad = {}, {}
    for path in SL_DIR.glob("*.png"):
        if path.stem in ("card", "frame") or path.stem in ("talk_blink_0", "sit_3") or path.stem.startswith("sneeze_"):
            # 재채기는 같은 자세 0·5번 실루엣으로 맞춤(QA 11-25 — 얼굴 창은 머리카락에 끌림) → 실루엣 테스트가 맡음
            continue
        r = head_ratio(face, eyes, _img_of(path))
        if r is None:
            continue
        sheets.setdefault(path.stem.rsplit("_", 1)[0], []).append(r)
        if not 0.9 <= r <= 1.1:
            bad[path.stem] = round(r, 3)
    medians = {k: round(float(sorted(v)[len(v) // 2]), 3) for k, v in sheets.items()}
    assert not bad and not {k: m for k, m in medians.items() if not 0.95 <= m <= 1.05}
    assert sum(len(v) for v in sheets.values()) >= 30
    for name in ("flame_0", "drag_0", "fall_0", "land_2"):   # 사용자가 짚은 그림은 꼭 잼
        assert head_ratio(face, eyes, _img_of(SL_DIR / f"{name}.png")) is not None, name


def test_starline_click_and_land_show_one_picture_at_a_time(app):
    """덮기 전환 없음 — 서서 클릭(서기 → 사이)·착지 → 서기 동안 layers()가 늘 한 장."""
    from mabinogi_addon.ui import pet_window

    clock = {"t": 1.0}
    b = _starline()
    w = pet_window.PetWindow(b, pet_window.load_frames("Starline", br.STARLINE), "#3A0729", clock=lambda: clock["t"],
                             outline="#D8AA5E")
    try:
        w.step()
        b.talk(clock["t"], 10)
        for _ in range(20):
            clock["t"] += 0.03
            w.step()
            assert len(w.layers(clock["t"])) == 1
        b._go("land", clock["t"])
        for _ in range(80):
            clock["t"] += 0.03
            w.step()
            assert len(w.layers(clock["t"])) == 1
    finally:
        w.close()


def test_known_cards_fill_down_to_card_bottom():
    """카드 224×280(기획 11-25): 그림은 양옆을 잘라 높이를 채움(가운데 기준 폭 = 높이×224/280) — 모든 카드·착장 카드가
    그만큼 넓어야 아래가 비지 않음(머리 위 20px만큼 아래가 잘림)."""
    from mabinogi_addon.character import outfits
    from mabinogi_addon.ui import character_tab as ct

    assert (ct.CARD_W, ct.CARD_H, ct.HEAD_ROOM) == (224, 280, 20)
    paths = [ASSETS / c.card for c in roster.ROSTER if c.known]
    paths += [ASSETS / outfits.asset(f, o.key, "card.png") for f, items in outfits.OUTFITS.items() for o in items[1:]]
    for path in paths:
        art = _img_of(path)
        assert art.shape[1] >= art.shape[0] * ct.CARD_W / ct.CARD_H, path


@pytest.mark.parametrize("profile,folder,scale", [(br.DARE, "다래", 1.0), (br.ARIA, "아리아", 1.0), (br.IAN, "이안", 1.0),
                                                  (br.LENA, "레나", 0.95), (br.STARLINE, "Starline", 1.15)])
def test_character_scale_applies_to_every_frame_and_fits_window(app, profile, folder, scale):
    """캐릭터별 그리기 배율(사용자 11-24 B안 — 얼굴 크기 맞춤: Starline ×1.15, 레나 ×0.95): 서 있기 그리기 키 = 190×배율,
    모든 프레임이 창 안(위·옆 잘림 없음), 잡기 판정(그림 영역)이 그림 크기를 따라감."""
    from mabinogi_addon.ui import pet_window

    assert profile.scale == scale
    b = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(1), profile=profile)
    frames = pet_window.load_frames(folder, profile)
    w = pet_window.PetWindow(b, frames, "#888888")
    try:
        stand = profile.anims["stand"][0][0]
        rect = w._frame_rect(frames[stand])
        assert abs(rect.height() - br.FIGURE_H * scale * frames[stand].height() / pet_window.FRAME_DIR_H) < 0.5
        for name, image in frames.items():
            r = w._frame_rect(image)
            assert r.top() >= 0 and r.left() >= 0 and r.right() <= pet_window.WIN_W, name
        w.step()
        w.grab()   # paintEvent가 그린 자리(_sprite)를 정함
        sprite = w._sprite
        assert abs(sprite.height() - w._frame_rect(frames[w._cur_name]).height()) < 0.01   # 그린 자리 = 배율 적용 크기
        from PySide6.QtCore import QPointF
        inside = QPointF(sprite.center().x(), sprite.top() + sprite.height() * 0.6)
        above = QPointF(sprite.center().x(), sprite.top() - 4)
        assert w._on_figure(inside) and not w._on_figure(above)   # 판정이 그려진 크기를 따라감
    finally:
        w.close()


def test_affinity_frozen_in_beta_but_reactions_stay():
    """캐릭터 베타(사용자 11-24 '당분간 호감도가 안 올라가게'): 켜기·쓰다듬기 끝까지·알림·구석 30분·반복 클릭 뒤에도
    값·오늘 오른 양·퀘스트 누적·연속 켜기 그대로. 짜증 반응(반복 클릭·쓰다듬기 4번째)은 그대로. 제작자 직접 조절은 됨."""
    assert aff.GROWTH is False
    a = aff.Affinity.load({"value": 30, "cleared": 1, "streak": 2, "lastLaunch": "2026-11-23",
                           "totals": {"pets": 1, "corner_minutes": 5, "alerts": 2}})
    before = a.to_dict()
    assert a.launched(DAY) == 0 and a.alerted(DAY) == 0
    for _ in range(31):
        assert a.corner_minute(DAY) == 0
    results = [a.petted(100.0 + i * 70, DAY) for i in range(4)]
    assert results[:3] == ["gain"] * 3 and results[3] == "annoyed"   # 4번째는 짜증(값은 그대로)
    assert any(a.click(500.0 + i * 0.5) for i in range(6))           # 반복 클릭 짜증 반응
    after = a.to_dict()
    for key in ("value", "cleared", "streak", "totals", "gained"):
        assert after.get(key) == before.get(key), key
    a.set_value(75)   # 제작자 조절은 그대로 됨
    assert a.value == 75


def test_creator_affinity_edit_still_saves_in_beta(app, cfg):
    from mabinogi_addon.ui import character_tab as ct

    tab = ct.CharacterTab()
    tab.set_creator(True)
    i = [c.character.key for c in tab.cards].index("조용한 여성")
    tab.editors[i].buttons[2].click()
    assert config.load_affinity("조용한 여성")["value"] == 50 and tab.cards[i]._affinity == 50
    tab.set_creator(False)
    assert not tab.cards[i].details_visible() and tab.cards[i].height() == ct.PAD_TOP + ct.CARD_H + ct.PAD_BOTTOM


def test_default_voice_button_returns_to_recorded_voice(app, cfg, monkeypatch):
    """0.56.0(사용자 11-24 '기본을 원하는 사람이 있긴 할 거 같은데'): 카드를 고른 뒤 `기본 목소리로` → 팩 "" ·
    카드 선택 없음 · voice_pack_changed 1번 · 기본 안내 글 · 기본 녹음 미리듣기. 이미 기본이면 버튼 비활성."""
    from mabinogi_addon.ui import character_tab as ct
    from mabinogi_addon.ui import notifier

    played = []
    monkeypatch.setattr(ct.CharacterTab, "_play_sample",
                        lambda self, pack: played.append(notifier.greeting_path(pack)))
    tab = ct.CharacterTab()
    assert not tab.default_button.isEnabled()   # 처음엔 기본
    tab.choose(roster.DARE)
    assert tab.default_button.isEnabled()
    changed = []
    tab.voice_pack_changed.connect(lambda: changed.append(1))
    tab.default_button.click()
    assert config.load_voice_pack() == "" and not any(c.selected() for c in tab.cards) and changed == [1]
    assert "기본 녹음 목소리" in tab.pet_hint.text() and not tab.default_button.isEnabled()
    assert played[-1] == notifier.SOUND_DIR / notifier.SAMPLE_FILE   # 기본 녹음 미리듣기


def test_card_click_previews_only_and_apply_button_moves(app, cfg, monkeypatch):
    """카드 고르기(사용자 11-25 B안): 누르면 인사만(저장 안 함), 쓰는 중이 아닌 카드엔 안쪽 '이 캐릭터로 적용'(한 번에 하나 —
    다른 카드 누르면 옮겨 감), 쓰는 중인 카드는 눌러도 버튼 없음·대기 풀림, 적용 = 저장·신호, 기본 목소리로·탭 떠나기는 대기 풀림."""
    from mabinogi_addon.ui import character_tab as ct

    played, saved = [], []
    monkeypatch.setattr(ct.CharacterTab, "_play_sample", lambda self, pack: played.append(pack))
    real_save = config.save_voice_pack
    monkeypatch.setattr(config, "save_voice_pack", lambda pack, *a, **k: saved.append(pack) or real_save(pack, *a, **k))
    tab = ct.CharacterTab()
    changed = []
    tab.voice_pack_changed.connect(lambda: changed.append(1))
    by = {c.character.name: c for c in tab.cards}
    by["레나"].clicked.emit(by["레나"].character)
    assert saved == [] and played == ["화난 여성"] and [c for c in tab.cards if c.pending()] == [by["레나"]]
    by["다래"].clicked.emit(by["다래"].character)
    assert [c for c in tab.cards if c.pending()] == [by["다래"]]   # 버튼이 옮겨 감
    by["다래"].apply_button.click()
    assert saved == ["조용한 여성"] and changed == [1] and by["다래"].selected() and not any(c.pending() for c in tab.cards)
    by["다래"].clicked.emit(by["다래"].character)                  # 쓰는 중 카드 — 인사만, 버튼 없음
    assert played[-1] == "조용한 여성" and not by["다래"].pending() and saved == ["조용한 여성"]
    by["이안"].clicked.emit(by["이안"].character)
    tab.default_button.click()
    assert not any(c.pending() for c in tab.cards)
    by["이안"].clicked.emit(by["이안"].character)
    tab.show()
    tab.hide()
    assert not any(c.pending() for c in tab.cards)
    assert by["이안"].size() == by["레나"].size()   # 버튼이 카드 안 — 크기 그대로


def test_greeting_random_among_existing_without_repeat(tmp_path, monkeypatch):
    """인사 여러 개(사용자 11-25): 인사.mp3·인사2~5.mp3 중 있는 것만 무작위, 같은 것 연속 금지, 하나면 그것, 없으면 투아림.
    '인사'로 시작하는 파일은 알림 소리 목록에 안 들어감."""
    from mabinogi_addon.ui import notifier

    sounds = tmp_path / "sounds"
    pack = sounds / "팩"
    pack.mkdir(parents=True)
    (sounds / notifier.SAMPLE_FILE).write_bytes(b"x")
    for name in ("인사.mp3", "인사2.mp3", "인사4.mp3", "비바체 연장.mp3"):
        (pack / name).write_bytes(b"x")
    monkeypatch.setattr(notifier, "SOUND_DIR", sounds)
    monkeypatch.setattr(notifier, "_last_greeting", {})
    seq = [notifier.greeting_path("팩", random.Random(i)).name for i in range(40)]
    assert set(seq) == {"인사.mp3", "인사2.mp3", "인사4.mp3"} and all(a != b for a, b in zip(seq, seq[1:]))
    assert notifier.alert_files(pack) == {"비바체 연장.mp3"}
    one = sounds / "하나"
    one.mkdir()
    (one / "인사3.mp3").write_bytes(b"x")
    assert {notifier.greeting_path("하나").name for _ in range(3)} == {"인사3.mp3"}
    (sounds / "없음").mkdir()
    monkeypatch.setattr(config, "load_voice_pack", lambda *a, **k: "")
    assert notifier.greeting_path("없음") == sounds / notifier.SAMPLE_FILE


@pytest.mark.parametrize("profile,rare", [(br.ARIA, "stretch"), (br.LENA, "magic"), (br.STARLINE, "sneeze")])
def test_rare_basic_motion_only_standing_out_of_game_every_3_to_6_minutes(profile, rare):
    """드문 기본 동작(기획 11-25 '너무 자주 나오면 이상함'): 게임 밖 서 있기에서만 3~6분에 한 번·1바퀴 뒤 서기,
    간격 안엔 안 나옴, 게임 중엔 안 나옴, 클릭하면 바로 끊김, 대기 동작과 같은 때 겹치지 않음."""
    assert profile.rare_extra == rare and profile.rare_gap == (180.0, 360.0)
    b = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(2), profile=profile)
    b.pos = (300.0, 700.0)
    b._next_walk = 1e9
    t, starts, last = 0.0, [], None
    while t < 1500:
        t += 0.25
        b._next_walk = max(b._next_walk, 1e9)
        b._next_idle = 1e9
        b.tick(t, False)
        if b.state == rare and last != rare:
            starts.append(t)
            assert profile.idle_extra is None or b._next_extra > t   # 대기 동작이 같은 때 끼지 않음
        last = b.state
    gaps = [b2 - a for a, b2 in zip(starts, starts[1:])]
    assert starts and starts[0] >= 180 and all(175 <= g <= 375 for g in gaps), (starts, gaps)
    c = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(2), profile=profile)
    c.pos = (300.0, 700.0)
    c.corner = (900.0, 700.0)
    t = 0.0
    while t < 800:
        t += 0.5
        c.tick(t, True)
        assert c.state != rare   # 게임 중엔 안 나옴
    d = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(2), profile=profile)
    d.pos = (300.0, 700.0)
    d._next_walk = 1e9
    d.tick(0, False)
    d._next_rare, d._next_walk, d._next_idle = 1.0, 1e9, 1e9
    d.tick(2, False)
    assert d.state == rare
    d.press(2.1, 300, 600)
    d.release(2.1)
    assert d.state != rare   # 클릭하면 바로 끊김


def test_rare_motion_waits_for_idle_line_and_settings_override():
    b = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(1), profile=br.ARIA)
    b.pos = (300.0, 700.0)
    b._next_walk = 1e9
    b.tick(0, False)
    b._next_rare, b._next_walk, b._next_idle = 1.0, 1e9, 10.0   # 혼잣말이 곧 → 미룸
    b.tick(2, False)
    assert b.state != "stretch" and b._next_rare >= 2 + br.RARE_DEFER - 0.01
    custom = br.ARIA.with_timing({"rareGap": [60, 90], "sleepGap": [40, 50]})
    assert custom.rare_gap == (60.0, 90.0) and custom.sleep_gap is None   # 엎드려 자기 없는 캐릭터는 그대로
    dare = br.DARE.with_timing({"sleepGap": [40, 50], "sleepHold": [10, 12]})
    assert dare.sleep_gap == (40.0, 50.0) and dare.sleep_hold == (10.0, 12.0)


def test_starline_sneeze_says_line_at_frame_four_once():
    b = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(1), profile=br.STARLINE)
    b.pos = (300.0, 700.0)
    b._next_walk = 1e9
    b.tick(0, False)
    b._next_rare, b._next_walk, b._next_idle, b._next_extra = 1.0, 1e9, 1e9, 1e9
    t, events = 0.0, []
    while t < 8:
        t += 0.05
        events += b.tick(t, False)
    assert events.count(("say", "sneeze")) == 1
    lines = ln.read(SL_DIR / "lines.json").lines["sneeze"]
    assert "누가 내 욕하나?" in [line.text for line in lines]


def test_dare_lies_down_every_3_to_6_minutes_in_corner_then_sits_again():
    """다래 엎드려 자기(기획 11-25 정정 — '구석에서는 자주 보이게'): 구석에 앉은 뒤 3~6분에 한 번 엎드림(0→2) →
    숨쉬기 20~40초(Zzz) → 6·7·8로 앉아 원래 앉아 있기로. 엎드린 동안 클릭 = 자다 깸, 게임 끝 = 앉은 뒤 일어나기."""
    assert br.DARE.sleep_gap == (180.0, 360.0) and br.DARE.sleep_hold == (20.0, 40.0) and br.IAN.sleep_gap is None
    b = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(3), profile=br.DARE, corner=(900.0, 700.0))
    b.pos = (300.0, 700.0)
    t, seen = 0.0, []
    while t < 1000:
        t += 0.25
        b.tick(t, True)
        seen.append((t, b.state))
    sat = next(x for x, s in seen if s == "crouch")
    downs = [x for (x, s), (_, prev) in zip(seen[1:], seen) if s == "sleep_down" and prev != "sleep_down"]
    assert downs and 180 <= downs[0] - sat <= 365
    loop = [x for x, s in seen if s == "sleep_loop" and downs[0] < x < downs[0] + 60]
    assert 19 <= loop[-1] - loop[0] <= 41   # 숨쉬기 20~40초
    after = [s for x, s in seen if loop[-1] < x < loop[-1] + 6]
    assert "sleep_up" in after and br.DARE.sit_state in after   # 다시 구석 앉아 있기로
    assert all(s in br.DARE.sitting for x, s in seen if x > sat + 1)   # 게임 중엔 계속 구석
    assert len(downs) >= 2 and all(175 <= b2 - a <= 420 for a, b2 in zip(downs, downs[1:]))
    # 엎드린 동안 클릭 → 자다 깸 / 게임 끝 → 앉은 뒤 일어나기
    c = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(3), profile=br.DARE, corner=(900.0, 700.0))
    c.pos = (300.0, 700.0)
    t = 0.0
    while c.state != "sleep_loop":
        t += 0.25
        c.tick(t, True)
    assert c.zzz()
    c.press(t, 900, 650)
    assert c.release(t)[-1] == ("say", "click_sleep") and c.state == "wake"
    d = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(3), profile=br.DARE, corner=(900.0, 700.0))
    d.pos = (300.0, 700.0)
    t = 0.0
    while d.state != "sleep_loop":
        t += 0.25
        d.tick(t, True)
    states = []
    for _ in range(40):
        t += 0.25
        d.tick(t, False)
        states.append(d.state)
    assert "sleep_up" in states and "rise" in states


@pytest.mark.parametrize("folder,ref,other", [
    ("아리아", "stand_0", "stretch_0"), ("아리아", "stand_0", "stretch_5"),
    ("레나", "stand_0", "magic_0"), ("레나", "stand_0", "magic_5"),
    ("Starline", "stand_0", "sneeze_0"), ("Starline", "stand_0", "sneeze_5"),
    ("Starline", "stand_0", "flame_0"), ("Starline", "stand_0", "flame_3"),   # 불꽃(QA 11-25 — 예전 1.07)
    ("다래", "sit_doze_0", "sleep_0"), ("다래", "sit_drowsy_0", "sleep_8"),
])
def test_basic_motion_same_pose_frames_match_neighbour_silhouette(folder, ref, other):
    """기본 동작 크기 튐 방지(QA 11-25 '기지개 전에 커지고, 엎드리기 전에 작아지고…'): 이웃 그림과 같은 자세인 장을
    발 밑 가운데 맞춰 겹쳤을 때 실루엣이 가장 잘 맞는 배율이 0.97~1.03(머리 폭·얼굴 창은 머리카락·귀에 끌려 못 씀)."""
    from scripts.silhouette import best_scale

    assert 0.97 <= best_scale(_img_of(ASSETS / folder / f"{ref}.png"), _img_of(ASSETS / folder / f"{other}.png")) <= 1.03


def test_starline_sneeze_bubble_keeps_sneeze_frames_to_the_end(app):
    """QA 11-25: 재채기 4번 말풍선이 말하기로 바꿔 4·5번이 안 나오고 크기가 튀었음 → 말풍선은 그림 위에만,
    재채기 0~5번 그대로 뒤 서기(talk_* 없음), 말풍선 1번, 말풍선이 떠 있는 동안 state == 'sneeze'."""
    from mabinogi_addon.ui import pet_window

    clock = {"t": 1.0}
    b = _starline(br.STARLINE)
    b._next_walk = 1e9
    w = pet_window.PetWindow(b, pet_window.load_frames("Starline", br.STARLINE), "#3A0729",
                             clock=lambda: clock["t"], outline="#D8AA5E")
    picker = ln.Picker(ln.read(SL_DIR / "lines.json"), random.Random(1))
    said = []
    w.events.connect(lambda events: [said.append(e[1]) or w.say(picker.pick(e[1])) for e in events if e[0] == "say"])
    try:
        w.step()
        b._next_rare, b._next_walk, b._next_idle, b._next_extra = clock["t"] + 0.01, 1e9, 1e9, 1e9
        frames = []
        for _ in range(int(6.5 * 30)):
            clock["t"] += 1 / 30
            w.step()
            name = b.frame(clock["t"])
            if not frames or frames[-1] != name:
                frames.append(name)
            if w.bubble() and b.state != "stand":
                assert b.state == "sneeze"
        assert said == ["sneeze"]
        start = frames.index("sneeze_0")
        assert frames[start:start + 7] == [f"sneeze_{i}" for i in range(6)] + ["stand_0"]
        assert not [f for f in frames if f.startswith("talk_")]
    finally:
        w.close()


def test_starline_sneeze_is_on_with_new_sheet():
    """0.56.2엔 꺼 뒀던 재채기를 새 시트(Starline_재채기_v2 — 서 있기와 같은 비율)로 다시 켬(기획 11-25)."""
    assert br.STARLINE.rare_extra == "sneeze" and br.STARLINE.rare_say == (4, "sneeze")


def test_starline_sneeze_v2_matches_stand_eyes_and_cloth_tone():
    """새 재채기 시트(기획 11-25): 끝(서기로 돌아가는) 프레임 눈 간격이 서 있기 ±3%, 0~5번 옷·망토 중간 톤 Lab ±1.5."""
    import cv2
    import numpy as np

    from mabinogi_addon.image_io import imread
    from scripts.build_starline_frames import eye_gap

    read = lambda n: imread(ASSETS / "Starline" / f"{n}.png", cv2.IMREAD_UNCHANGED)  # noqa: E731

    def mid(f):
        lab = cv2.cvtColor(np.ascontiguousarray(f[..., :3]), cv2.COLOR_BGR2LAB).astype(np.float64)
        sel = (f[..., 3] > 200) & (lab[..., 0] >= 80) & (lab[..., 0] <= 170)
        m = lab[sel].mean(0)
        return np.array([m[0] / 2.55, m[1] - 128, m[2] - 128])

    stand = read("stand_0")
    assert abs(eye_gap(read("sneeze_5")) / eye_gap(stand) - 1) <= 0.03
    for i in range(6):
        assert (np.abs(mid(read(f"sneeze_{i}")) - mid(stand)) <= 1.5).all(), i


# ---- 착장(옷) 8벌 + 카드 서랍(기획 11-25, docs/character-pet-spec.md 3-2절) ----------------------------
def test_outfit_unlock_levels_and_drawer_order():
    from mabinogi_addon.character import outfits

    lab, red = outfits.find("레나", "lab"), outfits.find("레나", "red_dress")
    assert (outfits.unlocked(lab, 49), outfits.unlocked(lab, 50)) == (False, True)
    assert (outfits.unlocked(red, 99), outfits.unlocked(red, 100)) == (False, True)
    names = lambda items: [o.key for o in items]  # noqa: E731
    assert names(outfits.drawer("레나", "")) == ["lab", "red_dress"]          # 기본 입음 → 50·100
    assert names(outfits.drawer("레나", "lab")) == ["", "red_dress"]          # 50 입음 → 기본·100(돌아갈 길)
    assert names(outfits.drawer("레나", "red_dress")) == ["", "lab"]
    assert names(outfits.drawer("레나", "모름")) == ["lab", "red_dress"]       # 모르는 값 = 기본
    assert outfits.drawer("Starline", "") == [] and outfits.of("Starline") == ()
    assert sorted(outfits.OUTFITS) == sorted(["다래", "아리아", "레나", "이안"])
    for folder, items in outfits.OUTFITS.items():
        assert [o.level for o in items] == [0, 50, 100]
        for o in items[1:]:   # 착장 카드 8장(상반신을 얼굴로 맞춰 card.png 틀로)
            card = ASSETS / outfits.asset(folder, o.key, "card.png")
            assert card.is_file(), card
            assert (SRC_ASSETS / folder / "의상" / o.name / "상반신.png").is_file()


SRC_ASSETS = Path(__file__).resolve().parents[1] / "docs" / "characters" / "assets"


def _drawer_tab(cfg_path, affinity=None, outfit=None, pack="조용한 여성"):
    import json

    cfg_path.write_text(json.dumps({"voice": {"pack": pack},
                                    "character": {"affinity": affinity or {}, "outfit": outfit or {}}}), encoding="utf-8")
    from mabinogi_addon.ui import character_tab as ct
    tab = ct.CharacterTab()
    tab.resize(760, 680)
    tab.show()
    return tab, {c.character.name: c for c in tab.cards}


def test_drawer_open_click_wears_and_locked_only_notices(app, cfg):
    """열린 옷 누름 → 그 캐릭터 옷 저장·카드 그림·서랍 다시(지금 옷 뺀 두 벌)·신호, 잠긴 옷 → 저장 안 함·안내.
    다른 캐릭터 옷을 바꿔도 고른 캐릭터(알림 목소리)는 그대로."""
    tab, cards = _drawer_tab(cfg, affinity={"화난 여성": {"value": 60, "cleared": 2}})
    changed = []
    tab.outfit_changed.connect(changed.append)
    lena = cards["레나"]
    assert lena.affinity() == 60
    tab.open_drawer(lena)
    assert tab.drawer.isVisible() and [c.outfit.key for c in tab.drawer.cells] == ["lab", "red_dress"]
    assert [c.unlocked for c in tab.drawer.cells] == [True, False]
    assert [c.caption() for c in tab.drawer.cells] == ["♥ 50 · 입을 수 있음", "♥ 100"]
    locked = tab.drawer.cells[1]
    locked.picked.emit(locked.outfit)
    assert config.load_outfit("화난 여성") == "" and changed == [] and tab.drawer.notice == "호감도 100에서 열려요"
    old_art = lena._art.cacheKey()
    tab.drawer.cells[0].picked.emit(tab.drawer.cells[0].outfit)
    assert config.load_outfit("화난 여성") == "lab" and changed == ["화난 여성"]
    assert lena.outfit == "lab" and lena._art.cacheKey() != old_art
    assert [c.outfit.key for c in tab.drawer.cells] == ["", "red_dress"]
    assert tab.drawer.cells[0].caption() == "기본"
    assert config.load_voice_pack() == "조용한 여성"            # 고른 캐릭터 그대로
    assert not lena.selected() and not lena.pending()
    tab.drawer.cells[0].picked.emit(tab.drawer.cells[0].outfit)  # 기본으로 돌아감
    assert config.load_outfit("화난 여성") == "" and lena.outfit == ""
    tab.refresh()                                               # 저장 값으로 다시 맞춰도 같음
    assert lena.outfit == ""


def test_drawer_direction_starline_none_and_closes_outside(app, cfg):
    from PySide6.QtCore import QPoint

    tab, cards = _drawer_tab(cfg)
    tab.open_drawer(cards["Starline"])
    assert not tab.drawer.isVisible()                       # 착장 없음 → 서랍 없음
    tab.open_drawer(cards["???"])
    assert not tab.drawer.isVisible()
    tab.open_drawer(cards["레나"])                            # 가운데 줄 → 오른쪽
    lena = cards["레나"].geometry()
    assert not tab.drawer.opens_left
    tab.drawer.open_for(cards["레나"], animate=False)
    assert tab.drawer.geometry().left() > lena.right() and tab.drawer.geometry().right() <= tab.width()
    tab.drawer.open_for(cards["다래"], animate=False)        # 맨 오른쪽 줄 → 왼쪽
    assert tab.drawer.opens_left and tab.drawer.geometry().right() < cards["다래"].geometry().left()
    assert tab.drawer.cells and all(not c.unlocked for c in tab.drawer.cells)   # 베타 호감도 0 — 잠긴 채로 보임
    inside = tab.drawer.geometry().center()
    tab._maybe_close_drawer(inside)
    assert tab.drawer.isVisible()
    tab._maybe_close_drawer(cards["다래"].geometry().center())
    assert tab.drawer.isVisible()
    tab._maybe_close_drawer(QPoint(2, 2))
    assert not tab.drawer.isVisible()


def test_saved_outfit_shows_on_card_and_pet_frames_fall_back(app, cfg, tmp_path, monkeypatch):
    from mabinogi_addon.ui import pet_window

    _tab, cards = _drawer_tab(cfg, outfit={"부드러운 여성": "tshirt", "화난 여성": "없는옷"})
    assert cards["아리아"].outfit == "tshirt" and cards["레나"].outfit == ""
    # 착장 SD가 아직 없음 → 기본 프레임 그대로
    base = pet_window.load_frames("아리아", br.ARIA)
    dressed = pet_window.load_frames("아리아", br.ARIA, "tshirt")
    assert set(base) == set(dressed) and all(base[n] == dressed[n] for n in base)
    # 착장 폴더에 같은 이름 프레임이 생기면 그걸 먼저
    root = tmp_path / "res"
    (root / "characters" / "아리아" / "outfits" / "tshirt").mkdir(parents=True)
    from PySide6.QtGui import QImage
    for name, size in (("stand_0", 10), ("walk_0", 10)):
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(0xFF00FF00)
        img.save(str(root / "characters" / "아리아" / f"{name}.png"))
    big = QImage(20, 20, QImage.Format.Format_ARGB32)
    big.fill(0xFFFF0000)
    big.save(str(root / "characters" / "아리아" / "outfits" / "tshirt" / "stand_0.png"))
    monkeypatch.setattr(pet_window.paths, "resource_dir", lambda: root)
    frames = pet_window.load_frames("아리아", br.ARIA, "tshirt")
    assert frames["stand_0"].width() == 20 and frames["walk_0"].width() == 10


def test_config_outfit_saves_per_character(cfg):
    assert config.load_outfit("화난 여성") == ""
    config.save_character(outfit=("화난 여성", "lab"))
    config.save_character(outfit=("조용한 여성", "frill_pajama"))
    assert config.load_outfit("화난 여성") == "lab" and config.load_outfit("조용한 여성") == "frill_pajama"



# ---- 11-25 카드 테두리·상태 표시·서랍 열기 지연(기획 — docs/characters/카드_테두리.md) ----
def test_card_frames_built_for_known_characters_only(app, cfg):
    import json

    from mabinogi_addon.ui import character_tab as ct

    for c in roster.ROSTER:
        frame = ct.card_frame(c)
        if not c.known:
            assert frame is None                       # ??? 테두리 없음
            continue
        pixmap, rect = frame
        meta = json.loads((ASSETS / roster.folder(c) / "frame.json").read_text(encoding="utf-8"))
        assert rect.x() == meta["x"] <= 0 and rect.y() <= 0   # 선 밖 장식은 카드 밖으로 넘침
        assert rect.right() >= ct.CARD_W and rect.bottom() >= ct.CARD_H
        assert abs(pixmap.width() / 2 - rect.width()) <= 1   # 2배 해상도
    assert ct.NAME_LIFT == {"Starline": 12, "이안": 6, "다래": 4, "아리아": 2, "레나": 0}


def test_card_states_dim_plate_and_pending_float(app, cfg):
    tab, cards = _drawer_tab(cfg)                     # 다래 사용 중
    dare, lena, ian = cards["다래"], cards["레나"], cards["이안"]
    assert dare.selected() and dare.bright()           # 사용 중은 늘 밝게(명판)
    assert not lena.bright() and not ian.bright()      # 나머지 25% 어둡게
    assert cards["다래"].card_rect().top() == ct_pad() + 1.5
    tab._play_sample = lambda pack: None
    tab.preview(lena.character)                       # 눌러 인사 → 적용 대기
    assert lena.pending() and lena.bright() and lena.apply_button.isVisible()
    assert lena.card_rect().top() == ct_pad() + 1.5 - 6       # 6px 떠오름
    button = lena.apply_button.geometry()
    assert button.bottom() < lena.card_rect().bottom() - 30   # 이름 바로 위(이름 자리 위)
    ian._hover = True
    assert ian.bright()                                # 마우스 올리면 원래 밝기
    tab._leave_card(ian)
    ian._hover = False
    assert not ian.bright()
    # 그리기 — 층이 카드마다 테두리·이름·명판을 그림(예외 없이)
    image = tab.grab()
    assert not image.isNull()


def ct_pad():
    from mabinogi_addon.ui import character_tab as ct
    return ct.PAD_TOP


def test_drawer_opens_after_300ms_hover_and_follows_floating_card(app, cfg):
    tab, cards = _drawer_tab(cfg, affinity={"화난 여성": {"value": 60, "cleared": 2}})
    lena = cards["레나"]
    tab._hover_card(lena)
    assert not tab.drawer.isVisible() and tab._hover_timer.isActive()
    assert tab._hover_timer.interval() == 300
    tab._leave_card(lena)                              # 지나가는 마우스 → 안 열림
    assert not tab._hover_timer.isActive()
    tab._hover_card(lena)
    tab._hover_timer.timeout.emit()                    # 0.3초 머묾
    assert tab.drawer.isVisible() and tab.drawer.card is lena and lena.bright()   # 서랍 열린 카드는 밝게
    tab._play_sample = lambda pack: None
    tab.resize(800, 680)                               # 창 폭 여유(좁으면 서랍이 탭 안으로 당겨짐)
    tab.preview(lena.character)                        # 적용 대기 → 떠오른 카드에 맞춰 서랍도
    from PySide6.QtCore import QPoint, QPointF
    rect = lena.card_rect().translated(QPointF(lena.mapTo(tab, QPoint(0, 0)))).toAlignedRect()
    assert tab.drawer.geometry().top() == rect.top()
    assert tab.drawer.geometry().left() - rect.right() == 16    # 테두리 장식만큼 간격
    tab.drawer.cells[0].picked.emit(tab.drawer.cells[0].outfit)   # 서랍에서 옷 → 대기 유지
    assert lena.pending()
    tab.drawer.close_drawer()                          # 서랍만 닫힘
    assert lena.pending() and not lena.keep_bright


# ---- 11-25 Starline 말하기: 발 그대로·색 서 있기와 같게(QA 반려) ----
def _sl(name):
    import cv2

    from mabinogi_addon.image_io import imread
    return imread(SL_DIR / f"{name}.png", cv2.IMREAD_UNCHANGED)


def test_starline_talk_loop_feet_match_base():
    """말하기 반복 장(강조·깜빡임)의 발 띠(아래 12%, 가운데 맞춤)가 talk_base와 같음 — 예전 emph 19.4·emph2 34.3."""
    import numpy as np

    def band(f):
        return f[int(f.shape[0] * 0.88):].astype(np.float32)

    base = band(_sl("talk_base_0"))
    for name in ("talk_m1_0", "talk_m2_0", "talk_emph_0", "talk_emph2_0", "talk_blink_0"):
        other = band(_sl(name))
        h, w = min(base.shape[0], other.shape[0]), max(base.shape[1], other.shape[1])

        def centered(x):
            out = np.zeros((h, w, 4), np.float32)
            off = (w - x.shape[1]) // 2
            out[:, off:off + x.shape[1]] = x[-h:]
            return out
        assert float(np.abs(centered(base) - centered(other)).mean()) <= 6.0, name


def test_starline_talk_tones_match_stand():
    """모든 talk_* 장: 중간 톤(L 80~170)·어두운 톤(L < 80) Lab 평균이 stand_0 ±1.5, 채도(HSV S 평균) ±3 —
    예전 시작 시트 채도 64.8·어두운 L 21.9, 반복 시트 73.4·25.3(QA 11-25)."""
    import cv2
    import numpy as np

    def tones(f):
        a = f[..., 3] > 200
        lab = cv2.cvtColor(np.ascontiguousarray(f[..., :3]), cv2.COLOR_BGR2LAB).astype(np.float64)
        hsv = cv2.cvtColor(np.ascontiguousarray(f[..., :3]), cv2.COLOR_BGR2HSV).astype(np.float64)
        out = []
        for sel in (a & (lab[..., 0] >= 80) & (lab[..., 0] <= 170), a & (lab[..., 0] < 80)):
            m = lab[sel].mean(0)
            out.append(np.array([m[0] / 2.55, m[1] - 128, m[2] - 128]))
        return out, hsv[a][:, 1].mean()

    (mid0, dark0), sat0 = tones(_sl("stand_0"))
    names = sorted(p.stem for p in [*SL_DIR.glob("talk_*.png"), *SL_DIR.glob("flame_*.png")])   # 불꽃 새 시트도(11-25)
    assert len(names) >= 13
    for name in names:
        (mid, dark), sat = tones(_sl(name))
        assert (np.abs(mid - mid0) <= 1.5).all() and (np.abs(dark - dark0) <= 1.5).all(), (name, mid, dark)
        assert abs(sat - sat0) <= 3, (name, sat, sat0)


def test_ian_sit_face_matches_crouch_and_rise():
    """이안 구석: 쪼그림 → 앉아 있기 → 일어나기에서 얼굴 크기가 서 있기와 같음(±2%) — 예전 sit 1.07~1.085(사용자 11-25)."""
    import cv2

    from mabinogi_addon.image_io import imread
    from scripts.build_ian_frames import face_ratio

    read = lambda n: imread(IAN_DIR / f"{n}.png", cv2.IMREAD_UNCHANGED)  # noqa: E731
    stand = read("stand_1")
    for name in ("crouch_2", "sit_0", "sit_1", "sit_2", "sit_3", "rise_0"):
        assert abs(face_ratio(stand, read(name)) - 1) <= 0.02 + 1e-9, name
    assert len({read(f"sit_{i}").shape[0] for i in range(4)}) == 1   # 한 배율(꿈틀거림 없음)
