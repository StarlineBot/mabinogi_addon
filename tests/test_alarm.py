"""알람(docs/alarm-spec.md 5절, 0.48.0) — 가짜 시계·표시 갈래·소리·목록 오버레이·블랙박스 메시지 회귀."""
import datetime as dt
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QFont, QFontMetricsF
from PySide6.QtWidgets import QApplication

from mabinogi_addon import alarm as m
from mabinogi_addon import config

THU = dt.date(2026, 11, 12)  # 목요일


def at(day, hh, mm, ss=0):
    return time.mktime(dt.datetime(day.year, day.month, day.day, hh, mm, ss).timetuple())


def run(clock, start, end, step=0.25):
    """start~end를 0.25초 주기로 돌려 울린 것 [(kind, 시각)]."""
    clock.start(start)
    out = []
    t = start
    while t < end:
        t = min(end, t + step)
        fires, _ = clock.check(t)
        out += [(f.kind, f.at) for f in fires]
    return out


def test_once_fires_then_turns_off_and_keeps_item():
    a = m.new_time_alarm(21, 0, name="레이드")
    c = m.AlarmClock([a])
    assert run(c, at(THU, 20, 59, 50), at(THU, 21, 0, 10)) == [("time", at(THU, 21, 0))]
    assert a.enabled is False and c.alarms == [a]  # 울린 뒤 꺼짐(지우지 않음)
    assert run(c, at(THU + dt.timedelta(days=1), 20, 59, 50), at(THU + dt.timedelta(days=1), 21, 0, 10)) == []


def test_daily_and_weekdays():
    daily = m.new_time_alarm(6, 0, repeat="daily")
    thu_only = m.new_time_alarm(20, 30, repeat="days", days=[3])
    c = m.AlarmClock([daily, thu_only])
    got = []
    for d in range(3):
        day = THU + dt.timedelta(days=d)
        got += run(c, at(day, 5, 59, 59), at(day, 6, 0, 1))
        got += run(c, at(day, 20, 29, 59), at(day, 20, 30, 1))
    assert got == [("time", at(THU, 6, 0)), ("time", at(THU, 20, 30)),
                   ("time", at(THU + dt.timedelta(days=1), 6, 0)), ("time", at(THU + dt.timedelta(days=2), 6, 0))]


@pytest.mark.parametrize("pre", [5, 10])
def test_pre_alert(pre):
    a = m.new_time_alarm(20, 30, name="길드전", pre=pre)
    c = m.AlarmClock([a])
    c.start(at(THU, 20, 0))
    fires = []
    t = at(THU, 20, 0)
    while t < at(THU, 20, 31):
        t += 0.25
        fires += c.check(t)[0]
    assert [(f.kind, f.at) for f in fires] == [("pre", at(THU, 20, 30) - pre * 60), ("time", at(THU, 20, 30))]
    assert m.notice_text(fires[0]) == f"{pre}분 뒤 · 길드전  20:30"
    assert m.notice_text(fires[1]) == "20:30  길드전"


def test_timer_fires_once_and_leaves_list():
    start = at(THU, 20, 0)
    timer = m.new_timer(30, start, name="요리")
    c = m.AlarmClock([timer])
    assert run(c, start, start + 30 * 60 + 2) == [("timer", start + 1800)]
    assert c.alarms == []
    assert m.notice_text(m.Fire("timer", timer, 0, 0)) == "30분 타이머 끝 · 요리"


def test_crosses_midnight():
    a = m.new_time_alarm(0, 5, repeat="daily")
    c = m.AlarmClock([a])
    assert run(c, at(THU, 23, 59, 50), at(THU + dt.timedelta(days=1), 0, 5, 5), step=1) == \
        [("time", at(THU + dt.timedelta(days=1), 0, 5))]


def test_sleep_jump_only_rings_last_minute():
    early, recent = m.new_time_alarm(20, 30, name="지남"), m.new_time_alarm(21, 0, name="방금")
    c = m.AlarmClock([early, recent])
    c.start(at(THU, 20, 0))
    fires, _ = c.check(at(THU, 21, 0, 30))  # 절전에서 1시간 뒤 복귀
    assert [f.alarm.name for f in fires] == ["방금"]


def test_restart_does_not_ring_missed_and_drops_finished_timers():
    a = m.new_time_alarm(21, 0)
    timer = m.new_timer(10, at(THU, 20, 0))
    c = m.AlarmClock([a, timer])
    c.start(at(THU, 21, 30))  # 앱이 꺼져 있던 동안 지남
    assert c.check(at(THU, 21, 30, 1))[0] == [] and c.alarms == [a] and a.enabled


def test_status_and_list_lines():
    now = at(THU, 20, 17, 26)
    c = m.AlarmClock([m.new_time_alarm(20, 30, name="길드전", repeat="days", days=[3]),
                      m.new_timer(13, now - 26, name="요리"), m.new_time_alarm(21, 0, name="레이드"),
                      m.new_time_alarm(20, 18, name="곧")])
    c.start(now)
    assert m.status_text(c, now) == "다음 알람 20:18 곧 · 타이머 12:34 남음"
    lines = [m.list_line(t, a, now) for t, a in c.upcoming(now, 3)]
    assert lines == [("34초 뒤", "곧", "soon"), ("20:30", "길드전", "time"), ("12분 뒤", "요리", "timer")]


def test_dict_round_trip_and_defaults():
    a = m.new_time_alarm(7, 5, repeat="days", days=[0, 4], pre=10)
    b = m.Alarm.from_dict(a.to_dict())
    assert (b.hour, b.minute, b.repeat, b.days, b.pre, b.label) == (7, 5, "days", [0, 4], 10, "알람")
    assert m.new_timer(5, 0).label == "타이머"
    assert m.Alarm.from_dict({"kind": "time", "hour": 25, "minute": 0}) is None
    assert m.Alarm.from_dict({"kind": "bogus"}) is None


# ---- 탭: 표시 갈래·소리·저장 ----

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


class Watcher:
    def __init__(self, game=True, own=False):
        self.game, self.own = game, own

    def is_game_active(self):
        return self.game

    def is_self_active(self):
        return self.own


def make_tab(clock, *, hwnd=0, watcher=None):
    from mabinogi_addon.ui.alarm_tab import AlarmTab
    events = []
    tab = AlarmTab(watcher, now=lambda: clock[0], game_hwnd=lambda: hwnd,
                   toast=lambda title, body: events.append(("toast", title, body)),
                   sound=lambda kind: events.append(("sound", kind)))
    return tab, events


def test_no_game_rings_toast_and_sound_and_saves(app):
    clock = [at(THU, 20, 0)]
    tab, events = make_tab(clock)
    tab.minutes.setValue(10)
    tab.timer_name.setText("요리")
    tab.start_btn.click()
    assert [a.label for a in m.AlarmClock([m.Alarm.from_dict(d) for d in config.load_alarms()["items"]]).alarms] == ["요리"]
    clock[0] += 600.1
    tab.tick()
    assert events == [("sound", "timer"), ("toast", "타이머", "10분 타이머 끝 · 요리")]
    assert config.load_alarms()["items"] == [] and tab.clock.alarms == []
    tab.shutdown()


def test_game_present_rings_game_notice_5s_below_blackbox(app, monkeypatch):
    from mabinogi_addon.ui import game_notice
    from mabinogi_addon.ui.blackbox_toast import BlackboxToast
    screen = QRect(0, 0, 1920, 1080)
    monkeypatch.setattr(game_notice, "screen_rect_for_hwnd", lambda hwnd: screen)
    clock = [at(THU, 20, 59, 59)]
    tab, events = make_tab(clock, hwnd=1234)
    tab.time_edit.setTime(tab.time_edit.time().fromString("21:00", "HH:mm"))
    tab.time_name.setText("레이드")
    tab.add_btn.click()
    box = BlackboxToast()
    box.show_message("최근 영상 저장 중… 30초", "pending", screen, sticky=True)
    clock[0] += 1.0
    tab.tick()
    assert events == [("sound", "time")]  # 토스트 없음
    notice = tab._notices[-1]
    assert notice.isVisible() and notice.text() == "21:00  레이드" and notice._timer.interval() == 5000
    assert notice.y() >= box.y() + box.height()  # 블랙박스 메시지 아래로
    assert box.y() == max(24, 1080 // 14)  # 블랙박스 자리는 그대로
    box.hide_message()
    assert notice.y() == max(24, 1080 // 14)  # 블랙박스가 사라지면 맨 위로
    notice.hide_message()
    tab.shutdown()


def test_paused_combat_does_not_stop_alarm(app, monkeypatch):
    """알람은 전투 보조 일시정지와 무관(탭은 일시정지를 보지 않는다)."""
    clock = [at(THU, 20, 0)]
    tab, events = make_tab(clock)
    tab.minutes.setValue(1)
    tab.start_btn.click()
    clock[0] += 61
    tab.tick()
    assert ("sound", "timer") in events
    tab.enable.setChecked(False)  # 알람 사용을 끄면 울리지 않음
    tab.minutes.setValue(1)
    tab.start_btn.click()
    clock[0] += 61
    tab.tick()
    assert events.count(("sound", "timer")) == 1
    tab.shutdown()


@pytest.mark.parametrize("present", [True, False])
def test_sound_file_or_default(monkeypatch, tmp_path, present):
    from mabinogi_addon.ui import notifier
    if present:
        (tmp_path / "알람.mp3").write_bytes(b"x")
    monkeypatch.setattr(notifier, "sound_path", lambda name: tmp_path / name)
    assert notifier.alarm_sound_file("time") == ("알람.mp3" if present else "파티 알림.mp3")
    assert notifier.alarm_sound_file("pre") == ("알람.mp3" if present else "파티 알림.mp3")
    assert notifier.alarm_sound_file("timer") == "파티 알림.mp3"


# ---- 게임 위 알람 목록 ----

def test_overlay_sorted_max3_soon_red_and_visibility(app):
    clock = [at(THU, 20, 0, 1)]
    watcher = Watcher(game=True)
    tab, _ = make_tab(clock, watcher=watcher)
    tab.show_check.setChecked(True)
    tab._update_overlay(clock[0])
    assert tab._overlay is None or not tab._overlay.isVisible()  # 알람 없으면 숨김
    for hh, mm, name in ((21, 0, "레이드"), (10, 30, "해야 할 일"), (20, 1, "곧"), (22, 0, "넷째")):
        tab.time_edit.setTime(tab.time_edit.time().fromString(f"{hh:02d}:{mm:02d}", "HH:mm"))
        tab.time_name.setText(name)
        tab.add_btn.click()
    tab.tick()
    ov = tab._overlay
    assert ov.isVisible()
    assert ov.lines == [("59초 뒤", "곧", "soon"), ("21:00", "레이드", "time"), ("22:00", "넷째", "time")]
    watcher.game = False  # 게임이 뒤로 → 숨김
    tab.tick()
    assert not ov.isVisible()
    watcher.game = True
    tab.tick()
    assert ov.isVisible() and ov.locked
    tab.lock_btn.click()  # 잠금 해제 → 상자·끌기
    assert not ov.locked and config.load_alarms()["overlay"]["locked"] is False
    tab.show_check.setChecked(False)
    assert not ov.isVisible()
    tab.shutdown()


# ---- 블랙박스 메시지 회귀: 공용 부품으로 바꿔도 모양·자리·시간 그대로 ----

def test_blackbox_message_unchanged(app):
    from mabinogi_addon.ui.blackbox_toast import SHOW_MS, BlackboxToast
    t = BlackboxToast()
    screen = QRect(100, 50, 2560, 1440)
    t.show_message("저장했어요 · 30초 분량", "done", screen)
    font = QFont()
    font.setPixelSize(14)
    font.setWeight(QFont.Weight.Bold)
    metrics = QFontMetricsF(font)
    assert (t.width(), t.height()) == (round(metrics.horizontalAdvance("저장했어요 · 30초 분량") + 34),
                                       round(metrics.height() + 12))
    assert t.x() == 100 + (2560 - t.width()) // 2 and t.y() == 50 + max(24, 1440 // 14)
    assert t._timer.interval() == SHOW_MS == 3000 and t.kind() == "done" and t.text() == "저장했어요 · 30초 분량"
    t.show_message("저장 중 10%", "pending", screen, sticky=True)
    assert not t._timer.isActive() and t.sticky
    t.hide_message()
    assert not t.isVisible()
