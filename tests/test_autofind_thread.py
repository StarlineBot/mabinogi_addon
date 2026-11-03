"""Real worker ownership, cancellation and caches for automatic discovery."""
from threading import Event, get_ident
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QWidget

from mabinogi_addon import config, autofind_state as state
from mabinogi_addon.ui import autofind_runtime as module

TARGET = (11, 22, 0, 0, 1920, 1080)
BOX = dict(x=10, y=20, w=30, h=40)


@pytest.fixture
def runtime(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window._setup_busy = lambda: False
    window._watcher = SimpleNamespace(is_game_active=lambda: True)
    window.dorcha_tab = SimpleNamespace(_own_window_over=lambda area: False)
    window.boss_tab = SimpleNamespace(_grab_rect=lambda *a: pytest.fail('unexpected Qt capture'))
    window.setup_guide = SimpleNamespace(record_result=lambda *a: None)
    window._reload_autofind_feature = lambda *a: None
    target = [TARGET]
    monkeypatch.setattr(module, 'registered_game_target', lambda *a: target[0])
    config._write_local_config({'buffTracker': {'captureRegion': BOX}})
    runtime = module.AutofindRuntime(window)
    runtime.timer.stop()
    calls = []
    class Capture:
        def __init__(self): calls.append(('open', get_ident()))
        def grab(self, region):
            calls.append(('grab', get_ident()))
            w, h = region['width'], region['height']
            return SimpleNamespace(bgra=bytes(w*h*4), width=w, height=h)
        def close(self): calls.append(('close', get_ident()))
    import mss
    monkeypatch.setattr(mss, 'mss', Capture)
    monkeypatch.setattr(module, 'buff_templates', lambda: ())
    monkeypatch.setattr(module, 'readable', lambda *a, **kw: True)
    yield runtime, window, calls, target
    runtime.shutdown()
    if runtime.executor is not None:
        runtime.executor.shutdown(wait=True)
    window.close()


def finish(runtime):
    assert runtime.future is not None
    runtime.future.result(timeout=5)
    runtime.tick()
    assert runtime.future is None


def test_registered_capture_reuses_worker_and_closes_on_owner(runtime):
    r, window, calls, target = runtime
    main = get_ident()
    for _ in range(4):
        r.tick()
        finish(r)
    assert [kind for kind, _ in calls] == ['open'] + ['grab']*4
    worker_ids = {tid for _, tid in calls}
    assert len(worker_ids) == 1 and main not in worker_ids
    r.shutdown()
    r.executor.shutdown(wait=True)
    assert calls[-1] == ('close', next(iter(worker_ids)))
    r.shutdown()
    assert sum(kind == 'close' for kind, _ in calls) == 1


@pytest.mark.parametrize('small', [False, True])
def test_search_capture_and_detection_run_on_same_worker(runtime, monkeypatch, small):
    r, _, calls, _ = runtime
    r.target = TARGET
    detected = []
    def detect(*args):
        detected.append(get_ident())
        return None
    monkeypatch.setattr(module, 'run_detector', detect)
    monkeypatch.setattr(module, 'find_expected', detect)
    r._search('boss', ('boss',), 0, waiting=True, small=small)
    r.future.result(timeout=5)
    assert detected == [calls[0][1]]
    assert detected[0] != get_ident()


def test_only_own_window_overlap_uses_qt_capture(runtime, monkeypatch):
    r, window, calls, _ = runtime
    captured = []
    read_threads = []
    window.dorcha_tab._own_window_over = lambda area: True
    window.boss_tab._grab_rect = lambda *a: (captured.append(get_ident()), np.zeros((40,30,3),np.uint8))[1]
    monkeypatch.setattr(module, 'readable', lambda *a, **kw: (read_threads.append(get_ident()), True)[1])
    r.tick()
    finish(r)
    assert captured == [get_ident()] and not calls
    assert read_threads and read_threads[0] != get_ident()


def test_settings_and_icons_cached_until_config_write(runtime, monkeypatch):
    r, _, _, _ = runtime
    reads, loads = [], []
    original = config._read_local_config
    monkeypatch.setattr(config, '_read_local_config', lambda *a, **kw: (reads.append(1), original(*a, **kw))[1])
    monkeypatch.setattr(module, 'buff_templates', lambda: (loads.append(get_ident()), ())[1])
    for _ in range(3):
        r.tick()
        finish(r)
    assert len(reads) == len(loads) == 1
    config.save_capture_region(20, 20, 30, 40)
    reads.clear()
    r.tick()
    finish(r)
    assert len(reads) == 1 and len(loads) == 2
    assert all(tid != get_ident() for tid in loads)


@pytest.mark.parametrize('interrupt', ['off', 'target', 'manual', 'pause', 'shutdown'])
def test_inflight_capture_cannot_publish_after_interruption(runtime, monkeypatch, interrupt):
    r, window, calls, target = runtime
    entered, release = Event(), Event()
    original = r.native.grab
    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(r.native, 'grab', blocked)
    monkeypatch.setattr(module, 'run_detector', lambda *a: (100,200,300,400))
    r.target = TARGET
    r._search('buff', ('buff',), 0)
    future = r.future
    assert entered.wait(5)
    if interrupt == 'off': state.set_automatic(False)
    elif interrupt == 'target': target[0] = (33,44,0,0,1920,1080)
    elif interrupt == 'manual': config.save_capture_region(50,60,30,40)
    elif interrupt == 'pause': window._paused = True
    else: r.shutdown()
    r.tick()
    release.set()
    future.result(timeout=5)
    r.tick()
    assert not r.candidates and state.remembered('buff') is None
    assert config.load_capture_region() == (dict(x=50,y=60,w=30,h=40) if interrupt == 'manual' else BOX)


def test_busy_worker_does_not_queue_more_capture_jobs(runtime, monkeypatch):
    r, _, calls, _ = runtime
    entered, release = Event(), Event()
    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return np.zeros((40,30,3),np.uint8)
    monkeypatch.setattr(r.native, 'grab', blocked)
    r.tick()
    assert entered.wait(5)
    future = r.future
    for _ in range(20): r.tick()
    assert r.future is future
    release.set()
    finish(r)


def test_capture_failure_keeps_confirmation_time_out_and_closes(runtime, monkeypatch):
    r, _, calls, _ = runtime
    r.tick()
    finish(r)
    def failed(*args): raise OSError('capture unavailable')
    monkeypatch.setattr(r.native.sct, 'grab', failed)
    candidate = state.Confirmation(BOX, state.epoch('buff'), TARGET)
    candidate.last_time = 1
    r.candidates['buff'] = candidate
    r.tick()
    finish(r)
    assert candidate.last_time is None and candidate.elapsed == 0
    assert r.lost.get('buff', 0) == 0
    r.shutdown()
    r.executor.shutdown(wait=True)
    assert calls[-1][0] == 'close'


def test_real_buff_icons_cached_and_keep_sample_reading(monkeypatch):
    from pathlib import Path
    from mabinogi_addon import image_io
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    r = module.AutofindRuntime(window)
    r.timer.stop()
    frame = image_io.imread(Path(__file__).parent/'data/image01.png')[420:910,112:416]
    original = image_io.imread
    loads = []
    monkeypatch.setattr(image_io, 'imread', lambda path: (loads.append(get_ident()), original(path))[1])
    def read(revision):
        r._submit({}, lambda: r._read('buff', frame, revision))
        assert r.future.result(timeout=5)
        r.future = r.job = None
    try:
        read(0)
        first = len(loads)
        assert first > 1 and all(tid != get_ident() for tid in loads)
        read(0)
        assert len(loads) == first
        read(1)
        assert len(loads) == first*2
    finally:
        r.shutdown()
        r.executor.shutdown(wait=True)
        window.close()
