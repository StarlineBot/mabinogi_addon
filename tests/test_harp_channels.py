"""하프 채널 연결 시간(docs/harp-channel-tcp-spec.md) — 로컬 테스트 서버로 성공·거부·시간 초과·취소, 화면 이탈·일시정지.

실제 게임 서버에는 접속하지 않는다(모든 연결은 127.0.0.1 또는 가짜 연결 함수).
"""
from __future__ import annotations

import json
import socket
import threading
from datetime import datetime, timedelta
from time import monotonic, perf_counter, sleep

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

from mabinogi_addon import harp_latency as hl
from test_navigation import window  # noqa: F401  (창 픽스처)


# ---- 주소 데이터 파일 -------------------------------------------------------------------------
def test_data_file_matches_spec_table():
    channels = hl.load_channels()
    assert [c.number for c in channels] == [n for n in range(1, 23) if n != 11]  # 11채널(하우징) 제외, 21개
    table = {31: (1, 2, 3), 32: (4, 5, 6), 33: (7, 8, 9), 34: (10, 12, 13), 39: (14, 15, 16), 40: (17, 18, 19), 41: (20, 21, 22)}
    expected = {n: (f"211.218.233.{ip}", port) for ip, nums in table.items() for n, port in zip(nums, (11020, 11021, 11023))}
    assert {c.number: c.address for c in channels} == expected
    assert all(c.source == "관찰" and c.checked == "2026-11-03" for c in channels)


@pytest.mark.parametrize("row", [{"channel": 1, "ip": "bad", "port": 1}, {"channel": 1, "ip": "1.2.3.4", "port": 0},
                                 {"channel": 1, "ip": "1.2.3.4", "port": 1, "source": "모름"}])
def test_bad_data_rows_fail_instead_of_guessing(tmp_path, row):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"channels": [row]}), encoding="utf-8")
    with pytest.raises((ValueError, OSError)):
        hl.load_channels(path)


# ---- 로컬 테스트 서버 ------------------------------------------------------------------------
@pytest.fixture
def server():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(8)
    yield s.getsockname()[1]
    s.close()


def _closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def blackhole():
    """연결이 완료되지 않는 주소: 대기열(backlog)이 가득 찬 채 accept하지 않는 서버(SYN이 버려져 응답 없음)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(0)
    port = s.getsockname()[1]
    fillers = []
    for _ in range(4):
        c = socket.socket()
        c.setblocking(False)
        c.connect_ex(("127.0.0.1", port))
        fillers.append(c)
    sleep(0.05)
    probe = hl.connect_time("127.0.0.1", port, timeout=0.3)
    if probe.kind != hl.TIMEOUT_KIND:
        for c in fillers:
            c.close()
        s.close()
        pytest.skip(f"이 환경은 가득 찬 대기열에서도 연결이 끝남({probe.kind})")
    yield port
    for c in fillers:
        c.close()
    s.close()


def test_success_against_local_server(server):
    r = hl.connect_time("127.0.0.1", server, timeout=2)
    assert r.kind == hl.OK and 0 <= r.ms < 1000


def test_refused_against_closed_port():
    assert hl.connect_time("127.0.0.1", _closed_port(), timeout=2).kind == hl.REFUSED


def test_timeout_is_reported_at_the_limit(blackhole):
    started = perf_counter()
    r = hl.connect_time("127.0.0.1", blackhole, timeout=0.3)
    assert r.kind == hl.TIMEOUT_KIND and 0.28 <= perf_counter() - started < 1.0


def test_cancel_stops_a_pending_connect_quickly(blackhole):
    cancel = threading.Event()
    threading.Timer(0.1, cancel.set).start()
    started = perf_counter()
    r = hl.connect_time("127.0.0.1", blackhole, timeout=5, cancel=cancel)
    assert r.kind == hl.CANCELLED and perf_counter() - started < 0.5


def test_every_outcome_closes_its_socket(monkeypatch, server):
    closed_port = _closed_port()  # 고정 전에 미리(이 소켓은 세지 않음)
    opened, closed = [], []
    real = socket.socket

    class Tracked(real):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            opened.append(self)

        def close(self):
            closed.append(self)
            super().close()
    monkeypatch.setattr(hl.socket, "socket", Tracked)
    cancel = threading.Event()
    cancel.set()
    hl.connect_time("127.0.0.1", server)
    hl.connect_time("127.0.0.1", closed_port)
    hl.connect_time("127.0.0.1", server, cancel=cancel)  # 취소면 소켓을 열지 않는다
    assert len(opened) == 2 and set(map(id, opened)) <= set(map(id, closed))


# ---- 통계·추천 --------------------------------------------------------------------------------
def _ok(ms):
    return hl.Result(hl.OK, ms)


def test_median_uses_recent_successes_only_and_cancel_is_not_an_attempt():
    s = hl.ChannelStats(("1.1.1.1", 1))
    for r in (_ok(5), hl.Result(hl.TIMEOUT_KIND), _ok(1), _ok(3), hl.Result(hl.CANCELLED), hl.Result(hl.REFUSED)):
        s.record(r)
    assert s.median == 3 and (s.successes, s.attempts) == (3, 5) and s.last.kind == hl.REFUSED
    for ms in (10, 10, 10, 10):
        s.record(_ok(ms))
    assert list(s.recent) == [3, 10, 10, 10, 10] and s.median == 10  # 최근 5회


def test_address_change_clears_that_channel_history():
    a = hl.Channel(1, "1.1.1.1", 1)
    b = hl.Channel(2, "1.1.1.1", 2)
    h = hl.History([a, b])
    h.record(1, _ok(1))
    h.record(2, _ok(2))
    h.sync([hl.Channel(1, "1.1.1.2", 1), b])
    assert h.stats[1].attempts == 0 and h.stats[2].attempts == 1


def test_fastest_ties_and_recommendation():
    chans = [hl.Channel(n, "1.1.1.1", n) for n in (1, 4, 7, 9, 13)]
    h = hl.History(chans)
    for n, ms in ((1, 3.0), (4, 2.05), (7, 2.0), (9, 2.1), (13, 2.2)):
        h.record(n, _ok(ms))
    h.record(13, hl.Result(hl.TIMEOUT_KIND))
    # 0.40.2 명세 변경: 성공 3회 전에는 추천·배지 없음, 배지는 추천 채널 하나에만, 추천 = 중앙값이 가장 작은 채널
    assert h.fastest() == set() and h.recommendation() == (None, [], False)
    for _ in range(2):
        for n, ms in ((1, 3.0), (4, 2.05), (7, 2.0), (9, 2.1), (13, 2.2)):
            h.record(n, _ok(ms))
    assert h.fastest() == {7}
    assert h.recommendation() == (7, [4, 9], True)  # 7(2.0)과 0.1ms 안 → '비슷하게 빠름'(중앙값 순)
    only_fail = hl.History([chans[0]])
    only_fail.record(1, hl.Result(hl.REFUSED))
    assert only_fail.fastest() == set() and only_fail.recommendation() == (None, [], False)


def test_round_runs_at_most_two_at_once_and_reports_every_channel():
    chans = [hl.Channel(n, "127.0.0.1", n) for n in range(1, 8)]
    live, peak, results = [0], [0], {}
    lock = threading.Lock()
    done = threading.Event()

    def connect(ip, port, timeout, cancel):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        sleep(0.02)
        with lock:
            live[0] -= 1
        return _ok(port)
    r = hl.Round(chans, lambda n: None, lambda n, res: results.__setitem__(n, res), lambda c: done.set(), connect=connect)
    r.start()
    assert done.wait(5)
    assert peak[0] == 2 and sorted(results) == list(range(1, 8))


# ---- 화면 -------------------------------------------------------------------------------------
def wait_until(cond, seconds=5.0):
    deadline = monotonic() + seconds
    while not cond() and monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()
    return cond()


class Gate:
    """채널 연결을 붙잡아 두는 가짜 연결(취소되면 바로 돌아옴)."""

    def __init__(self, results=None, hold=False):
        self.results = results or {}
        self.hold = threading.Event()
        if not hold:
            self.hold.set()
        self.calls = []

    def __call__(self, ip, port, timeout, cancel):
        self.calls.append(port)
        while not self.hold.is_set():
            if cancel.is_set():
                return hl.Result(hl.CANCELLED)
            sleep(0.005)
        return self.results.get(port, _ok(2.0 + port * 0.3))


@pytest.fixture
def harp(monkeypatch):
    from mabinogi_addon.ui.harp_tab import HarpChannelTab
    app = QApplication.instance() or QApplication([])
    chans = [hl.Channel(n, "127.0.0.1", n) for n in (1, 2, 3, 4, 5, 6, 7)]
    clock = [1000.0]
    made = []

    def make(gate):
        tabs = QTabWidget()
        tab = HarpChannelTab(channels=chans, connect=gate, now=lambda: datetime(2026, 11, 3, 21, 41, 8),
                             clock=lambda: clock[0])
        tabs.addTab(QWidget(), "다른 탭")
        tabs.addTab(tab, "하프 채널 연결")
        tabs.resize(800, 600)
        made.append((tabs, tab))
        return tabs, tab
    yield app, make, clock
    for tabs, tab in made:
        tab.shutdown()
        tabs.close()
        tabs.deleteLater()
    app.processEvents()


def test_opening_measures_at_once_then_every_60s_while_viewing(harp):
    app, make, clock = harp
    gate = Gate({3: hl.Result(hl.TIMEOUT_KIND), 5: hl.Result(hl.REFUSED)})
    tabs, tab = make(gate)
    tabs.show()
    assert tab._round is None and gate.calls == []  # 다른 탭을 보는 동안은 재지 않는다
    tabs.setCurrentWidget(tab)
    assert wait_until(lambda: tab._round is None and tab._last_time is not None)
    assert sorted(gate.calls) == [1, 2, 3, 4, 5, 6, 7]
    assert tab.cards[3].value.text().count("시간 초과") and tab.cards[5].value.text().count("연결 거부")
    # 0.40.2 명세 변경: 성공 3회 전에는 추천·배지 없이 '측정 중이에요(n/3)'
    assert not any(card.badge.isVisible() for card in tab.cards.values())
    assert "측정 중이에요(1/3)" in tab.recommend.main.text()
    assert "마지막 측정 오후 9:41:08 · 다음 측정까지 60초" in tab.status.text()
    clock[0] += 59
    tab._tick()
    assert tab._round is None and len(gate.calls) == 7
    clock[0] += 1
    tab._tick()  # 한 회차가 끝나고 60초 뒤
    assert wait_until(lambda: len(gate.calls) == 14 and tab._round is None)
    assert tab.history.stats[1].attempts == 2
    clock[0] += 60
    tab._tick()  # 세 번째 회차 → 성공 3회
    assert wait_until(lambda: len(gate.calls) == 21 and tab._round is None)
    assert tab.cards[1].badge.isVisible() and not tab.cards[2].badge.isVisible()
    assert "1채널" in tab.recommend.main.text() and "다음으로 빠른 채널" in tab.recommend.others.text()
    assert "2채널" in tab.recommend.others.text()


def test_leaving_screen_cancels_and_cancel_is_not_counted(harp):
    app, make, clock = harp
    gate = Gate(hold=True)
    tabs, tab = make(gate)
    tabs.show()
    tabs.setCurrentWidget(tab)
    assert wait_until(lambda: len(gate.calls) == 2)  # 동시 최대 2개
    assert "측정 중 · 0 / 7" in tab.status.text()
    tabs.setCurrentIndex(0)  # 화면 이탈
    assert tab._round is None
    gate.hold.set()
    app.processEvents()
    sleep(0.1)
    app.processEvents()
    assert all(s.attempts == 0 for s in tab.history.stats.values())  # 취소는 시도에 넣지 않음
    assert len(gate.calls) == 2  # 남은 채널은 시작하지 않음
    tabs.setCurrentWidget(tab)  # 다시 보면 바로 한 번
    assert wait_until(lambda: tab._last_time is not None)
    assert all(s.attempts == 1 for s in tab.history.stats.values())


def test_pause_minimize_and_no_overlap(harp):
    app, make, clock = harp
    gate = Gate(hold=True)
    tabs, tab = make(gate)
    tabs.show()
    tabs.setCurrentWidget(tab)
    assert wait_until(lambda: tab._round is not None and len(gate.calls) == 2)
    first = tab._round
    tab.measure_now()  # 회차 중에는 새 회차를 만들지 않음
    assert tab._round is first and not tab.refresh.isEnabled()
    tab.set_paused(True)  # 전투 보조 일시정지
    assert tab._round is None
    assert "일시정지" in tab.status.text() or "아직 측정 안 함" in tab.status.text()
    gate.hold.set()
    tab.set_paused(False)
    assert wait_until(lambda: tab._last_time is not None and tab._round is None)
    clock[0] += 61
    tabs.showMinimized()
    app.processEvents()
    tab._tick()
    if tabs.isMinimized():  # 오프스크린에서도 최소화 상태가 잡히면
        assert tab._round is None


def test_channel_tab_is_public_and_renamed(window, monkeypatch):
    """0.42.0 사용자 결정: 서버별 채널 상태는 모두에게 공개(로그인·제작자와 무관), 이름 변경."""
    from mabinogi_addon import feature_access
    w, app = window
    tabs = w.optimization_tools.panel.tabs
    names = lambda: [tabs.tabText(i) for i in range(tabs.count())]
    assert names()[-1] == "서버별 채널 상태" and "하프 채널 연결" not in names()
    for creator in (True, False):
        monkeypatch.setattr(feature_access, "is_creator", lambda c=creator: c)
        w._refresh_harp_access()
        assert names().count("서버별 채널 상태") == 1
    calls = []
    monkeypatch.setattr(w.harp_tab, "measure_background", lambda rounds=1: calls.append(rounds))
    w._startup_channel_measure()  # 창이 뜬 뒤 몇 초 뒤(타이머) — 시작 직후 3회
    w._home_refresh_channels()    # 홈 새로고침 — 1회
    assert calls == [3, 1]
    w.harp_tab._connect = lambda *a: hl.Result(hl.OK, 2.0)  # 탭을 열면 바로 재므로 실제 서버 대신 가짜 연결
    w.home_page.open_feature.emit("channels")
    assert tabs.currentWidget() is w._harp_scroll


def test_startup_windows_are_not_always_on_top():
    """0.40.0(사용자): 로딩 창이 맨 위에 떠 뒤 창을 가리지 않게."""
    from PySide6.QtCore import Qt
    from mabinogi_addon.ui.splash import Splash
    QApplication.instance() or QApplication([])
    s = Splash(typing=False)
    try:
        assert not s.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    finally:
        s.close()
        s.deleteLater()



# ---- 0.40.2 화면 정리: 큰 숫자 = 중앙값, 배지 하나, 표본 3회, 배지 잘림 ---------------------------------
def _history(values):
    """{채널: [성공 ms ...]} → History."""
    h = hl.History([hl.Channel(n, "1.1.1.1", n) for n in values])
    for n, seq in values.items():
        for ms in seq:
            h.record(n, _ok(ms))
    return h


def test_recommend_smallest_median_and_group_similar():
    h = _history({15: [2.0, 2.0, 2.0], 21: [2.0, 2.0, 2.0], 6: [1.9, 1.9, 1.9], 22: [2.8, 2.8, 2.8]})
    assert h.recommendation() == (6, [15, 21], True)  # 2.0·2.0·1.9 → 1.9 채널 추천, 나머지는 '비슷하게 빠름'
    assert h.fastest() == {6}
    far = _history({1: [1.5, 1.5, 1.5], 2: [2.0, 2.0, 2.0], 3: [2.5, 2.5, 2.5], 4: [3.0, 3.0, 3.0]})
    assert far.recommendation() == (1, [2, 3], False)  # 0.1ms 안이 없으면 '다음으로 빠른 채널'


def test_two_samples_or_fewer_give_no_recommendation(harp):
    app, make, clock = harp
    tabs, tab = make(Gate())
    for n, s in tab.history.stats.items():
        for _ in range(2):
            s.record(_ok(2.0 + n / 10))
    tab._last_time = datetime(2026, 11, 3, 21, 41, 8)
    tab._refresh_view()
    assert tab.history.recommendation()[0] is None
    assert "측정 중이에요(2/3)" in tab.recommend.main.text()
    assert not any(card.badge.isVisible() for card in tab.cards.values())


def test_big_number_is_median_and_just_now_is_small(harp):
    from mabinogi_addon.ui.harp_tab import ChannelCard
    app, make, clock = harp
    s = hl.ChannelStats(("1.1.1.1", 1))
    for ms in (2.8, 2.7, 2.9, 2.8, 10.5):  # 한 번 튄 10.5
        s.record(_ok(ms))
    card = ChannelCard(22)
    try:
        card.show_state("done", s)
        assert ">2.8<" in card.value.text() and "10.5" not in card.value.text()  # 큰 숫자 = 중앙값
        assert "방금 10.5" in card.sub.text() and "5/5" in card.sub.text()
        s.record(hl.Result(hl.TIMEOUT_KIND))
        card.show_state("done", s)
        assert ">2.8<" in card.value.text() and "시간 초과" in card.sub.text()
    finally:
        card.deleteLater()


def test_fastest_badge_is_not_clipped_at_narrow_window(harp):
    """0.40.2(Confirmed 스크린샷 2장): '가장 빠름'이 '가장 빠'로 잘림 — 배지 폭이 글자보다 좁아지지 않는다(칸 폭은 그대로)."""
    from PySide6.QtWidgets import QScrollArea
    app, make, clock = harp
    tabs, tab = make(Gate())
    tabs.setCurrentWidget(tab)
    tab.cancel()
    for n, s in tab.history.stats.items():
        for _ in range(3):
            s.record(_ok(2.0 + n / 10))
    tab._last_time = datetime(2026, 11, 3, 21, 41, 8)
    tab._refresh_view()
    tabs.resize(760, 600)  # QA가 잘림을 본 창 폭
    tabs.show()
    app.processEvents()
    badge = tab.cards[1].badge
    assert badge.isVisible()
    assert badge.sizeHint().width() <= badge.width()


def test_unreadable_channel_file_keeps_app_running(monkeypatch, caplog):
    """0.40.2: 채널 목록을 못 읽어도(0.40.0 exe 경로 문제) 탭만 안내하고 예외로 앱을 끝내지 않는다."""
    import logging
    from mabinogi_addon.ui.harp_tab import HarpChannelTab
    QApplication.instance() or QApplication([])
    caplog.set_level(logging.ERROR)
    monkeypatch.setattr(hl, "load_channels", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("harp_channels.json")))
    tab = HarpChannelTab()
    try:
        assert tab.channels == [] and tab.load_error == "채널 목록을 불러오지 못했어요"
        assert "채널 목록을 불러오지 못했어요" in tab.recommend.main.text()
        # 0.41.1: 읽기 실패는 추천(초록) 상자가 아니라 경고색
        from mabinogi_addon.ui.palette import color
        assert color("warn") in tab.recommend.main.text() and color("warn") in tab.recommend.styleSheet()
        assert color("ok") not in tab.recommend.styleSheet()
        assert any("하프 채널 목록" in r.getMessage() for r in caplog.records)
        tab.measure_now()
        assert tab._round is None
    finally:
        tab.shutdown()
        tab.deleteLater()


# ---- 0.42.0 서버 선택·시작 직후 측정·홈 ---------------------------------------------------------
def test_server_combo_only_harp_selectable(harp):
    from mabinogi_addon.party.client import SERVERS
    app, make, clock = harp
    tabs, tab = make(Gate())
    combo = tab.server_combo
    assert [combo.itemData(i) for i in range(combo.count())] == list(SERVERS)
    assert combo.currentData() == "하프"
    model = combo.model()
    assert [model.item(i).isEnabled() for i in range(combo.count())] == [name == "하프" for name in SERVERS]
    assert all("준비 중" in combo.itemText(i) for i in range(combo.count()) if combo.itemData(i) != "하프")


def test_startup_burst_runs_three_rounds_without_viewing_then_stops(harp):
    """앱 시작 직후: 탭을 보지 않아도 3회 연속(첫 추천) → 그 뒤 상시 반복 없음. 홈 문구가 측정 중 → 가장 빠른 채널."""
    app, make, clock = harp
    gate = Gate()
    tabs, tab = make(gate)
    tabs.show()  # 다른 탭을 보는 중
    assert tab.home_summary() == ("아직 재지 않았어요", "muted", False)
    tab.measure_background(3)
    text, kind, busy = tab.home_summary()
    assert busy and kind == "muted" and text.startswith("측정 중이에요")
    assert wait_until(lambda: len(gate.calls) == 21 and tab._round is None, 10)
    assert tab._background == 0
    assert tab.home_summary() == ("가장 빠른 채널 1채널 2.3ms", "ok", False)
    clock[0] += 185
    assert tab.home_summary()[0] == "가장 빠른 채널 1채널 2.3ms"
    tab._tick()  # 탭을 보지 않으면 60초 재측정도 없음
    app.processEvents()
    assert len(gate.calls) == 21 and tab._round is None
    tab.measure_background(1)  # 홈 새로고침 1회
    assert wait_until(lambda: len(gate.calls) == 28 and tab._round is None)
    assert tab.history.stats[1].attempts == 4


def test_background_burst_survives_leaving_tab_but_not_pause(harp):
    app, make, clock = harp
    gate = Gate(hold=True)
    tabs, tab = make(gate)
    tabs.show()
    tabs.setCurrentWidget(tab)
    assert wait_until(lambda: len(gate.calls) == 2)
    tab.measure_background(3)  # 보는 중 회차에 이어 시작 직후 3회
    tabs.setCurrentIndex(0)  # 화면을 떠나도 시작 직후 측정은 계속
    assert tab._round is not None
    tab.set_paused(True)  # 전투 보조 일시정지면 멈춤
    assert tab._round is None and tab._background == 0
    tab.measure_background(3)
    assert tab._round is None  # 일시정지 중에는 시작하지 않음
    gate.hold.set()


def test_network_failure_is_reported_on_home(harp):
    app, make, clock = harp
    gate = Gate({n: hl.Result(hl.TIMEOUT_KIND) for n in range(1, 8)})
    tabs, tab = make(gate)
    tabs.show()
    tab.measure_background(1)
    assert wait_until(lambda: tab._round is None and tab._last_time is not None)
    assert tab.home_summary() == ("측정 못 함 · 네트워크 연결을 확인해 주세요", "warn", False)


def test_round_still_limits_concurrency_and_sends_nothing(server):
    """동시 연결 최대 2개·연결만 하고 데이터 없음(현행 유지) — 전체 공개 전 확인."""
    assert hl.CONCURRENCY == 2
    import inspect
    source = inspect.getsource(hl.connect_time)
    assert ".send" not in source and ".recv" not in source


def test_home_channel_chip_states():
    from mabinogi_addon.ui.home_page import HomePage
    app = QApplication.instance() or QApplication([])
    home = HomePage()
    try:
        home.resize(790, 800)
        home.update_state({"channel": ("가장 빠른 채널 21채널 2.0ms", "ok", False)})
        text = home.channel_label.text()
        assert "21채널" in text and "2.0ms" in text and home.channel_btn.isEnabled()
        home.set_channel("측정 중이에요(1/3)", "muted", True)
        assert "측정 중이에요(1/3)" in home.channel_label.text() and not home.channel_btn.isEnabled()
        home.set_channel("측정 못 함 · 네트워크 연결을 확인해 주세요", "warn", False)
        assert "측정 못 함" in home.channel_label.text()
        fired = []
        home.channel_refresh.connect(lambda: fired.append(1))
        home.channel_btn.click()
        assert fired == [1]
    finally:
        home.deleteLater()


# ---- 8절: 앱 켜자마자 추천(지난 결과 저장·시작 1초·화면 스레드 부담) --------------------------------
def _tab_at(when, gate, chans=None):
    from mabinogi_addon.ui.harp_tab import HarpChannelTab
    QApplication.instance() or QApplication([])
    chans = chans or [hl.Channel(n, "127.0.0.1", n) for n in (1, 2, 3, 4, 5, 6, 7)]
    now = [when]
    tab = HarpChannelTab(channels=chans, connect=gate, now=lambda: now[0], clock=monotonic)
    return tab, now


def _rounds(tab, count):
    for _ in range(count):
        tab.measure_background(1)
        assert wait_until(lambda: tab._round is None)


def test_startup_timing_constants():
    from mabinogi_addon.ui import harp_tab, main_window
    assert harp_tab.BURST_GAP == 0.5 and harp_tab.BURST_ROUNDS == 3
    import inspect  # 테스트 공통 설정(conftest)이 대기를 늘려 두므로 원래 값은 소스에서 확인
    assert "CHANNEL_STARTUP_DELAY_MS = 1000" in inspect.getsource(main_window)


def test_save_restore_round_trip_and_address_change_discards():
    from mabinogi_addon import config
    tab, now = _tab_at(datetime(2026, 11, 4, 21, 40), Gate())
    try:
        assert tab.saved is None
        _rounds(tab, 3)
        cache = config.load_channel_cache()
        assert cache["fingerprint"] == hl.fingerprint(tab.channels) and cache["measuredAt"] == "2026-11-04T21:40:00"
        assert cache["recent"]["1"] == [2.3, 2.3, 2.3]
    finally:
        tab.shutdown()
    again, _ = _tab_at(datetime(2026, 11, 5, 10, 0), Gate(hold=True))
    try:  # 다음 날 앱 시작 — 측정 전에 바로 지난 결과
        assert again.home_summary() == ("가장 빠른 채널 1채널 2.3ms", "ok", False)  # 시각 없이(사용자 결정 11-05)
        assert again.saved.stats[1].median == pytest.approx(2.3)
    finally:
        again.shutdown()
    moved = [hl.Channel(n, "127.0.0.1", n + (100 if n == 3 else 0)) for n in (1, 2, 3, 4, 5, 6, 7)]
    changed, _ = _tab_at(datetime(2026, 11, 5, 10, 0), Gate(hold=True), moved)
    try:  # 주소 목록이 바뀌면 저장값을 버린다
        assert changed.saved is None and changed.home_summary()[0] == "아직 재지 않았어요"
    finally:
        changed.shutdown()


@pytest.mark.parametrize("age,shown", [(timedelta(days=6, hours=23), True), (timedelta(days=7), False)])
def test_saved_result_seven_day_limit(age, shown):
    from mabinogi_addon import config
    chans = [hl.Channel(n, "127.0.0.1", n) for n in (1, 2, 3)]
    measured = datetime(2026, 11, 1, 12, 0)
    config.save_channel_cache({"fingerprint": hl.fingerprint(chans), "measuredAt": measured.isoformat(),
                               "recent": {"1": [2.0, 2.0, 2.0], "2": [3.0, 3.0, 3.0]}})
    tab, _ = _tab_at(measured + age, Gate(hold=True), chans)
    try:
        assert (tab.saved is not None) is shown
        if shown:
            assert tab.home_summary()[0] == "가장 빠른 채널 1채널 2.0ms"
    finally:
        tab.shutdown()


def test_saved_shown_until_three_new_rounds_then_replaced_without_mixing():
    from mabinogi_addon import config
    chans = [hl.Channel(n, "127.0.0.1", n) for n in (1, 2, 3, 4, 5, 6, 7)]
    config.save_channel_cache({"fingerprint": hl.fingerprint(chans), "measuredAt": "2026-11-04T21:40:00",
                               "recent": {"7": [1.0, 1.0, 1.0], "1": [9.0, 9.0, 9.0]}})
    tab, _ = _tab_at(datetime(2026, 11, 5, 10, 0), Gate(), chans)  # 새로 재면 1채널(2.3ms)이 가장 빠름
    try:
        assert tab.home_summary()[0] == "가장 빠른 채널 7채널 1.0ms"
        _rounds(tab, 2)  # 새 값 1~2회 — 저장값 그대로(섞지 않음)
        assert tab.home_summary()[0] == "가장 빠른 채널 7채널 1.0ms"
        assert "7채널" in tab.recommend.main.text() and "방금" not in tab.recommend.main.text()  # 측정 시각은 보이지 않음(11-05)
        _rounds(tab, 1)  # 3회 모임 → 새 값으로 교체
        assert tab.home_summary()[0] == "가장 빠른 채널 1채널 2.3ms"
        assert "1채널" in tab.recommend.main.text()
    finally:
        tab.shutdown()


def test_hidden_tab_no_card_updates_and_one_summary_and_save_per_round(monkeypatch):
    """8절 4항: 탭이 안 보이면 카드 갱신 0회, 홈 문구(summary_changed)는 회차당 1회, 저장은 회차당 최대 1회."""
    from mabinogi_addon import config
    from mabinogi_addon.ui import harp_tab
    tab, _ = _tab_at(datetime(2026, 11, 5, 10, 0), Gate())
    cards, summaries, saves = [], [], []
    monkeypatch.setattr(harp_tab.ChannelCard, "show_state", lambda self, *a: cards.append(self.number))
    tab.summary_changed.connect(lambda: summaries.append(1))
    original = config.save_channel_cache
    monkeypatch.setattr(config, "save_channel_cache", lambda data: saves.append(1) or original(data))
    try:
        assert not tab.isVisible()
        _rounds(tab, 4)
        assert cards == []                      # 숨은 탭은 채널 카드를 그리지 않음
        assert len(summaries) == 4              # 회차당 1번
        assert len(saves) == 2                  # 추천이 생긴 3·4회차에 1번씩(1~2회 값으로 덮지 않음)
        tabs = QTabWidget()
        tabs.addTab(tab, "서버별 채널 상태")
        tab._connect = Gate(hold=True)          # 보이면서 시작하는 측정은 붙잡아 둔다
        tabs.show()
        app = QApplication.instance()
        app.processEvents()
        assert len(set(cards)) == 7             # 보이는 순간 한 번에 그림
        tab.cancel()
        tabs.close()
    finally:
        tab.shutdown()


def test_saved_cards_hide_just_now_until_this_run_measures_them():
    """저장값을 보여 주는 동안 카드에 '방금 x.x' 작은 글씨 없음(추천 줄과 같게). 이번 실행 값이 생긴 카드만 '방금'."""
    from mabinogi_addon import config
    chans = [hl.Channel(n, "127.0.0.1", n) for n in (1, 2, 3)]
    config.save_channel_cache({"fingerprint": hl.fingerprint(chans), "measuredAt": "2026-11-04T21:40:00",
                               "recent": {"1": [2.0, 2.0, 2.0], "2": [3.0, 3.0, 3.0], "3": [4.0, 4.0, 4.0]}})
    gate = Gate({2: hl.Result(hl.OK, 2.5), 3: hl.Result(hl.OK, 3.5)})
    tab, _ = _tab_at(datetime(2026, 11, 5, 10, 0), gate, chans)
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "다른 탭")
    tabs.addTab(tab, "서버별 채널 상태")
    tabs.resize(800, 600)
    try:
        tabs.show()
        tabs.setCurrentWidget(tab)  # 화면을 열자마자 저장값 표시 + 바로 1회 측정
        QApplication.instance().processEvents()
        assert wait_until(lambda: tab._round is None and tab._last_time is not None)
        assert tab.saved is not None and tab._view()[1]  # 아직 지난 결과를 보여 주는 중(새 값 1회)
        for n in (1, 2, 3):
            assert "방금" in tab.cards[n].sub.text()  # 1회 측정으로 세 채널 모두 이번 실행 값이 생김
        tab2, _ = _tab_at(datetime(2026, 11, 5, 10, 0), Gate(hold=True), chans)
        holder = QTabWidget()
        holder.addTab(tab2, "x")
        holder.show()
        QApplication.instance().processEvents()
        tab2.cancel()
        tab2.history.record(1, hl.Result(hl.OK, 2.1))  # 이번 실행 값은 1채널만
        tab2._refresh_view()
        assert "방금 2.1" in tab2.cards[1].sub.text()
        for n in (2, 3):  # 저장값 카드: 큰 숫자만, '방금'·성공/시도 없음
            assert "방금" not in tab2.cards[n].sub.text() and "/" not in tab2.cards[n].sub.text()
            assert "ms" in tab2.cards[n].value.text()
        tab2.shutdown()
        holder.close()
    finally:
        tab.shutdown()
        tabs.close()
