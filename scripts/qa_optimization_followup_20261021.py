"""Independent follow-up checks; no real Windows or network mutations."""
import pytest

from mabinogi_addon.optimization.engine import Engine
from mabinogi_addon.optimization.frames import FrameStream
from mabinogi_addon.optimization.session import ChangeDeferred, Recovery
from test_support.regressions.optimization_contract import GUID, LaunchDuringInspection


def test_game_observation_failure_never_mutates_network(tmp_path):
    backend = LaunchDuringInspection()
    calls = []

    def game():
        calls.append(None)
        if len(calls) > 1:
            raise OSError('injected observation failure')
        return None

    backend.game = game
    recovery = Recovery(tmp_path / 'recovery.json', backend, lambda: True)
    engine = Engine(backend, recovery, lambda: True)
    assert engine.start(dict(cpu=False, count=None, adapter=GUID, tcp=True, rss=False))
    engine.thread.join(3)
    assert not engine.busy and len(calls) > 1
    assert not backend.writes and not backend.restarts


def test_each_restart_is_guarded_and_remaining_target_survives_reload(tmp_path):
    backend = LaunchDuringInspection()
    recovery = Recovery(tmp_path / 'recovery.json', backend, lambda: True)
    other = '22345678-1234-1234-1234-123456789abc'
    recovery.restart_targets = {GUID, other}
    recovery._save()
    calls = []

    def guard():
        calls.append(None)
        if len(calls) == 2:
            raise ChangeDeferred('game started before the second restart')

    with pytest.raises(ChangeDeferred):
        recovery.flush_network(guard=guard)
    assert len(backend.restarts) == 1
    assert len(recovery.restart_targets) == 1
    assert backend.restarts[0][0] not in recovery.restart_targets
    reloaded = Recovery(recovery.path, backend, lambda: False)
    assert reloaded.restart_targets == recovery.restart_targets


def test_v1_qpc_at_long_uptime_is_not_relative_time():
    frequency = 10_000_000
    start = 180 * 86400
    stream = FrameStream(123, frequency)
    stream.boundary(start)
    stream.feed('Application,ProcessID,SwapChainAddress,TimeInSeconds,'
                'msBetweenPresents,QPCTime', start + 1)
    for n in range(1, 61):
        tick = round(start * frequency + n * frequency / 60)
        stream.feed(f'game.exe,123,0xabc,{n / 60},16.6666667,{tick}', start + 1)
    assert stream.snapshot(start + 1)['fps'] == pytest.approx(60, rel=1e-5)
    stream.boundary(start + 2)
    stream.feed(f'game.exe,123,0xabc,0.5,16.6666667,{(start + 1) * frequency}', start + 2)
    assert stream.snapshot(start + 2)['fps'] is None
