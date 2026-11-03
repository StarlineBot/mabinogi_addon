"""Real worker ownership, cancellation and caches for automatic discovery."""
from threading import Event, get_ident
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QWidget

from mabinogi_addon import config, autofind_state as state
from mabinogi_addon.ui import autofind_runtime as module

REAL_READABLE = module.readable

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


@pytest.mark.parametrize('replacement', ['destroyed', 'owner-changed', 'hidden', 'exe-changed'])
def test_tick_reuses_valid_target_and_rediscovers_replacement(runtime, monkeypatch, replacement):
    import sys
    from mabinogi_addon.system import window_capture, dwm_thumbnail, window_watcher
    r, window, _, _ = runtime
    window._paused = True  # Exercise real target lookup without starting native capture.
    monkeypatch.setattr(module, 'registered_game_target', window_capture.registered_game_target)
    monkeypatch.setattr(window_capture, 'sys', SimpleNamespace(platform='win32'))
    clock = [0.0]
    monkeypatch.setattr(window_capture, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    native = dict(hwnd=11, pid=22, valid=True, visible=True, exe='client.exe')
    enumerations, owners = [], []
    monkeypatch.setattr(config, 'load_game_exe', lambda: 'Client.exe')
    monkeypatch.setattr(dwm_thumbnail, 'find_game_window',
                        lambda *a: (enumerations.append(1), native['hwnd'])[1])
    monkeypatch.setattr(dwm_thumbnail, 'window_rect', lambda hwnd: (0,0,1920,1080))
    monkeypatch.setattr(window_watcher, '_exe_basename_of_pid',
                        lambda pid: (owners.append(pid), native['exe'])[1])
    monkeypatch.setitem(sys.modules, 'win32gui', SimpleNamespace(
        IsWindow=lambda hwnd: native['valid'], IsWindowVisible=lambda hwnd: native['visible']))
    monkeypatch.setitem(sys.modules, 'win32process', SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (1, native['pid'] if hwnd == 11 else 44)))
    r.tick()
    assert r.target == TARGET and len(enumerations) == 1
    for _ in range(5): r.tick()
    assert len(enumerations) == 1 and owners == [22]
    generation = r.target_generation
    r.candidates['buff'] = state.Confirmation(BOX, state.epoch('buff'), TARGET)
    native['hwnd'] = 33
    if replacement == 'destroyed': native['valid'] = False
    elif replacement == 'hidden': native['visible'] = False
    elif replacement == 'owner-changed': native['pid'] = 99
    else:
        native['exe'] = 'other.exe'
        clock[0] = 6  # Ownership is revalidated after the existing five-second cache.
    r.tick()
    assert r.target == (33,44,0,0,1920,1080)
    assert len(enumerations) == 2 and r.target_generation == generation + 1
    assert not r.candidates
    native.update(hwnd=0, valid=False)
    r.tick()
    assert r.target is None
    native.update(hwnd=55, valid=True, visible=True, exe='client.exe')
    r.tick()
    assert r.target == (55,44,0,0,1920,1080)
    assert len(enumerations) == 4


@pytest.mark.parametrize('automatic', [False, True])
@pytest.mark.parametrize('stamp', ['2026-10-09 185117', '2026-10-14 000646'])
def test_real_hundred_does_not_start_search_or_false_notice(runtime, monkeypatch, automatic, stamp):
    from mabinogi_addon import image_io
    from mabinogi_addon.autofind_replay import detector_assets, run_detector
    from mabinogi_addon.detect.tuarim_reader import read_percent, read_observation
    r, window, _, _ = runtime
    frame = image_io.imread(f'tests/data/스크린샷 {stamp}.png')
    box = run_detector('tuarim', frame, detector_assets('tuarim'), {})
    assert box is not None
    x,y,w,h = box
    crop = frame[y:y+h,x:x+w]
    assert read_percent(crop) is None  # The tab's hold-at-full contract is unchanged.
    assert read_observation(crop) == 100
    # The fixture normally stubs readers; restore the production function for this replay.
    monkeypatch.setattr(module, 'readable', REAL_READABLE)
    assert module.readable('tuarim', crop)
    monkeypatch.setattr(r.native, 'grab', lambda *a: crop.copy())
    notices = []
    window.setup_guide.record_result = lambda *a: notices.append(a)
    monkeypatch.setattr(r, '_search', lambda *a, **kw: pytest.fail('100% must not trigger reacquisition'))
    config._write_local_config({'tuarim': {'enabled': True, 'box': BOX},
                                'autofind': {'enabled': automatic}})
    clock = [0.0]
    monkeypatch.setattr(module, 'monotonic', lambda: clock[0])
    for _ in range(65):
        r.tick()
        r.future.result(timeout=5)
        clock[0] += .5
        r.tick()
        clock[0] += .5
    assert r.lost['tuarim'] == r.failures['tuarim'] == 0
    assert not r.candidates and not notices


@pytest.mark.parametrize('changed', [False, True])
def test_confirmed_resource_only_reloads_when_position_changes(runtime, monkeypatch, changed):
    r, window, _, _ = runtime
    config._write_local_config({'dorcha': {'enabled': True, 'box': BOX}})
    r.target = TARGET
    box = {**BOX, 'x': BOX['x'] + 1} if changed else dict(BOX)
    candidate = state.Confirmation(box, state.epoch('dorcha'), TARGET)
    r.candidates['dorcha'] = candidate
    r.lost['dorcha'], r.failures['dorcha'] = 20, 2
    writes, reloads = [], []
    original = config._write_local_config
    monkeypatch.setattr(config, '_write_local_config', lambda raw: (writes.append(raw), original(raw))[1])
    window._reload_autofind_feature = reloads.append
    for i in range(4):
        r._accept(dict(kind='read',frame_id=i,delta=1), {'dorcha': True}, i, True, 1)
    assert len(writes) == int(changed)
    assert reloads == (['dorcha'] if changed else [])
    assert candidate.saved and candidate.changed == changed
    assert not r.candidates and r.lost['dorcha'] == r.failures['dorcha'] == 0


@pytest.mark.parametrize('key', ['buff', 'dorcha', 'tuarim'])
def test_unread_notice_visible_when_folded_and_cleared_on_recovery(runtime, key):
    from mabinogi_addon.ui.region_section import RegionSection
    r, window, _, _ = runtime
    region = RegionSection(QWidget(), unset_text='미리보기', parent=window)
    region.set_registered(True)
    tab = SimpleNamespace(region_section=region)
    setattr(window, 'buff_tab' if key == 'buff' else 'resource_tab', tab)
    window.show()
    region.show()
    r._accept(dict(kind='read', frame_id=1, delta=11), {key: False}, 12, False, 0)
    assert region.notice.isVisibleTo(window)
    assert not region.fold.isVisibleTo(window)
    assert '10초' in region.notice.text()
    region.set_summary('✓ 영역 지정됨 · 판독 대기')
    assert '10초' in region.notice.text()  # Periodic summary updates cannot erase it.
    r._accept(dict(kind='read', frame_id=2, delta=1), {key: True}, 13, False, 0)
    assert region.notice.isHidden() and not region.notice.text()
    assert key not in r.notified


def test_resource_notices_recover_independently(runtime):
    from mabinogi_addon.ui.region_section import RegionSection
    r, window, _, _ = runtime
    region = RegionSection(QWidget(), unset_text='미리보기', parent=window)
    window.resource_tab = SimpleNamespace(region_section=region)
    job = dict(kind='read', frame_id=1, delta=11)
    r._accept(job, {'dorcha': False, 'tuarim': False}, 12, False, 0)
    r._accept(job, {'dorcha': True}, 13, False, 0)
    assert '도르카' not in region.notice.text() and '투아림' in region.notice.text()


@pytest.mark.parametrize('change', ['automatic', 'region', 'disabled', 'target'])
def test_notice_invalidated_and_rearmed_on_setting_or_target_change(runtime, change):
    r, window, _, target = runtime
    raw = {'dorcha': {'enabled': True, 'box': BOX}, 'autofind': {'enabled': False}}
    config._write_local_config(raw)
    r.tick()
    finish(r)
    r._accept(dict(kind='read', frame_id=1, delta=11), {'dorcha': False}, 12, False, 0)
    assert 'dorcha' in r.notified
    if change == 'automatic': raw['autofind']['enabled'] = True
    elif change == 'region': raw['dorcha']['box'] = {**BOX, 'x': 99}
    elif change == 'disabled': raw['dorcha']['enabled'] = False
    else: target[0] = None
    config._write_local_config(raw)
    r.tick()
    assert not r.notified
    assert r.lost.get('dorcha', 0) == 0
    if r.future is not None: finish(r)
    if change == 'automatic':
        raw['autofind']['enabled'] = False
        config._write_local_config(raw)
        r.tick()
        if r.future is not None: finish(r)
        r._accept(dict(kind='read', frame_id=2, delta=5), {'dorcha': False}, 20, False, 0)
        assert not r.notified
        r._accept(dict(kind='read', frame_id=3, delta=6), {'dorcha': False}, 26, False, 0)
        assert r.notified == {'dorcha'}
