"""0.34.0 패스트핑: 켜는 순간에만 적용 + '재부팅 대기'·[지금 적용], 게임 종료 시 자동 어댑터 재시작 제거(사용자 결정 2026-10-31).

제보: 최적화를 켠 날 PC 종료가 끝나지 않음. 원인 후보 — 게임 실행 중 켜면 패스트핑을 미뤘다가 게임 프로세스가 끝나는 순간
앱이 스스로 TcpAckFrequency·자동 조정을 쓰고 Restart-NetAdapter를 했다 → 게임을 끄고 곧바로 PC를 끄면 Windows 종료와 겹침.
이제 게임 종료로는 네트워크 작업을 하지 않는다. 게임 중 켜면 값만 써 두고(재시작 없음) '재부팅 대기'로 기록한다.
"""
import json

from mabinogi_addon.optimization.engine import Engine, TCP_PENDING, TCP_PENDING_MESSAGE
from mabinogi_addon.optimization.result_summary import PENDING_LINE, summarize
from mabinogi_addon.optimization.session import Recovery, rebooted_since
from test_optimization import GUID, TARGET, Backend, _wait

NORMAL = 0x20
NETWORK = ('ack', 'autotuning')


class GameBackend(Backend):
    def __init__(self, running=True):
        super().__init__()
        self.current = [TARGET if running else None]
        self.values[('priority', json.dumps(TARGET, sort_keys=True))] = NORMAL
        self.values[('ack', json.dumps(GUID))] = None
        self.values[('autotuning', json.dumps('global'))] = 'restricted'
        self.game = lambda: self.current[0]
        self.alive = lambda target: self.current[0] == target
        self.processes = lambda: []
        self.governor_running = lambda: False


def _start(tmp_path, running=True, auto=False, priority=True):
    b = GameBackend(running)
    r = Recovery(tmp_path / 'j.json', b, lambda: True)
    e = Engine(b, r, lambda: True)
    assert e.start(dict(cpu=False, count=None, adapter=GUID, tcp=True, rss=False, priority=priority, auto=auto))
    return b, r, e


def _network_writes(b):
    return [kind for kind, _t, _v in b.writes if kind in NETWORK]


def test_enable_during_game_writes_values_without_restart(tmp_path):
    b, r, e = _start(tmp_path)
    assert _wait(lambda: e.outcome.get('tcp') == ('pending', TCP_PENDING))
    assert _network_writes(b) == ['ack', 'autotuning'] and not b.restarts  # 값은 써 두고 재시작 없음
    assert r.reboot_pending and r.restart_pending_since is not None
    assert _wait(lambda: TCP_PENDING_MESSAGE in e.status)
    assert PENDING_LINE in summarize(e, r, dict(priority=True, tcp=True))[2]
    saved = json.loads(r.path.read_text(encoding='utf-8'))
    assert saved['restart_pending_since'] == r.restart_pending_since  # 다시 실행해도 대기 유지
    assert Recovery(r.path, b, lambda: True).reboot_pending
    e.stop(); e.thread.join(5)


def test_game_exit_does_no_network_work(tmp_path):
    for auto in (False, True):
        b, r, e = _start(tmp_path / str(auto), auto=auto)
        e.auto = auto
        assert _wait(lambda: e.outcome.get('tcp') == ('pending', TCP_PENDING) and e.phase == 'applied')
        writes, restarts = list(b.writes), list(b.restarts)
        b.current[0] = None  # 게임 종료
        if auto:
            assert _wait(lambda: e.phase == 'ended', 6)
            e.stop()
        e.thread.join(6)
        new = [w for w in b.writes if w not in writes]
        assert not [w for w in new if w[0] in NETWORK] and b.restarts == restarts  # 재시작·네트워크 쓰기 0
        assert any(w[0] == 'priority' for w in new)  # 게임에 건 우선순위 원복은 그대로
        assert r.reboot_pending


def test_apply_now_restarts_once_and_clears(tmp_path):
    b, r, e = _start(tmp_path, priority=False)
    e.thread.join(5)
    assert r.reboot_pending and not b.restarts
    b.current[0] = None  # 게임을 끈 뒤
    assert e.apply_pending_network()
    e.thread.join(5)
    assert b.restarts == [GUID] and not r.reboot_pending and not r.restart_targets
    assert e.outcome['tcp'] == ('ok', '')


def test_apply_now_refuses_while_game_runs(tmp_path):
    b, r, e = _start(tmp_path, priority=False)
    e.thread.join(5)
    assert e.apply_pending_network()  # 버튼은 화면에서 막지만, 작업 쪽도 재시작 직전에 다시 확인
    e.thread.join(5)
    assert not b.restarts and r.reboot_pending and '게임이 실행 중' in e.status


def test_reboot_clears_pending_only_when_booted_after(tmp_path):
    b, r, e = _start(tmp_path, priority=False)
    e.thread.join(5)
    since = r.restart_pending_since
    assert not r.clear_if_rebooted(since - 60) and r.reboot_pending  # 부팅이 기록보다 이르면 유지
    assert not r.clear_if_rebooted(None) and r.reboot_pending  # 부팅 시각을 모르면 유지
    assert r.clear_if_rebooted(since + 60) and not r.reboot_pending and not r.restart_targets
    assert not b.restarts  # 재부팅으로 적용 — 앱은 재시작하지 않음
    assert rebooted_since(10, 5) and not rebooted_since(5, 10) and not rebooted_since(None, 5)


def test_enable_with_game_off_restarts_once_and_same_values_skip(tmp_path):
    b, r, e = _start(tmp_path, running=False, priority=False)
    e.thread.join(5)
    assert b.restarts == [GUID] and not r.reboot_pending and e.outcome['tcp'] == ('ok', '')
    # 이미 목표값: 원복하지 않은 채 다시 켜면 바꿀 값이 없어 재시작도 없다
    b.restarts.clear()
    r2 = Recovery(tmp_path / 'j2.json', b, lambda: True)
    e2 = Engine(b, r2, lambda: True)
    assert e2.start(dict(cpu=False, count=None, adapter=GUID, tcp=True, rss=False, priority=False))
    e2.thread.join(5)
    assert not b.restarts and e2.outcome['tcp'] == ('same', '')


def test_user_turn_off_restores_with_restart(tmp_path):
    b, r, e = _start(tmp_path, priority=False)
    e.thread.join(5)
    b.current[0] = None
    assert e.restore_network()  # 사용자가 직접 끄는 원복은 지금처럼(어댑터 재시작 포함)
    e.thread.join(5)
    assert b.restarts == [GUID] and not r.pending and not r.restart_targets
    assert b.values[('ack', json.dumps(GUID))] is None and b.values[('autotuning', json.dumps('global'))] == 'restricted'
