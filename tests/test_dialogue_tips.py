"""잡담 기능 추천·디스코드 권유(잡담 명세 17절, 0.47.0) — 17.6 테스트."""
import json
import random
import time

import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, paths
from mabinogi_addon.creator_dialogue import (FAILING_FEATURES, INVITE_URL, TIP_FEATURES, TipPicker, Tip, invite_due, parse,
                                             parse_tips, read, read_tips)

DAY = 86400


def _tips(*features):
    return tuple(Tip(f"tip-{f}", f, (("문장 " + f,),), "보러 가기") for f in features)


# ---- 추첨(순수) ----

def test_about_a_quarter_and_never_same_feature_twice_in_a_row():
    picker = TipPicker(_tips("buff", "custom", "memo"), rng=random.Random(7))
    picks, previous, repeats = 0, None, 0
    for _ in range(1000):
        got = picker.pick({"buff", "custom", "memo"}, invite_ok=False)
        if got is None:
            continue
        picks += 1
        kind, tip = got
        assert kind == "tip"
        repeats += tip.feature == previous
        previous = tip.feature
        picker.shown(tip)
    assert 0.21 <= picks / 1000 <= 0.29 and repeats == 0


def test_nothing_unused_means_no_tip_and_single_unused_is_skipped_right_after():
    picker = TipPicker(_tips("buff", "custom"), rng=random.Random(1))
    assert all(picker.pick(set(), invite_ok=False) is None for _ in range(1000))  # 모두 쓰는 중 → 0회
    picker.rng = random.Random(2)
    shown = []
    for _ in range(400):
        got = picker.pick({"custom"}, invite_ok=False)
        if got:
            shown.append(got[1].feature)
            picker.shown(got[1])
    assert shown == ["custom"]  # 안 쓰는 게 하나뿐이면 직전 것만 빼므로 그다음부턴 일반 대사


def test_invite_first_and_not_same_day_as_tip():
    picker = TipPicker(_tips("buff"), rng=random.Random(3))
    results = {picker.pick({"buff"}, invite_ok=True) for _ in range(200)}
    assert results == {None, ("invite", None)}  # 25% 차례에 권유가 먼저
    results = {picker.pick({"buff"}, invite_ok=False, tip_ok=False) for _ in range(200)}
    assert results == {None}  # 오늘 권유를 보였으면 기능 추천 안 함


@pytest.mark.parametrize("state,days,due", [
    ({}, 0, True),
    ({"joined": True}, 999, False),                           # 참가하기 누른 적 있음 → 다시 안 나옴
    ({"declinedAt": 0}, 44.9, False), ({"declinedAt": 0}, 45.1, True),   # 괜찮아요 45일
    ({"shownAt": 0}, 29.9, False), ({"shownAt": 0}, 30.1, True),         # 그 밖엔 30일에 한 번
])
def test_invite_schedule(state, days, due):
    assert invite_due(state, days * DAY) is due


# ---- 대사 파일(옛 앱 호환·잘못된 tips) ----

BUILTIN = paths.resource_dir() / "dialogues.json"


def test_builtin_has_18_draft_tips_and_old_parse_ignores_them():
    raw = json.loads(BUILTIN.read_text(encoding="utf-8"))
    recommend = [t for t in raw["tips"] if "when" not in t and t["feature"] != "inquiry"]
    assert {t["feature"] for t in recommend} == set(TIP_FEATURES) and len(recommend) == 18
    # 0.48.0(17.7): 일반 문의 권유 1 + 콕 집어 묻기 8
    assert sum(t["feature"] == "inquiry" for t in raw["tips"]) == 1
    assert {t["feature"] for t in raw["tips"] if t.get("when") == "failing"} == set(FAILING_FEATURES)
    entries = read(BUILTIN)  # 지금 배포된 앱의 parse는 entries만 읽는다
    assert len(entries) == 12
    without = dict(raw)
    without.pop("tips")
    assert parse(json.dumps(without, ensure_ascii=False).encode()) == entries
    assert len(read_tips(BUILTIN)) == 27


@pytest.mark.parametrize("tips,expected", [
    ("엉망", ()),                                                       # 칸이 잘못됨 → 추천만 끔
    ([{"id": "a", "feature": "모르는기능", "parts": ["x"]}], ()),         # 모르는 feature 건너뜀
    ([{"id": "a", "feature": "buff", "parts": ["x" * 61]}], ()),        # 60자 넘음
    ([{"id": "a", "feature": "buff", "parts": ["x"], "button": "아홉글자버튼이다요"}], ()),  # 버튼 8자 넘음
    ([{"id": "a", "feature": "buff", "parts": ["좋아요"]}, 3], ("buff",)),  # 잘못된 항목만 건너뜀
])
def test_bad_tips_never_break_entries(tips, expected):
    raw = json.loads(BUILTIN.read_text(encoding="utf-8"))
    raw["tips"] = tips
    data = json.dumps(raw, ensure_ascii=False).encode()
    assert parse(data) == read(BUILTIN)  # 일반 대사 그대로
    assert tuple(t.feature for t in parse_tips(data)) == expected


def test_missing_tips_key_keeps_builtin_tips_in_feed(monkeypatch, tmp_path):
    """원격·캐시 파일에 tips 칸이 아직 없으면(지금 게시된 파일) 내장 추천을 그대로 쓴다. 잘못된 칸이면 추천만 끔."""
    QApplication.instance() or QApplication([])
    from mabinogi_addon.ui.dialogue_feed import DialogueFeed
    raw = json.loads(BUILTIN.read_text(encoding="utf-8"))
    raw.pop("tips")
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    (tmp_path / "creator-dialogues.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    feed = DialogueFeed()
    assert len(feed.tips) == 27 and len(feed.entries) == 12
    feed.shutdown()
    raw["tips"] = {"잘못": True}
    (tmp_path / "creator-dialogues.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    feed = DialogueFeed()
    assert feed.tips == () and len(feed.entries) == 12
    feed.shutdown()


# ---- 창(사용 여부·말풍선·버튼) ----

@pytest.fixture
def window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    from mabinogi_addon.ui.main_window import MainWindow
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    config.save_general_flag("skipSetup", True)
    w = MainWindow()
    w._hide_home()
    w.show()
    app.processEvents()
    w.creator_dialogue.visibility = lambda *args: True
    yield w, app
    w._force_quit = True
    w.close()


def test_all_draft_tips_fit_two_lines(window):
    w, _ = window
    d = w.creator_dialogue
    assert len(d.feed.tips) == 27  # 17.5 문장 18 + 17.7 문의 권유 9 전부 말풍선 두 줄 안(넘치면 건너뜀)
    assert all(d.bubble.measure(d._shortest(t.parts))[2] for t in d.feed.tips)
    too_long = Tip("x", "buff", (("가나다라마바사아자차카타파하 " * 4,),), "보러 가기")
    assert d._usable_tips((too_long,)) == ()


@pytest.mark.dialogue_tips
def test_turning_on_feature_or_opening_tool_removes_its_tip(window):
    w, app = window
    unused = w.unused_tip_features()
    assert {"dorcha", "memo", "calc", "sketch", "harp"} <= unused
    w.dorcha_tab.enable.setChecked(True)
    w._tabs.setCurrentWidget(w._tracker_tabs)
    w._tracker_tabs.setCurrentWidget(w._combat_pages["memo"])  # 메모 화면을 한 번 엶
    w._tabs.setCurrentWidget(w._convenience_tabs)               # 계산기 화면
    app.processEvents()
    unused = w.unused_tip_features()
    assert "dorcha" not in unused and "memo" not in unused and "calc" not in unused
    assert {"sketch", "harp"} <= unused
    assert config.load_opened_tools() == {"memo", "calc"}


def _force(d, monkeypatch, extra):
    monkeypatch.setattr(d, "_pick_extra", lambda: extra)


@pytest.mark.dialogue_tips
def test_tip_bubble_go_opens_feature(window, monkeypatch):
    w, app = window
    d = w.creator_dialogue
    tip = next(t for t in d.feed.tips if t.feature == "custom")
    _force(d, monkeypatch, ("tip", tip))
    assert d.request()
    assert [b.text() for b in d.bubble.buttons] == ["보러 가기"]  # 괜찮아요 없음
    assert config.load_dialogue_tip_day() == time.strftime("%Y-%m-%d")
    d._eligible()  # 1초마다 노출 확인해도 버튼 그대로
    assert [b.text() for b in d.bubble.buttons] == ["보러 가기"]
    d.bubble.buttons[0].click()
    app.processEvents()
    assert not d.bubble.isVisible()
    assert w._tabs.currentWidget() is w._tracker_tabs and w._tracker_tabs.currentWidget() is w._combat_pages["custom"]
    assert d.picker.last_feature == "custom"


@pytest.mark.dialogue_tips
@pytest.mark.parametrize("answer", ["참가하기", "괜찮아요"])
def test_invite_buttons(window, monkeypatch, answer):
    w, app = window
    d = w.creator_dialogue
    opened = []
    d.open_url = opened.append
    now = [1_800_000_000.0]
    d.wall = lambda: now[0]
    _force(d, monkeypatch, ("invite", None))
    assert d.request()
    assert [b.text() for b in d.bubble.buttons] == ["참가하기", "괜찮아요"]
    assert config.load_discord_invite()["shownAt"] == now[0]
    next(b for b in d.bubble.buttons if b.text() == answer).click()
    app.processEvents()
    state = config.load_discord_invite()
    if answer == "참가하기":
        assert opened == [INVITE_URL] and state["joined"] is True
        assert not invite_due(state, now[0] + 999 * DAY)  # 다시 안 나옴
    else:
        assert opened == [] and not invite_due(state, now[0] + 44 * DAY) and invite_due(state, now[0] + 46 * DAY)


@pytest.mark.dialogue_tips
def test_real_pick_respects_same_day_and_disabled_dialogue(window, monkeypatch):
    w, _ = window
    d = w.creator_dialogue
    d.picker.rng = d.session.rng = random.Random(5)
    d.wall = lambda: 1_800_000_000.0
    config.save_discord_invite(shownAt=1_800_000_000.0 - 3600)  # 오늘 권유를 보임
    kinds = {(d._pick_extra() or ("normal",))[0] for _ in range(300)}
    assert kinds == {"normal"}  # 권유는 30일 안 지났고, 같은 날 기능 추천과도 겹치지 않음
    config.save_discord_invite(shownAt=0)
    kinds = {(d._pick_extra() or ("normal",))[0] for _ in range(300)}
    assert kinds == {"normal", "invite"}  # 권유 차례가 먼저
    w.settings_tab.dialogue_enabled.setChecked(False)  # 잡담 끄면 말풍선 자체가 없음
    assert not d.request()


# ---- 17.7 문의 권유(0.48.0) ----

def test_failing_asks_first_inquiry_mixes_with_tips_and_bad_when_skipped():
    tips = _tips("buff") + (Tip("tip-inquiry", "inquiry", (("문의",),), "문의하기"),
                            Tip("ask-buff", "buff", (("버프가?",),), "문의하기", "failing"))
    picker = TipPicker(tips, rng=random.Random(4))
    got = {picker.pick({"buff"}, invite_ok=True, failing={"buff"}) for _ in range(300)} - {None}
    assert got == {("tip", tips[2])}  # 콕 집어 묻기가 권유·추천보다 먼저
    picker.rng = random.Random(9)
    seen = set()
    for _ in range(400):
        r = picker.pick(set(), invite_ok=False)
        if r:
            seen.add(r[1].feature)
    assert seen == {"inquiry"}  # 모든 기능을 써도 일반 문의 권유는 가끔
    raw = json.loads(BUILTIN.read_text(encoding="utf-8"))
    raw["tips"] = [{"id": "x", "feature": "memo", "when": "failing", "parts": ["a"]},
                   {"id": "y", "feature": "buff", "when": "someday", "parts": ["a"]},
                   {"id": "z", "feature": "buff", "when": "failing", "parts": ["버프?"]}]
    parsed = parse_tips(json.dumps(raw, ensure_ascii=False).encode())
    assert [(t.ident, t.button, t.when) for t in parsed] == [("z", "문의하기", "failing")]


@pytest.mark.dialogue_tips
def test_inquiry_button_opens_window_and_failing_opens_card_once_a_day(window, monkeypatch):
    w, app = window
    d = w.creator_dialogue
    opened = []
    monkeypatch.setattr(w, "open_inquiry_for", lambda feature: opened.append(feature))
    general = next(t for t in d.feed.tips if t.feature == "inquiry")
    _force(d, monkeypatch, ("tip", general))
    assert d.request() and [b.text() for b in d.bubble.buttons] == ["문의하기"]
    d.bubble.buttons[0].click()
    app.processEvents()
    assert opened == [None]  # 일반 권유 = 문의 창만
    ask = next(t for t in d.feed.tips if t.when == "failing" and t.feature == "buff")
    _force(d, monkeypatch, ("tip", ask))
    assert d.request() and d.bubble.text.text() == "버프가 잘 안 읽히나요? 문의하기로 알려 주시면 고쳐 볼게요"
    d.bubble.buttons[0].click()
    app.processEvents()
    assert opened == [None, "buff"]  # 콕 집어 묻기 = 그 기능 문제 신고 칸
    assert config.load_failing_asked() == {"buff": time.strftime("%Y-%m-%d")}
    monkeypatch.undo()  # 진짜 _pick_extra: 오늘 물은 기능은 빼고
    monkeypatch.setattr(w, "failing_tip_features", lambda: {"buff"})
    d.picker.rng = random.Random(1)
    kinds = {(d._pick_extra() or ("normal", None))[1] for _ in range(200)}
    assert all(k is None or k.when != "failing" for k in kinds)


def test_failing_needs_ten_minutes_and_opens_card(window, monkeypatch):
    w, _ = window
    from mabinogi_addon.ui import main_window as mw
    now = [1000.0]
    monkeypatch.setattr(mw.MainWindow, "_failing_now", lambda self: {"boss"})
    monkeypatch.setattr(w._watcher, "is_game_active", lambda: True, raising=False)
    import time as _t
    monkeypatch.setattr(_t, "monotonic", lambda: now[0])
    w._failing_sampled = 0.0
    w._sample_failing()
    now[0] += 599
    w._sample_failing()
    assert w.failing_tip_features() == set()
    now[0] += 2
    assert w.failing_tip_features() == {"boss"}
    w.open_inquiry_for("boss")
    try:
        assert w._inquiry.card.key == "boss" and w._inquiry.card_buttons["boss"].isChecked()
    finally:
        w._inquiry.shutdown()
        w._inquiry.close()
