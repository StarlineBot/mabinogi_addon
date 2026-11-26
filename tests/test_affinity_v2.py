"""호감도 2차 규칙(명세 3-2절, 11-26 게이지 배포) — 하루 10(게임 4 + 행동 6), 행동 25%·5분, 24·49 멈춤, 25 퀘스트 2일 연속,
줄어들기·캐릭터 바꾸기 바닥, 알파 저장 값 이전."""
import json
import random

import pytest

from mabinogi_addon.character import affinity as aff

DAY, NEXT, NEXT2 = "2026-11-24", "2026-11-25", "2026-11-26"


class Always:
    """확률을 늘 통과(행동 점수 = 쿨다운·상한만 보게)."""
    def random(self):
        return 0.0


def _a(value=0, cleared=0, rng=None, **kw):
    a = aff.Affinity(aff.Rules(**kw), value=value, cleared=cleared)
    a.rng = rng or Always()
    return a


def test_game_points_every_30_minutes_up_to_four_a_day():
    a = _a()
    got = [a.corner_minute(DAY) for _ in range(300)]
    assert sum(got) == 4 and [i + 1 for i, g in enumerate(got) if g] == [30, 60, 90, 120]
    assert a.game_points == 4 and a.value == 4


def test_action_points_cooldown_five_minutes_and_six_a_day():
    a = _a()
    assert a.action("click", 0, DAY) == 1
    assert a.action("pet", 299, DAY) == 0            # 5분 안엔 안 오름
    got = [a.action("speech", 300 * k, DAY) for k in range(1, 20)]
    assert sum(got) == 5 and a.action_points == 6    # 하루 최대 6
    assert a.value == 6


def test_daily_cap_ten_is_game_four_plus_action_six():
    a = _a()
    for k in range(30):
        a.action("alert", 300 * k, DAY)
    for _ in range(300):
        a.corner_minute(DAY)
    assert a.value == a.gained == 10
    assert a.action("alert", 99999, NEXT) == 1        # 자정 지나면 다시
    assert a.gained == 1 and a.value == 11


@pytest.fixture
def no_ceiling(monkeypatch):
    """확률 검사용 — 멈추는 값 없이."""
    monkeypatch.setattr(aff.Affinity, "ceiling", lambda self: 10 ** 9)


def test_action_chance_counts(no_ceiling):
    a = aff.Affinity(aff.Rules(action_cooldown=0, action_cap=10 ** 6, daily_cap=10 ** 6), rng=random.Random(7))
    got = sum(a.action("click", i, DAY) for i in range(4000))
    assert 900 <= got <= 1100


def test_stops_at_24_until_quest_and_49_after():
    a = _a(value=23)
    a.action("click", 0, DAY)
    a.action("click", 600, DAY)
    assert a.value == 24 and a.stage == 0 and a.quest_text().startswith("퀘스트: 2일 연속")
    for d in (DAY, NEXT):
        a.petted(1000, d)
        a.poked(2000, d)
        for _ in range(30):
            a.corner_minute(d)
    assert a.cleared == 1 and a.value == 25 and a.stage == 25   # 퀘스트를 깬 날 같이 게임 30분째 +1이 이어서
    assert a.quest_text() == "다음 이야기는 준비 중이에요"
    b = _a(value=48, cleared=1)
    for k in range(5):
        b.action("click", 300 * k, DAY)
    assert b.value == 49 and b.stage == 25            # 50 퀘스트 아직 없음 → 49에서 멈춤


def test_quest_25_needs_two_consecutive_days_of_all_three():
    a = _a()
    a.petted(0, DAY)
    a.poked(0, DAY)
    for _ in range(29):
        a.corner_minute(DAY)                          # 29분 — 같이 게임하기 아직
    assert a.quest_text() == "퀘스트: 2일 연속 — 쓰다듬기 1/2 · 찔러 보기 1/2 · 같이 게임하기 0/2"
    a.petted(0, NEXT2)                                # 하루 건너뜀 → 다시 1
    assert a.quest_run("pet") == 1
    a.petted(0, "2026-11-27")
    a.poked(0, NEXT2)
    a.poked(0, "2026-11-27")
    assert a.cleared == 0
    for d in (NEXT2, "2026-11-27"):
        for _ in range(30):
            a.corner_minute(d)
    assert a.cleared == 1 and all(a.quest[k]["done"] for k in aff.QUEST_KINDS)
    a.petted(0, "2026-11-29")                         # 깬 뒤엔 끊겨도 그대로
    assert a.quest_run("pet") == 2 and a.cleared == 1


def test_decay_after_three_days_floor_is_cleared_stage():
    a = _a(value=20)
    assert a.decay(3) == 0 and a.value == 20          # 3일 안 켬 → 그대로
    assert a.decay(6) == 3 and a.value == 17          # 4·5·6일째 −1씩
    assert a.decay(100) == 17 and a.value == 0
    b = _a(value=30, cleared=1)
    b.decay(100)
    assert b.value == 25                              # 25 퀘스트를 깼으면 25 아래로 안 내려감
    c = _a(value=10, cleared=1)                       # 바닥보다 이미 낮으면 그대로(올리지 않음)
    c.decay(100)
    assert c.value == 10


def test_leave_minus_three_once_a_day_floor_and_sulk_once():
    a = _a(value=30, cleared=1)
    assert a.leave(DAY) == 3 and a.value == 27
    assert a.leave(DAY) == 0 and a.value == 27        # 같은 날 또 떠나도 한 번만
    assert a.leave(NEXT) == 2 and a.value == 25       # 바닥 25
    assert a.take_sulk() is True and a.take_sulk() is False


def test_repeat_penalty_and_annoyed_pet_keep_floor():
    a = _a(value=26, cleared=1)
    for t in (0, 100, 200):
        for i in range(5):
            a.click(t + i)
    assert a.value == 25
    b = _a(value=10)
    assert [b.petted(t, DAY) for t in (0, 1, 2)] == ["gain"] * 3
    value = b.value
    assert b.petted(3, DAY) == "annoyed" and b.value == value - 1
    assert b.petted(10, DAY) == "none"


def test_old_alpha_save_migrates_value_and_quest():
    old = {"value": 30, "cleared": 1, "day": DAY, "gained": 7, "counts": {"pet": 3}, "totals": {"pets": 4}}
    a = aff.Affinity.load(old)
    assert (a.value, a.cleared, a.gained, a.stage) == (30, 1, 0, 25)
    b = aff.Affinity.load({"value": 27})              # 25 이상 → 25 퀘스트 깬 것으로
    assert b.cleared == 1 and b.stage == 25
    c = aff.Affinity.load({"value": 60, "cleared": 2})   # 제작자 값 그대로(끌어내리지 않음)
    assert c.value == 60 and c.stage == 50
    c.rng = Always()
    c.action("click", 0, DAY)
    assert c.value == 61                              # 50 넘게 깬 구간(cleared 2)은 74까지
    d = aff.Affinity.load({"value": 12})
    assert d.cleared == 0 and d.value == 12


def test_round_trip_and_rules_from_settings():
    rules = aff.Rules.from_dict({"game_cap": 2, "action_chance": 0.5, "daily_cap": True, "unknown": 1, "leave_penalty": -1})
    assert rules.game_cap == 2 and rules.action_chance == 0.5 and rules.daily_cap == 10 and rules.leave_penalty == 3
    a = _a()
    a.petted(0, DAY)
    a.corner_minute(DAY)
    a.leave(DAY)
    b = aff.Affinity.load(json.loads(json.dumps(a.to_dict())))
    assert b.to_dict() == a.to_dict()
    assert aff.Affinity.load({"value": 500}).value == 100


def test_creator_set_value_clears_quests():
    a = aff.Affinity()
    a.set_value(50)
    assert a.cleared == 2 and a.stage == 50
    a.set_value(24)
    assert a.cleared == 0 and a.stage == 0


# ---- 앱 연결(동행 탭·컨트롤러) -------------------------------------------------------------------
import datetime  # noqa: E402
import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    from mabinogi_addon import config
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "LOCAL_CONFIG_PATH", path)
    real_read, real_write = config._read_local_config, config._write_local_config
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: real_read(path))
    monkeypatch.setattr(config, "_write_local_config", lambda data, *a, **k: real_write(data, path))
    return config


class _Fake:
    def __init__(self):
        from mabinogi_addon.character import brain as br
        self.said = []
        self.brain = br.Brain(br.Floor(0, 1000, 700))

    def say(self, line, mood="normal"):
        self.said.append(line.text if line is not None and not isinstance(line, str) else line)


def test_start_decays_every_saved_character_after_long_absence(app, cfg):
    from mabinogi_addon.ui import character_controller as cc
    cfg.save_voice_pack("조용한 여성")
    cfg.save_character(lastSeen="2026-11-14", rules={"action_chance": 0})
    cfg.save_character(affinity=("조용한 여성", {"rules": 2, "value": 20}))
    cfg.save_character(affinity=("부드러운 여성", {"rules": 2, "value": 40, "cleared": 1}))
    ctrl = cc.CharacterController()
    ctrl.set_enabled(True)
    try:
        ctrl.start(datetime.datetime(2026, 11, 24, 12))   # 9일 안 켬 → 4일째부터 6일 −1씩
        assert cfg.load_affinity("조용한 여성")["value"] == 14 and ctrl.affinity.value == 14
        assert cfg.load_affinity("부드러운 여성")["value"] == 34
    finally:
        ctrl.shutdown()


def test_apply_other_character_costs_three_and_return_says_sulk_line(app, cfg):
    from mabinogi_addon.character import roster
    from mabinogi_addon.ui import character_controller as cc
    from mabinogi_addon.ui import character_tab as ct
    cfg.save_voice_pack("조용한 여성")
    cfg.save_character(affinity=("조용한 여성", {"rules": 2, "value": 20}))
    tab = ct.CharacterTab()
    ctrl = cc.CharacterController()
    ctrl.set_enabled(True)
    tab.voice_pack_changed.connect(ctrl.voice_changed)
    aria, dare = roster.by_pack("부드러운 여성"), roster.by_pack("조용한 여성")
    try:
        tab.preview(aria)                                 # 카드 눌러 인사 듣기 → 안 깎임, 안내만
        assert cfg.load_affinity("조용한 여성")["value"] == 20
        assert "다래가 서운해할 거예요(♥ −3)" in tab.pet_hint.text()
        tab.choose(aria)                                  # 적용 → 떠나는 다래 −3
        assert cfg.load_affinity("조용한 여성")["value"] == 17
        tab.choose(dare)
        tab.choose(aria)                                  # 같은 날 또 떠나도 한 번만
        assert cfg.load_affinity("조용한 여성")["value"] == 17
        ctrl.window = fake = _Fake()
        ctrl.sync_window = lambda: None                   # 가짜 창 그대로(펫 창을 다시 만들지 않게)
        tab.choose(dare)                                  # 다래로 돌아옴 → 서운함 한 줄(한 번)
        assert ctrl.character.key == "조용한 여성"
        assert fake.said[0] == "…돌아왔네. 조금… 쓸쓸했어."
        assert cfg.load_affinity("조용한 여성").get("sulky") is False
        tab.choose(aria)
        ctrl.voice_changed()
        fake.said.clear()
        cfg.save_voice_pack("조용한 여성")
        ctrl.voice_changed()                              # 같은 날 다시 떠났다 와도 서운함은 다시(떠날 때마다)
        assert fake.said[:1] == ["…돌아왔네. 조금… 쓸쓸했어."]
    finally:
        ctrl.window = None
        ctrl.shutdown()


def test_came_back_line_is_in_every_character():
    from mabinogi_addon import paths
    from mabinogi_addon.character import lines as ln
    assert "came_back" in ln.SITUATIONS
    for folder in ("다래", "아리아", "레나", "이안", "Starline"):
        data = ln.read(paths.resource_dir() / "characters" / folder / "lines.json")
        texts = [line.text for line in data.lines["came_back"]]
        assert len(texts) == 1 and len(texts[0]) <= 30, folder
