"""잡담 로그인 권유(잡담 명세 17.8, 0.52.0 사용자 결정 11-16) — 비로그인에게만, 설정 동기화 안내.

로그인이 풀린 사람(예전 discordUser만 있음)도 같은 문장(사용자 결정 11-16 — '풀렸어요' 문장은 말풍선 두 줄을 넘어 빼고 공통으로).
"""
import random
import time

import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, feature_access, paths
from mabinogi_addon.creator_dialogue import LOGIN_TEXT, Tip, TipPicker, login_due, read_tips

DAY = 86400
NOW = 1_800_000_000.0


def _login_tip():
    return Tip("tip-login", "login", ((LOGIN_TEXT,),), "로그인하러 가기")


# ---- 추첨·주기(순수) ----

def test_login_after_invite_before_tips_and_never_as_plain_tip():
    tips = (Tip("tip-buff", "buff", (("버프",),), "보러 가기"), _login_tip())
    picker = TipPicker(tips, rng=random.Random(3))
    kinds = {(picker.pick({"buff"}, invite_ok=True, login_ok=True) or ("normal",))[0] for _ in range(300)}
    assert kinds == {"normal", "invite"}  # 디스코드 권유가 먼저
    got = {picker.pick({"buff"}, invite_ok=False, login_ok=True) for _ in range(300)}
    assert got == {None, ("login", tips[1])}  # 그다음 로그인 권유
    plain = {(picker.pick({"buff", "login"}, invite_ok=False, login_ok=False) or ("normal", None))[1] for _ in range(300)}
    assert tips[1] not in plain  # 로그인 항목은 기능 추천 차례에 섞이지 않음


@pytest.mark.parametrize("state,days,due", [
    ({}, 0, True),
    ({"declinedAt": 0}, 44.9, False), ({"declinedAt": 0}, 45.1, True),   # 괜찮아요 45일
    ({"shownAt": 0}, 29.9, False), ({"shownAt": 0}, 30.1, True),         # 그 밖엔 30일에 한 번
])
def test_login_schedule(state, days, due):
    assert login_due(state, days * DAY) is due


def test_login_text_in_dialogue_file_fits_rules():
    tips = [t for t in read_tips(paths.resource_dir() / "dialogues.json") if t.feature == "login"]
    assert len(tips) == 1 and tips[0].button == "로그인하러 가기"
    assert "".join(c[0] for c in tips[0].parts) == LOGIN_TEXT


def test_login_record_is_synced():
    from mabinogi_addon import cloud_sync
    config.save_login_invite(shownAt=NOW)
    assert cloud_sync.strip_for_sync(config._read_local_config())["loginInvite"] == {"shownAt": NOW}
    assert "loginInvite" not in config._LOCAL_ONLY_KEYS


# ---- 창 ----

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
    d = w.creator_dialogue
    d.visibility = lambda *args: True
    d.wall = lambda: NOW
    d.picker.rng = d.session.rng = random.Random(5)
    yield w, app
    w._force_quit = True
    w.close()


def _kinds(d, n=300):
    return {(d._pick_extra() or ("normal",))[0] for _ in range(n)}


@pytest.mark.dialogue_tips
def test_logged_in_never_sees_login(window, monkeypatch):
    w, _ = window
    d = w.creator_dialogue
    config.save_discord_invite(joined=True)  # 디스코드 권유는 끝남
    monkeypatch.setattr(feature_access, "is_logged_in", lambda: True)
    assert "login" not in _kinds(d)
    monkeypatch.setattr(feature_access, "is_logged_in", lambda: False)
    assert "login" in _kinds(d)


@pytest.mark.dialogue_tips
def test_old_discord_user_gets_same_sentence(window, monkeypatch):
    """예전 discordUser만 있는(로그인이 풀린) 사람도 일반 비로그인과 같은 문장."""
    w, _ = window
    d = w.creator_dialogue
    raw = config._read_local_config()
    raw["discordUser"] = {"id": "1", "name": "옛 로그인"}
    config._write_local_config(raw)
    monkeypatch.setattr(feature_access, "is_logged_in", lambda: False)
    tip = next((t for t in d.feed.tips if t.feature == "login"), None)
    monkeypatch.setattr(d, "_pick_extra", lambda: ("login", tip))
    assert d.request()
    assert d.bubble.text.text() == LOGIN_TEXT
    assert [b.text() for b in d.bubble.buttons] == ["로그인하러 가기", "괜찮아요"]
    assert config.load_login_invite()["shownAt"] == NOW


@pytest.mark.dialogue_tips
def test_not_same_day_as_invite_or_tip(window, monkeypatch):
    w, _ = window
    d = w.creator_dialogue
    monkeypatch.setattr(feature_access, "is_logged_in", lambda: False)
    config.save_discord_invite(shownAt=NOW - 3600)  # 오늘 디스코드 권유를 보임
    assert _kinds(d) == {"normal"}
    config.save_discord_invite(joined=True)
    config.save_dialogue_tip_day(time.strftime("%Y-%m-%d", time.localtime(NOW)))  # 오늘 기능 추천을 보임
    assert "login" not in _kinds(d)
    config.save_dialogue_tip_day("2000-01-01")
    config.save_login_invite(shownAt=NOW - 3600)  # 오늘 로그인 권유를 보임 → 디스코드 권유·기능 추천도 오늘은 없음
    config.save_discord_invite(joined=False, shownAt=0)
    assert _kinds(d) == {"normal"}


@pytest.mark.dialogue_tips
@pytest.mark.parametrize("answer", ["로그인하러 가기", "괜찮아요"])
def test_login_buttons(window, monkeypatch, answer):
    w, app = window
    d = w.creator_dialogue
    monkeypatch.setattr(feature_access, "is_logged_in", lambda: False)
    monkeypatch.setattr(d, "_pick_extra", lambda: ("login", None))
    assert d.request()
    next(b for b in d.bubble.buttons if b.text() == answer).click()
    app.processEvents()
    state = config.load_login_invite()
    if answer == "로그인하러 가기":  # 설정 › 계정, 로그인 버튼이 보이게
        assert w._tabs.currentWidget() is w._settings_scroll
        button = w.settings_tab._login_btn
        top = button.mapTo(w._settings_scroll.widget(), button.rect().topLeft()).y()
        scroll = w._settings_scroll.verticalScrollBar().value()
        assert scroll <= top <= scroll + w._settings_scroll.viewport().height() - button.height()
        assert "declinedAt" not in state
    else:
        assert not login_due(state, NOW + 44 * DAY) and login_due(state, NOW + 46 * DAY)
