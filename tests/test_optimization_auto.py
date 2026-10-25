"""최적화 명세 13.10 자동 적용: 게임마다 걸고 정리, 네트워크 자동 변경 없음, Governor 보류, 비정상 종료 뒤 이어 관리, 앱 시작 대기."""
import json
from types import SimpleNamespace

import pytest

from mabinogi_addon import config
from mabinogi_addon.optimization.engine import Engine
from mabinogi_addon.optimization.session import Recovery
from mabinogi_addon.system.process_priority import HIGH, NORMAL
from mabinogi_addon.ui import optimization_controller as module
from test_optimization import Backend, GUID, TARGET, _wait
from test_navigation import window  # noqa: F401  (픽스처)

SECOND = {'pid': 456, 'birth': '111222333'}


def key(target):
    return ('priority', json.dumps(target, sort_keys=True))


class GameBackend(Backend):
    """게임을 켜고 끄는 가짜 OS. current가 None이면 게임 없음."""
    def __init__(self):
        super().__init__()
        self.current = [TARGET]
        self.governor = [False]
        for target in (TARGET, SECOND):
            self.values[key(target)] = NORMAL
        self.values[('ack', json.dumps(GUID))] = None
        self.game = lambda: self.current[0]
        self.alive = lambda target: self.current[0] == target
        self.processes = lambda: []
        self.governor_running = lambda: self.governor[0]


AUTO = dict(cpu=False, count=None, adapter=None, tcp=False, rss=False, priority=True, auto=True)


@pytest.fixture
def setup(tmp_path):
    backend = GameBackend()
    return Recovery(tmp_path / 'journal.json', backend, lambda: True), backend


def test_auto_cleans_up_each_game_and_waits_for_the_next(setup):
    r, b = setup
    e = Engine(b, r, lambda: True)
    assert e.start(AUTO)
    assert _wait(lambda: b.values[key(TARGET)] == HIGH)
    b.current[0] = None  # 게임 종료
    assert _wait(lambda: b.values[key(TARGET)] == NORMAL, 6)  # 그 게임에 건 값만 원복
    assert _wait(lambda: '다음 게임을 기다려요' in e.status, 6)
    assert e.busy and e.task == 'session' and not r.pending  # 세션(토글)은 켜진 채
    b.current[0] = SECOND  # 다음 게임
    assert _wait(lambda: b.values[key(SECOND)] == HIGH, 6)
    assert [i['target'] for i in r.pending] == [SECOND] and len(r.items) == 1  # 끝난 기록은 정리
    e.stop(); e.thread.join(5)
    assert b.values[key(SECOND)] == NORMAL and not r.pending


def test_manual_session_still_ends_on_game_exit_when_auto_turned_off_midway(setup):
    r, b = setup
    e = Engine(b, r, lambda: True)
    assert e.start(AUTO)
    assert _wait(lambda: b.values[key(TARGET)] == HIGH)
    e.auto = False  # 체크를 끔: 지금 게임이 끝나면 이전처럼 세션도 끝
    b.current[0] = None
    e.thread.join(6)
    assert not e.busy and e.session_end == 'game_exit' and b.values[key(TARGET)] == NORMAL


def test_auto_never_touches_network_and_starts_while_fastping_is_kept(setup):
    r, b = setup
    r.apply('ack', GUID, 1)  # 예전에 건 패스트핑(원복 전까지 유지되는 정상 상태)
    writes = len(b.writes)
    e = Engine(b, r, lambda: True)
    assert e.start(AUTO)  # 수동 시작과 달리 남은 네트워크 기록이 자동 적용을 막지 않는다
    assert _wait(lambda: b.values[key(TARGET)] == HIGH)
    b.current[0] = None
    assert _wait(lambda: b.values[key(TARGET)] == NORMAL, 6)
    assert all(kind == 'priority' for kind, _t, _v in b.writes[writes:])
    assert [i['kind'] for i in r.pending] == ['ack'] and not b.restarts
    e.stop(); e.thread.join(5)
    assert [i['kind'] for i in r.pending] == ['ack']  # 세션을 끝내도 네트워크는 그대로(원복은 토글로)


def test_governor_holds_auto_without_ending_and_resumes(setup):
    r, b = setup
    e = Engine(b, r, lambda: True)
    assert e.start(AUTO)
    assert _wait(lambda: b.values[key(TARGET)] == HIGH)
    b.governor[0] = True
    assert _wait(lambda: e.held and b.values[key(TARGET)] == NORMAL, 6)  # 다투지 않고 정리 후 보류
    assert e.busy and 'Governor' in e.status
    assert module.optimization_badge(r, e) == ('최적화: 보류', 'neutral')
    b.governor[0] = False
    assert _wait(lambda: not e.held and b.values[key(TARGET)] == HIGH, 6)  # 끄면 다시 적용(한도 새로 계산)
    e.stop(); e.thread.join(5)


def test_after_crash_running_game_is_managed_again_with_original_record(setup, tmp_path):
    r, b = setup
    r.apply('priority', TARGET, HIGH)  # 지난 실행이 건 값(앱 비정상 종료로 원복 못 함)
    assert b.values[key(TARGET)] == HIGH
    reopened = Recovery(tmp_path / 'journal.json', b, lambda: True)
    writes = len(b.writes)
    e = Engine(b, reopened, lambda: True)
    assert e.start(AUTO)
    assert _wait(lambda: '게임 우선순위' in e.status)
    assert len(b.writes) == writes and reopened.pending[0]['old'] == NORMAL  # 원복 대신 이어 관리
    assert '미적용' not in e.status
    b.current[0] = None
    assert _wait(lambda: b.values[key(TARGET)] == NORMAL, 6)  # 그 게임이 끝나면 원래 값으로
    e.stop(); e.thread.join(5)


def test_after_crash_without_game_old_values_are_restored_before_waiting(setup, tmp_path):
    r, b = setup
    r.apply('priority', TARGET, HIGH)
    b.current[0] = None
    reopened = Recovery(tmp_path / 'journal.json', b, lambda: True)
    e = Engine(b, reopened, lambda: True)
    assert e.start(AUTO)
    assert _wait(lambda: '게임 실행 대기' in e.status)
    assert b.values[key(TARGET)] == NORMAL and not reopened.pending
    e.stop(); e.thread.join(5)


# ---- 화면·설정 ----

def test_auto_option_is_saved_and_defaults_off(tmp_path):
    path = tmp_path / 'c.json'
    assert 'auto' not in config.load_optimization_selection(path)
    config.save_optimization_selection(dict(cpu=True, priority=True, tcp=True, auto=True), path)
    assert config.load_optimization_selection(path)['auto'] is True


def _controller(window, monkeypatch):
    w = window[0]
    c = w.optimization_tools; c.timer.stop()
    monkeypatch.setattr(module, 'optimization_available', lambda: True); c.refresh_access()
    started = []
    monkeypatch.setattr(c.engine, 'start', lambda options: started.append(options) or True)
    return w, c, started


def test_checkbox_is_off_by_default_and_turning_on_starts_waiting_without_network(window, monkeypatch):
    w, c, started = _controller(window, monkeypatch)
    d = c.panel
    assert not d.auto.isChecked() and d.auto.text() == '마비노기를 켜면 자동 적용'
    config.save_optimization_selection(dict(layout='none'))  # 13.11: CPU 체크 해제 대신 '배치 안 함'
    d.tcp.setChecked(True); d.priority.setChecked(True)
    d.auto.setChecked(True)
    assert started == [dict(cpu=False, count=None, layout='none', adapter=None, tcp=False, rss=False, priority=True, auto=True)]
    assert c.engine.auto and config.load_optimization_selection()['auto'] is True
    assert c._summary_requested['auto'] is True


def test_no_auto_start_without_any_process_item(window, monkeypatch):
    w, c, started = _controller(window, monkeypatch)
    config.save_optimization_selection(dict(layout='none')); c.panel.priority.setChecked(False)
    c.panel.auto.setChecked(True)
    assert started == []


def test_app_start_waits_for_game_once_when_auto_saved(window, monkeypatch):
    w, c, started = _controller(window, monkeypatch)
    config.save_optimization_selection(dict(layout='none')); c.panel.priority.setChecked(True)
    c._restoring_selection = True; c.panel.auto.setChecked(True); c._restoring_selection = False  # 저장값 복원(시작 안 함)
    assert started == []
    c._auto_pending = True  # 앱 시작 때 저장된 '자동 적용 켬'
    c._tick()
    assert len(started) == 1 and started[0]['auto'] and not started[0]['tcp']
    c._tick()
    assert len(started) == 1  # 한 번만


def test_manual_start_carries_auto_choice(window, monkeypatch):
    w, c, started = _controller(window, monkeypatch)
    d = c.panel
    config.save_optimization_selection(dict(layout='none')); d.priority.setChecked(True)
    d.tcp.setChecked(False)  # 13.14: 패스트핑 기본 켬 — 이 테스트는 연결 없이 시작
    c._restoring_selection = True; d.auto.setChecked(True); c._restoring_selection = False
    c._start_optimization()
    assert started[-1]['auto'] is True


def test_fps_record_has_auto_apply_flag(window, monkeypatch):
    from mabinogi_addon.optimization.frames import FrameStream
    w, c, started = _controller(window, monkeypatch)
    monkeypatch.setattr(module.presentmon, 'clock', lambda: (100.0, 1000000))
    c.stream = FrameStream(123, 1000000, c.summary)
    c._sync_summary_context(100.0)
    assert c.summary.context['optimization_auto_apply'] is False
    c._restoring_selection = True; c.panel.auto.setChecked(True); c._restoring_selection = False
    c._sync_summary_context(101.0)
    assert c.summary.context['optimization_auto_apply'] is True


# ---- 0.18.0 QA ----

def test_unchecking_auto_while_waiting_ends_session_and_later_game_is_untouched(setup):
    # 재현 scripts/qa_0180_auto_uncheck_waiting.py: 게임 없는 대기 중 체크 해제 → 그 뒤 켠 게임에 적용되면 안 됨
    r, b = setup
    r.apply('ack', GUID, 1)  # 네트워크 기록은 그대로 남아야 한다
    b.current[0] = None
    e = Engine(b, r, lambda: True)
    assert e.start(AUTO)
    assert _wait(lambda: '게임 실행 대기' in e.status)
    e.auto = False
    e.thread.join(5)
    assert not e.busy and e.session_end == 'auto_off' and '게임 대기를 멈췄어요' in e.status
    b.current[0] = TARGET
    assert not _wait(lambda: b.values[key(TARGET)] == HIGH, 1.5)
    assert [i['kind'] for i in r.pending] == ['ack']


def test_unchecking_auto_while_game_managed_ends_at_that_game_exit(setup):
    r, b = setup
    e = Engine(b, r, lambda: True)
    assert e.start(AUTO)
    assert _wait(lambda: b.values[key(TARGET)] == HIGH)
    e.auto = False
    assert not _wait(lambda: not e.busy, 2.5)  # 관리 중인 게임이 있으면 계속
    assert b.values[key(TARGET)] == HIGH
    b.current[0] = None
    e.thread.join(6)
    assert not e.busy and e.session_end == 'game_exit' and b.values[key(TARGET)] == NORMAL


def test_manual_session_without_auto_still_waits_for_game(setup):
    r, b = setup
    b.current[0] = None
    e = Engine(b, r, lambda: True)
    assert e.start(dict(AUTO, auto=False))
    assert not _wait(lambda: not e.busy, 1.5)
    b.current[0] = TARGET
    assert _wait(lambda: b.values[key(TARGET)] == HIGH, 4)
    e.stop(); e.thread.join(5)


def test_toggle_off_during_auto_says_waiting_stopped(window, monkeypatch):
    w, c, started = _controller(window, monkeypatch)
    c._restoring_selection = True; c.panel.auto.setChecked(True); c._restoring_selection = False
    c.engine.session_end = 'cancel'
    c.engine.status = '세션을 중단하고 CPU를 원복해요.'
    c._sync_optimization_toggle()
    assert '자동 적용을 멈췄어요 · 앱을 다시 켜거나 체크를 다시 켜면 게임을 기다려요.' in c.engine.status
    c.engine.session_end = 'cancel'
    c._restoring_selection = True; c.panel.auto.setChecked(False); c._restoring_selection = False
    c.engine.status = '세션을 중단하고 CPU를 원복해요.'
    c._sync_optimization_toggle()
    assert '자동 적용을 멈췄어요' not in c.engine.status  # 체크가 꺼져 있으면 안내 없음


# ---- 0.22.0 QA: 자동 적용 세션이 엔진을 점유해도 환경 확인 ----

def test_inspection_runs_while_auto_session_waits_and_fills_layouts(window, monkeypatch, tmp_path):
    from test_cpu_layouts import X9800
    from test_optimization_recommend import WIRED
    w = window[0]
    c = w.optimization_tools; c.timer.stop()
    monkeypatch.setattr(module, 'optimization_available', lambda: True); c.refresh_access()
    b = GameBackend()
    b.current[0] = None  # 게임 대기 중
    b.topology = lambda: X9800
    b.adapters = lambda: [dict(WIRED)]
    b.background_candidate = lambda p, game: True
    b.values[('cpu', json.dumps(TARGET, sort_keys=True))] = 0xFFFF
    c.backend = b
    c.recovery = Recovery(tmp_path / 'j.json', b, lambda: True)
    c.engine = Engine(b, c.recovery, c._can_start)
    d = c.panel
    assert d.split.findData('focus') < 0  # 환경 확인 전
    c._restoring_selection = True; d.priority.setChecked(True); d.auto.setChecked(True); c._restoring_selection = False
    c._auto_pending = True
    c._tick()  # 앱 시작: 자동 세션이 게임을 기다리며 엔진 점유
    assert _wait(lambda: c.engine.busy and c.engine.phase == 'waiting')
    w._tabs.setCurrentWidget(c.panel)  # 탭을 연다 → 세션 중이어도 환경 확인
    assert _wait(lambda: (c._tick(), d.split.findData('focus') >= 0)[1])
    assert c.engine.busy and c.engine.task == 'session'  # 세션은 그대로
    assert d.split.count() == 4 and d.split.currentData() == 'focus'
    assert d.adapter.currentData() == '11111111-1111-1111-1111-111111111111'
    assert d.inspect.isEnabled()  # '다시 확인'도 세션 중 누를 수 있음
    b.current[0] = TARGET  # 게임 시작 → 추천 배치 이름이 결과 줄·상단에
    assert _wait(lambda: c.engine.outcome.get('cpu') == ('ok', ''), 6)
    c._tick()
    assert '✓ CPU 배치 · 게임 집중 (6+2)' in d.results.text().split('\n')
    assert c._badge_split == '· 게임 집중'
    c.engine.stop(); c.engine.thread.join(5)


def test_engine_inspection_during_session_keeps_session_status(setup):
    from test_cpu_layouts import X9800
    r, b = setup
    b.current[0] = None
    b.topology = lambda: X9800
    b.adapters = lambda: []
    e = Engine(b, r, lambda: True)
    assert e.start(AUTO)
    assert _wait(lambda: e.phase == 'waiting' and '게임 실행 대기' in e.status)
    assert e.inspect() and e.inspecting or e.inspection is not None
    assert not e.inspect() or e.inspection is not None  # 이미 확인 중이면 겹치지 않음
    assert _wait(lambda: e.inspection is not None and not e.inspecting)
    assert e.inspection[0] is X9800 and e.task == 'session' and '환경을 확인했어요' not in e.status
    e.stop(); e.thread.join(5)
