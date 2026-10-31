"""Requirement probes shared by regular regression and the historical QA command."""
import copy
import json

from mabinogi_addon.optimization.engine import Engine
from mabinogi_addon.optimization.frames import FrameStream
from mabinogi_addon.optimization.session import Recovery
from mabinogi_addon.system.optimization import WindowsOptimization
from mabinogi_addon.system.presentmon import arguments


GUID = '12345678-1234-1234-1234-123456789abc'
GAME = {'pid': 123, 'birth': '987654321'}


def test_pinned_v1_qpc_header_is_accepted():
    # PresentMon v2.3.1 CsvOutput.cpp WriteCsvHeader<FrameMetrics1>,
    # with display/GPU/input tracking disabled and --qpc_time enabled.
    header = ('Application,ProcessID,SwapChainAddress,Runtime,SyncInterval,'
              'PresentFlags,Dropped,TimeInSeconds,msInPresentAPI,'
              'msBetweenPresents,QPCTime')
    assert '--v1_metrics' in arguments(123, 'MabinogiAddon-' + 'a' * 32)
    stream = FrameStream(123, 1000)
    stream.feed(header, 101)
    for n in range(26):
        stamp = 100.02 + n * .02
        stream.feed(f'game.exe,123,0xabc,DXGI,0,0,0,{stamp},0.1,20,'
                    f'{round(stamp * 1000)}', stamp)
    assert abs(stream.snapshot(100.52)['fps'] - 50) < .01


def test_parser_control_modern_header():
    stream = FrameStream(123, 1000)
    stream.feed('Application,ProcessID,SwapChainAddress,TimeInQPC,MsBetweenPresents', 100)
    for n in range(26):
        stamp = 100.02 + n * .02
        stream.feed(f'game.exe,123,0xabc,{round(stamp * 1000)},20', stamp)
    assert abs(stream.snapshot(100.52)['fps'] - 50) < .01


class LaunchDuringInspection:
    validate = staticmethod(WindowsOptimization.validate)

    def __init__(self):
        self.running = False
        self.values = {'ack': None, 'nodelay': None, 'autotuning': 'disabled'}
        self.writes = []
        self.restarts = []

    def game(self):
        return copy.deepcopy(GAME) if self.running else None

    def processes(self):
        # The user launches the game after the initial absent-game observation,
        # while the engine is still enumerating processes before network writes.
        self.running = True
        return []

    def governor_running(self):
        return False

    def alive(self, target):
        return False  # End the finite probe after the network batch.

    def read(self, kind, target):
        return self.values[kind]

    def write(self, kind, target, value):
        self.writes.append((kind, value, self.running))
        self.values[kind] = value

    def restart_network(self, target):
        self.restarts.append((target, self.running))


def test_game_start_during_inspection_defers_network(tmp_path):
    backend = LaunchDuringInspection()
    recovery = Recovery(tmp_path / 'recovery.json', backend, lambda: True)
    engine = Engine(backend, recovery, lambda: True)
    assert engine.start(dict(cpu=False, count=None, adapter=GUID, tcp=True, rss=False))
    engine.thread.join(3)
    assert not engine.busy
    evidence = dict(writes=backend.writes, restarts=backend.restarts,
                    journal=json.loads(recovery.path.read_text(encoding='utf-8')))
    assert not backend.writes and not backend.restarts, evidence


def test_network_control_game_already_running(tmp_path):
    backend = LaunchDuringInspection()
    backend.running = True
    recovery = Recovery(tmp_path / 'recovery.json', backend, lambda: True)
    engine = Engine(backend, recovery, lambda: True)
    assert engine.start(dict(cpu=False, count=None, adapter=GUID, tcp=True, rss=False))
    engine.thread.join(3)
    assert not engine.busy and not backend.writes and not backend.restarts
