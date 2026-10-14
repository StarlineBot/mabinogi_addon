"""프로세스 생존뿐 아니라 워커 복구·캡처 해제·객체 수거도 검증한다.

네이티브 QThread abort를 pytest와 격리하기 위해 별도 프로세스에서 실행한다.
캡처 진입은 Event로 동기화하고, 종료 후에는 Qt 이벤트와 GC를 처리한다.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest


_PREAMBLE = """
import os, time, gc, threading, weakref, numpy as np
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
from mabinogi_addon.ui import buff_controller as bc
from mabinogi_addon.ui.buff_controller import BuffController

app = QApplication([])

def run_loop(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()

def wait_until(predicate, timeout_ms=3000):
    deadline = time.monotonic() + timeout_ms / 1000
    while not predicate():
        assert time.monotonic() < deadline, "Condition was not reached"
        run_loop(5)

def collect_objects():
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()

class FakeOverlay:
    locked = True
    def __init__(self): self.updates = 0
    def set_items(self, *a): self.updates += 1
    def show(self): pass
    def hide(self): pass

class FakeWatcher:
    def is_game_active(self): return True
    def is_self_active(self): return False

class _R:
    entries = []; alerts = []; alerts2 = []

class OkEngine:
    def tick(self, region, now, foreground=True, bar_region=None): return _R()

class ThrowEngine:
    def __init__(self, recover=False):
        self.calls = 0
        self.recover = recover
    def tick(self, *a, **k):
        self.calls += 1
        if not self.recover or self.calls == 1:
            raise RuntimeError("boom in tick")
        return _R()

class FrameSrc:
    def __init__(self): self.closes = 0
    def grab(self): return np.zeros((20, 20, 3), np.uint8)
    def close(self): self.closes += 1

class BlockSrc(FrameSrc):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.returned = threading.Event()
    def grab(self):
        self.entered.set()
        assert self.release.wait(10), "Capture was not released"
        self.returned.set()
        return None

def make_ctrl(overlay=None):
    return BuffController(overlay or FakeOverlay(), {}, {}, watcher=FakeWatcher())
"""


_MW_PREAMBLE = """
import os, json, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtWidgets import QApplication
from mabinogi_addon import config
_tmp = Path(tempfile.mkdtemp()) / "c.json"
_tmp.write_text("{}")
config._read_local_config = lambda path=None: json.loads(_tmp.read_text())
config._write_local_config = (
    lambda data, path=None: _tmp.write_text(json.dumps(data, ensure_ascii=False))
)
"""


_SCENARIOS = {
    "restart_drop": _PREAMBLE + """
refs = []
for _ in range(30):
    source, bar_source, engine = BlockSrc(), FrameSrc(), OkEngine()
    ctrl = make_ctrl()
    ctrl.start(source, engine, interval_ms=10, bar_source=bar_source)
    assert source.entered.wait(5), "Capture was not entered"
    worker = ctrl._worker
    refs.append(tuple(weakref.ref(obj) for obj in (ctrl, worker, engine)))
    ctrl.stop(timeout_ms=1)
    assert worker.isRunning(), "Stop did not time out"
    assert worker in bc._ZOMBIES
    del ctrl, worker, engine
    collect_objects()
    source.release.set()
    wait_until(lambda: source.closes and bar_source.closes and not bc._ZOMBIES)
    assert source.returned.is_set()
    assert source.closes == bar_source.closes == 1
    del source, bar_source
    collect_objects()
run_loop(50)
collect_objects()
assert not bc._ZOMBIES
assert all(ref() is None for row in refs for ref in row), "Finished objects retained"
""",
    "tick_throws": _PREAMBLE + """
source, engine = FrameSrc(), ThrowEngine()
ctrl = make_ctrl()
ctrl.start(source, engine, interval_ms=5)
try:
    wait_until(lambda: engine.calls >= 5)
    assert ctrl._worker.isRunning(), "Worker stopped after tick exception"
finally:
    ctrl.stop(timeout_ms=1000)
assert source.closes == 1
""",
    "tick_recovers": _PREAMBLE + """
source, engine, overlay = FrameSrc(), ThrowEngine(recover=True), FakeOverlay()
ctrl = make_ctrl(overlay)
ctrl.start(source, engine, interval_ms=5)
try:
    wait_until(lambda: engine.calls >= 5 and overlay.updates >= 4)
    assert ctrl._worker.isRunning()
finally:
    ctrl.stop(timeout_ms=1000)
assert source.closes == 1
""",
    "reap_race": _PREAMBLE + """
source, bar_source = BlockSrc(), FrameSrc()
ctrl = make_ctrl()
ctrl.start(source, OkEngine(), bar_source=bar_source)
assert source.entered.wait(5)
worker = ctrl._worker
original_wait = worker.wait
def finish_before_check():
    source.release.set()
    assert original_wait(2000)
    return True
worker.isFinished = finish_before_check
ctrl.stop(timeout_ms=1)
run_loop(50)  # queued finished delivery follows the synchronous isFinished fallback
assert source.closes == bar_source.closes == 1, "Sources closed more than once"
assert not bc._ZOMBIES
""",
    "shutdown_blocked": _MW_PREAMBLE + _PREAMBLE + """
from mabinogi_addon.ui.main_window import MainWindow
w = MainWindow()
source = BlockSrc()
ctrl = make_ctrl()
ctrl.start(source, OkEngine(), interval_ms=10)
w.buff_controller = ctrl
assert source.entered.wait(5), "Capture was not entered"
w._force_quit = True
w.close()  # actual closeEvent must reach its final process exit
os._exit(99)
""",
}


def _run_scenario(name: str, mutation: str = "") -> subprocess.CompletedProcess:
    script = _SCENARIOS[name]
    if mutation:
        assert script.startswith(_PREAMBLE)
        script = _PREAMBLE + mutation + script[len(_PREAMBLE):]
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("name", list(_SCENARIOS))
def test_no_native_abort(name: str):
    proc = _run_scenario(name)
    assert proc.returncode == 0, (
        f"[{name}] returncode={proc.returncode}\n{proc.stderr[-2000:]}"
    )


@pytest.mark.parametrize("name, mutation", [
    ("tick_throws", "bc._TrackWorker.run = lambda self: self._tick_once(True)\n"),
    ("restart_drop", "BuffController._close_sources = lambda *a: None\n"),
    ("restart_drop", """
class KeepFinished(set):
    def discard(self, value): pass
bc._ZOMBIES = KeepFinished()
"""),
    ("restart_drop", """
import ast, inspect, textwrap
tree = ast.parse(textwrap.dedent(inspect.getsource(BuffController.stop)))
class KeepFinishedConnection(ast.NodeTransformer):
    def visit_Try(self, node):
        if any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "disconnect"
            and any(isinstance(arg, ast.Name) and arg.id == "_reap" for arg in call.args)
            for statement in node.body for call in ast.walk(statement)
        ):
            return []
        return self.generic_visit(node)
tree = KeepFinishedConnection().visit(tree)
ast.fix_missing_locations(tree)
namespace = {}
exec(compile(tree, "<qa-retain-finished-connection>", "exec"), bc.__dict__, namespace)
BuffController.stop = namespace["stop"]
"""),
], ids=["tick_guard_removed", "source_close_omitted", "zombie_retained", "connection_retained"])
def test_lifecycle_assertions_detect_broken_behavior(name: str, mutation: str):
    proc = _run_scenario(name, mutation)
    assert proc.returncode != 0, "Injected lifecycle defect passed the scenario"
    assert "AssertionError" in proc.stderr, proc.stderr[-2000:]


def test_delayed_worker_still_enters_blocked_capture():
    proc = _run_scenario("restart_drop", """
original_run = bc._TrackWorker.run
delayed_once = False
def delayed_run(self):
    global delayed_once
    if not delayed_once:
        delayed_once = True
        time.sleep(0.45)
    original_run(self)
bc._TrackWorker.run = delayed_run
""")
    assert proc.returncode == 0, proc.stderr[-2000:]
