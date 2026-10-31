"""0.34.0 패스트핑(사용자 결정 E안 — 완전히 막기): 게임이 꺼진 상태에서 최적화를 켤 때만 적용하고, 게임 종료로는 네트워크 작업 없음.

제보: 최적화를 켠 날 PC 종료가 끝나지 않음. 원인 후보 — 게임 실행 중 켜면 패스트핑을 미뤘다가 게임 프로세스가 끝나는 순간
앱이 스스로 값을 쓰고 Restart-NetAdapter를 했다 → 게임을 끄고 곧바로 PC를 끄면 Windows 종료와 겹침.
이 게임은 인터넷이 잠깐만 끊겨도 종료되므로 게임 중에는 적용할 방법이 없다 → 게임 중에는 이미 목표값일 때만 진행,
아니면 '게임을 끈 뒤 다시 눌러 주세요'로 막는다. 적용된 패스트핑·최대 프레임 400은 사용자가 최적화를 끌 때만 되돌린다.
"""
import json

from PySide6.QtWidgets import QMessageBox

from mabinogi_addon.optimization.engine import Engine, fastping_ready
from mabinogi_addon.optimization.session import Recovery
from test_navigation import window  # noqa: F401  (픽스처)
from test_optimization import GUID, TARGET, Backend, _wait

NORMAL = 0x20
NETWORK = ('ack', 'autotuning')


class GameBackend(Backend):
    def __init__(self, running=True, ready=False):
        super().__init__()
        self.current = [TARGET if running else None]
        self.values[('priority', json.dumps(TARGET, sort_keys=True))] = NORMAL
        self.values[('ack', json.dumps(GUID))] = 1 if ready else None
        self.values[('autotuning', json.dumps('global'))] = 'normal' if ready else 'restricted'
        self.game = lambda: self.current[0]
        self.alive = lambda target: self.current[0] == target
        self.processes = lambda: []
        self.governor_running = lambda: False


def _start(tmp_path, running=True, ready=False, priority=True, auto=False):
    b = GameBackend(running, ready)
    r = Recovery(tmp_path / 'j.json', b, lambda: True)
    e = Engine(b, r, lambda: True)
    assert e.start(dict(cpu=False, count=None, adapter=GUID, tcp=True, rss=False, priority=priority, auto=auto))
    return b, r, e


def _network_writes(b):
    return [w for w in b.writes if w[0] in NETWORK]


def test_fastping_ready_reads_only():
    values = {('ack', GUID): 1, ('autotuning', 'global'): 'normal'}
    assert fastping_ready(lambda kind, target: values[(kind, target)], GUID)
    values[('ack', GUID)] = None
    assert not fastping_ready(lambda kind, target: values[(kind, target)], GUID)

    def broken(*_a):
        raise OSError('읽기 실패')
    assert not fastping_ready(broken, GUID) and not fastping_ready(lambda *_a: 1, None)  # 모르면 막는 쪽


def test_game_running_and_not_ready_writes_nothing(tmp_path):
    b, r, e = _start(tmp_path, priority=False)
    e.thread.join(5)
    assert not _network_writes(b) and not b.restarts and not r.pending and not r.restart_targets
    assert e.outcome['tcp'] == ('fail', '게임을 끈 뒤 적용할 수 있어요')


def test_game_running_and_already_ready_runs_without_change(tmp_path):
    b, r, e = _start(tmp_path, ready=True, priority=False)
    e.thread.join(5)
    assert not _network_writes(b) and not b.restarts and e.outcome['tcp'] == ('same', '')


def test_game_exit_does_no_network_work(tmp_path):
    for auto in (False, True):
        b, r, e = _start(tmp_path / str(auto), auto=auto)
        e.auto = auto
        assert _wait(lambda: e.phase == 'applied')
        b.current[0] = None  # 게임 종료
        if auto:
            assert _wait(lambda: e.phase == 'ended', 6)
            e.stop()
        e.thread.join(6)
        assert not _network_writes(b) and not b.restarts  # 예전: 여기서 패스트핑 적용·어댑터 재시작
        assert any(w[0] == 'priority' for w in b.writes)  # 게임에 건 우선순위 원복은 그대로


def test_game_off_applies_once_and_keeps_until_user_turns_off(tmp_path):
    b, r, e = _start(tmp_path, running=False, priority=False)
    e.thread.join(5)
    assert b.restarts == [GUID] and e.outcome['tcp'] == ('ok', '')
    assert b.values[('ack', json.dumps(GUID))] == 1
    # 게임을 켰다 꺼도 패스트핑은 그대로(되돌리지 않음)
    b.current[0] = TARGET
    b.current[0] = None
    assert b.values[('ack', json.dumps(GUID))] == 1 and b.restarts == [GUID]
    # 사용자가 최적화를 끄면 원래대로(재연결 포함)
    assert e.restore_network()
    e.thread.join(5)
    assert b.restarts == [GUID, GUID] and not r.pending
    assert b.values[('ack', json.dumps(GUID))] is None and b.values[('autotuning', json.dumps('global'))] == 'restricted'


def test_screen_blocks_start_during_game_unless_ready(window, monkeypatch):
    w, app = window
    controller = w.optimization_tools
    controller.refresh_access()
    if controller.panel is None or not controller._can_start():
        import pytest
        pytest.skip('최적화 화면 없음(로그인 필요 환경)')
    d = controller.panel
    d.tcp.setChecked(True)
    d.adapter.addItem('이더넷', GUID)
    d.adapter.setCurrentIndex(d.adapter.count() - 1)
    shown, begun, asked = [], [], []
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: shown.append(a[1]))
    monkeypatch.setattr(controller, '_begin', lambda options: begun.append(options))
    monkeypatch.setattr(controller, '_network_confirmation', lambda: asked.append(1) or True)
    monkeypatch.setattr(controller, '_game_running', lambda: True)
    values = {}
    monkeypatch.setattr(controller.backend, 'read', lambda kind, target: values[kind], raising=False)
    values.update(ack=None, autotuning='restricted')
    controller._start_optimization()
    assert shown == ['패스트핑은 게임을 끈 뒤에 적용할 수 있어요'] and not begun and not asked  # 완전히 막음
    values.update(ack=1, autotuning='normal')
    controller._start_optimization()
    assert len(begun) == 1 and not asked  # 이미 목표값: 확인 창 없이 시작(끊김 없음)
    monkeypatch.setattr(controller, '_game_running', lambda: False)
    controller._start_optimization()
    assert len(begun) == 2 and asked == [1]  # 게임 꺼짐: 지금처럼 확인 창 → 적용
