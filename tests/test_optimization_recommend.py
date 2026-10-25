"""최적화 명세 13.12(패스트핑 이름·연결 자동 선택)·13.13(결과 요약·자세히 보기)·13.14(추천 최적화·상세 설정 접기)."""
import json
import logging
from types import SimpleNamespace as NS

import pytest
from PySide6.QtWidgets import QGroupBox

from mabinogi_addon import config
from mabinogi_addon.optimization.engine import Engine
from mabinogi_addon.optimization.result_summary import summarize
from mabinogi_addon.optimization.session import Core, Recovery, Topology
from mabinogi_addon.system.optimization import default_adapter
from mabinogi_addon.system.process_priority import HIGH, NORMAL
from mabinogi_addon.ui import optimization_controller as module
from test_navigation import window  # noqa: F401  (픽스처)
from test_optimization import Backend, TARGET, _wait

X9800 = Topology('AMD Ryzen 7 9800X3D', tuple(Core(i, (2 * i, 2 * i + 1)) for i in range(8)))
WIRED = dict(Name='이더넷', InterfaceGuid='{11111111-1111-1111-1111-111111111111}', ifIndex=5, Default=True)
WIFI = dict(Name='Wi-Fi', InterfaceGuid='{22222222-2222-2222-2222-222222222222}', ifIndex=9, Default=False)


def test_default_adapter_only_when_exactly_one_internet_route():
    assert default_adapter([WIRED, WIFI]) == '11111111-1111-1111-1111-111111111111'
    assert default_adapter([dict(WIFI)]) is None  # VPN 등: 물리 연결이 기본 경로가 아님
    assert default_adapter([WIRED, dict(WIFI, Default=True)]) is None
    assert default_adapter([]) is None


def _controller(window, monkeypatch):
    w = window[0]
    c = w.optimization_tools; c.timer.stop()
    monkeypatch.setattr(module, 'is_creator', lambda: True); c.refresh_access()
    return w, c


# ---- 13.12 ----

def test_single_connection_is_shown_as_one_line_without_choice(window, monkeypatch):
    w, c = _controller(window, monkeypatch)
    c._apply_inspection(X9800, [WIRED])
    d = c.panel
    assert d.tcp.text() == '패스트핑' and 'TcpAckFrequency' in d.notice.text()
    assert d.adapter.isHidden() and not d.adapter_label.isHidden()
    assert d.adapter_label.text() == '이더넷 (인터넷 연결 중 · 자동 선택)'
    assert d.adapter.currentData() == '11111111-1111-1111-1111-111111111111'


def test_two_connections_preselect_internet_route_and_allow_change(window, monkeypatch):
    w, c = _controller(window, monkeypatch)
    c._apply_inspection(X9800, [WIFI, WIRED])
    d = c.panel
    assert not d.adapter.isHidden() and d.adapter_label.isHidden()
    assert d.adapter.currentText() == '이더넷 (인터넷 연결 중 · 자동 선택)'
    d.adapter.setCurrentIndex(d.adapter.findData('22222222-2222-2222-2222-222222222222'))
    assert config.load_optimization_selection()['adapter'] == '22222222-2222-2222-2222-222222222222'
    c._apply_inspection(X9800, [WIFI, WIRED])
    assert d.adapter.currentText() == 'Wi-Fi'  # 직접 고른 연결은 유지


def test_unknown_internet_route_requires_manual_choice(window, monkeypatch):
    w, c = _controller(window, monkeypatch)
    c._apply_inspection(X9800, [dict(WIFI), dict(WIRED, Default=False)])
    assert c.panel.adapter.currentData() is None and not c.panel.adapter.isHidden()
    started = []
    monkeypatch.setattr(c.engine, 'start', lambda options: started.append(options))
    c._start_optimization()
    assert not started and '연결' in c.engine.status


# ---- 13.14 ----

def test_layout_order_and_advanced_is_outside_and_collapsed(window, monkeypatch):
    w, c = _controller(window, monkeypatch)
    d = c.panel
    titles = [box.title() for box in d.findChildren(QGroupBox)]
    assert titles.index('환경 확인') < titles.index('추천 최적화') < titles.index('CPU 배치') < titles.index('네트워크')
    assert '적용 · 복구' not in titles
    recommend = next(box for box in d.findChildren(QGroupBox) if box.title() == '추천 최적화')
    assert d.toggle.parent() is recommend and d.auto.parent() is recommend and d.details_toggle.parent() is recommend
    assert not recommend.isAncestorOf(d.advanced_toggle)  # 구역 밖 바로 아래
    assert d.advanced_toggle.text() == '상세 설정 ▸' and not d.advanced.isVisibleTo(d)
    d.advanced_toggle.click()
    assert d.advanced.isVisibleTo(d) and d.advanced_toggle.text() == '상세 설정 ▾'
    assert config.load_optimization_selection()['advanced'] is True
    d.advanced_toggle.setChecked(False)
    c._restore_selection()
    assert not d.advanced_toggle.isChecked()


def test_recommendation_and_custom_selection(window, monkeypatch):
    w, c = _controller(window, monkeypatch)
    c._apply_inspection(X9800, [WIRED])
    d = c.panel
    c._tick()
    assert d.recommend.text() == '이 PC 추천: 게임 우선순위 높음 · CPU 배치 게임 집중 (6+2) · 패스트핑'
    assert d.toggle.text() == '추천 설정으로 최적화' and d.reset_recommended.isHidden()
    d.split.setCurrentIndex(d.split.findData('max_focus'))
    c._tick()
    assert d.recommend.text() == '직접 고른 설정: 게임 우선순위 높음 · CPU 배치 게임 최대 집중 (7+1) · 패스트핑'
    assert d.toggle.text() == '선택한 설정으로 최적화' and not d.reset_recommended.isHidden()
    d.tcp.setChecked(False)
    c._tick()
    assert d.recommend.text() == '직접 고른 설정: 게임 우선순위 높음 · CPU 배치 게임 최대 집중 (7+1)'
    d.reset_recommended.click()
    c._tick()
    assert d.split.currentData() == 'focus' and d.tcp.isChecked() and d.toggle.text() == '추천 설정으로 최적화'


def test_first_use_defaults_to_recommended_but_saved_choice_is_kept(window, monkeypatch):
    w, c = _controller(window, monkeypatch)
    c._restore_selection()
    assert c.panel.tcp.isChecked() and c.panel.priority.isChecked()
    config.save_optimization_selection(dict(tcp=False, priority=True))
    c._restore_selection()
    assert not c.panel.tcp.isChecked()


def test_recommended_start_applies_priority_layout_and_fastping(window, monkeypatch):
    w, c = _controller(window, monkeypatch)
    c._apply_inspection(X9800, [WIRED])
    started = []
    monkeypatch.setattr(c.engine, 'start', lambda options: started.append(options))
    monkeypatch.setattr(c, '_network_confirmation', lambda: True)  # 직접 누를 때 네트워크 확인 1회
    c._start_optimization()
    options = started[-1]
    assert options['priority'] and options['layout'] == 'focus' and options['tcp']
    assert options['adapter'] == '11111111-1111-1111-1111-111111111111'


# ---- 13.13 결과 요약 ----

def engine_state(busy=True, task='session', phase=None, outcome=None, cancel=False, status='', ran=True):
    return NS(busy=busy, task=task, phase=phase, outcome=outcome or {}, cancel=NS(is_set=lambda: cancel),
              status=status, ran=ran)


def recovery_state(pending=(), corrupt=False, restart=()):
    return NS(pending=list(pending), corrupt=corrupt, restart_targets=set(restart))


REQ = dict(priority=True, cpu=True, tcp=True, auto=False)


@pytest.mark.parametrize('engine, recovery, requested, expected', [
    (engine_state(phase='waiting'), recovery_state(), dict(REQ, auto=True),
     ('마비노기를 기다리는 중 · 켜지면 자동으로 적용해요', 'neutral', [])),
    (engine_state(phase='applied', outcome=dict(priority=('ok', ''), cpu=('ok', ''), tcp=('same', ''))), recovery_state(), REQ,
     ('최적화 적용 중', 'ok', ['✓ 게임 우선순위 높음', '✓ CPU 배치 · 게임 집중 (6+2)', '✓ 패스트핑 · 이미 목표값이라 그대로 뒀어요'])),
    (engine_state(phase='applied', outcome=dict(priority=('ok', ''), cpu=('released', '다른 프로그램이 바꿔서 그대로 뒀어요'),
                                                tcp=('fail', '관리자 권한이 필요해요'))), recovery_state(), REQ,
     ('일부 항목을 적용하지 못했어요', 'warn',
      ['✓ 게임 우선순위 높음', '! CPU 배치 · 다른 프로그램이 바꿔서 그대로 뒀어요', '! 패스트핑 · 관리자 권한이 필요해요'])),
    (engine_state(phase='ended', outcome=dict(priority=('restored', ''), cpu=('restored', ''))),
     recovery_state(pending=[dict(kind='ack', state='applied')]), dict(REQ, auto=True),
     ('게임이 끝나 원래대로 되돌렸어요', 'neutral',
      ['↺ 게임 우선순위 · 되돌림', '↺ CPU 배치 · 되돌림', '• 패스트핑 · 적용 중 (최적화를 끄면 되돌려요)'])),
    (engine_state(busy=False), recovery_state(), REQ, ('원래대로 되돌렸어요', 'neutral', [])),
    (engine_state(busy=False, ran=False, status='시작 전'), recovery_state(), {}, ('시작 전 · 시스템 설정을 변경하지 않았어요.', 'neutral', [])),
    (engine_state(busy=False, status='원래부터 같은 값이라 되돌릴 것이 없어요.'), recovery_state(), REQ,
     ('원래부터 같은 값이라 되돌릴 것이 없어요.', 'neutral', [])),
    (engine_state(busy=False), recovery_state(corrupt=True), REQ,
     ('복구 기록이 손상돼 새 적용을 막았어요. 추정값으로 되돌리지 않아요.', 'error', [])),
    (engine_state(phase='held'), recovery_state(), REQ, ('Process Lasso가 실행 중이라 잠시 멈췄어요 · 끄면 다시 적용해요', 'neutral', [])),
])
def test_summary_is_current_state_line_plus_one_line_per_item(engine, recovery, requested, expected):
    result = summarize(engine, recovery, requested, layout_label='게임 집중 (6+2)')
    assert result == expected
    assert not any(token in ' '.join([result[0], *result[2]]) for token in ('PID', '0x', '개'))


class GameBackend(Backend):
    def __init__(self):
        super().__init__()
        self.current = [TARGET]
        self.values[('priority', json.dumps(TARGET, sort_keys=True))] = NORMAL
        self.game = lambda: self.current[0]
        self.alive = lambda target: self.current[0] == target
        self.processes = lambda: []
        self.governor_running = lambda: False


def test_engine_records_item_outcomes_and_auto_restore(tmp_path):
    b = GameBackend()
    r = Recovery(tmp_path / 'j.json', b, lambda: True)
    e = Engine(b, r, lambda: True)
    assert e.start(dict(cpu=False, count=None, adapter=None, tcp=False, rss=False, priority=True, auto=True))
    assert _wait(lambda: e.outcome.get('priority') == ('ok', '') and e.phase == 'applied')
    b.current[0] = None
    assert _wait(lambda: e.phase == 'ended' and e.outcome['priority'] == ('restored', ''), 6)
    e.stop(); e.thread.join(5)


def test_session_record_goes_to_app_log_and_details_once(window, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    w, c = _controller(window, monkeypatch)
    c.engine.status = '게임 우선순위: 높음 적용 · 확인 완료\nCP3.exe (PID 10596): 적용=0xF000'
    c._tick(); c._tick()
    records = [r for r in caplog.records if r.getMessage().startswith('최적화 상태:')]
    assert len(records) == 1 and 'PID 10596' in records[0].getMessage()
    d = c.panel
    assert 'PID 10596' in d.details.text() and d.details.isHidden() and 'PID' not in d.status.text() + d.results.text()
    d.details_toggle.click()
    assert d.details.isVisibleTo(d) and d.details_toggle.text() == '자세히 보기 ▾'


# ---- 13.13 QA 후속: 시작이 막힌 이유·환경 확인 실패는 보이는 상태 줄에 ----

def test_blocked_start_without_internet_route_shows_warning_on_status_line(window, monkeypatch):
    w, c = _controller(window, monkeypatch)
    c._apply_inspection(X9800, [dict(WIFI), dict(WIRED, Default=False)])  # 기본 경로 판단 불가
    started = []
    monkeypatch.setattr(c.engine, 'start', lambda options: started.append(options))
    d = c.panel
    d.toggle.click()  # 추천 설정으로 최적화
    c._tick()
    assert not started
    assert d.status.text() == '패스트핑을 적용할 연결을 상세 설정에서 선택해 주세요.'
    assert '#e67e22' in d.status.styleSheet() and d.results.isHidden()
    d.adapter.setCurrentIndex(1)  # 연결을 고르면 안내는 사라진다
    c._tick()
    assert d.status.text().startswith('시작 전')


def test_nothing_selected_warns_on_status_line(window, monkeypatch):
    w, c = _controller(window, monkeypatch)
    config.save_optimization_selection(dict(layout='none'))
    d = c.panel
    d.priority.setChecked(False); d.tcp.setChecked(False)
    c._start_optimization(); c._tick()
    assert d.status.text() == '사용할 항목을 선택해 주세요.' and '#e67e22' in d.status.styleSheet()


def test_inspection_failure_is_visible_until_rechecked(window, monkeypatch):
    w, c = _controller(window, monkeypatch)
    c.engine.inspection, c.engine.inspection_failed = (X9800, []), ['네트워크 연결']
    c._tick()
    d = c.panel
    assert d.status.text().startswith('네트워크 연결을 읽지 못했어요') and '#e67e22' in d.status.styleSheet()
    d.priority.setChecked(False)  # 다른 선택을 바꿔도 환경 확인 실패 안내는 유지
    c._tick()
    assert d.status.text().startswith('네트워크 연결을 읽지 못했어요')
    c.engine.inspection, c.engine.inspection_failed = (X9800, [WIRED]), []
    c._tick()
    assert d.status.text().startswith('시작 전')


def test_app_log_gets_only_newly_added_session_lines(window, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    w, c = _controller(window, monkeypatch)
    c.engine.status = '게임 우선순위: 높음 적용 · 확인 완료'
    c._tick()
    c.engine.status = '게임 우선순위: 높음 적용 · 확인 완료\n다른 도구가 CPU 배치를 바꿨어요'
    c._tick()
    messages = [r.getMessage() for r in caplog.records if r.getMessage().startswith('최적화 상태:')]
    assert messages == ['최적화 상태: 게임 우선순위: 높음 적용 · 확인 완료', '최적화 상태: 다른 도구가 CPU 배치를 바꿨어요']


@pytest.mark.parametrize('failed, expected', [
    (['CPU 구조'], 'CPU 구조를 읽지 못했어요'),
    (['네트워크 연결'], '네트워크 연결을 읽지 못했어요'),
    (['CPU 구조', '네트워크 연결'], 'CPU 구조·네트워크 연결을 읽지 못했어요'),
])
def test_inspection_failure_uses_correct_object_particle(window, monkeypatch, failed, expected):
    # QA 후속: 'CPU 구조을'(조사 오류) → 마지막 항목 받침에 따라 을/를
    w, c = _controller(window, monkeypatch)
    c.engine.inspection, c.engine.inspection_failed = (X9800, []), failed
    c._tick()
    assert c.panel.status.text().startswith(expected)
    assert module.object_particle('Wi-Fi') == '을(를)'
