import json
import threading
import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from mabinogi_addon import config, feature_access, halo_capture as core, image_io
from test_navigation import window
from mabinogi_addon.ui.halo_capture_section import HaloCaptureSection
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget

native_target = HaloCaptureSection._foreground_target


@pytest.mark.parametrize('boss_id', [None, 'lenen_miir', 'petach'])
def test_timer_alone_never_arms_halo(window, monkeypatch, boss_id):
    section = window[0].boss_tab.halo_capture
    monkeypatch.setattr(config, 'load_discord_user', lambda: {'id': feature_access.CREATOR_DISCORD_ID})
    section.set_boss_context(boss_id)
    section._monitor(900)
    assert not section._clock.armed
    assert not section._warning.isVisible()


def test_identified_hoehan_arms_automatically_and_other_boss_resets(window, monkeypatch):
    import mabinogi_addon.ui.halo_capture_section as module
    section = window[0].boss_tab.halo_capture
    monkeypatch.setattr(config, 'load_discord_user', lambda: {'id': feature_access.CREATOR_DISCORD_ID})
    now = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    section._target = (11,22,0,0,1920,1080)
    for seconds, raw in [(0,900), (.5,900), (1,899)]:
        now[0] = 100 + seconds
        section.set_boss_context('lenen_miir_hoehan')
        section._monitor(raw)
    assert section._clock.anchor == (899,101)
    assert '감시 중' in section.state.text()
    warnings = []
    monkeypatch.setattr(section._warning, 'show_message', lambda *args: warnings.append(args))
    now[0] = 102
    section.set_boss_context('lenen_miir_hoehan')
    section._monitor(898)
    assert warnings == [('헤일로 5초 전', 5000)]
    section._monitor(898)
    assert len(warnings) == 1
    section.set_boss_context(None)
    section._monitor(898)
    assert not section._warning.isVisible()
    assert section._clock.last_remaining == 898
    assert section._countdown.isVisible()
    section.set_boss_context('lenen_miir')
    assert not section._clock.armed and section._clock.anchor is None


def test_stale_boss_context_cannot_arm_or_warn(window, monkeypatch):
    import mabinogi_addon.ui.halo_capture_section as module
    section = window[0].boss_tab.halo_capture
    now = [0.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    section.set_boss_context('lenen_miir_hoehan')
    now[0] = 2
    section._monitor(900)
    assert not section._clock.armed


def test_collection_records_raw_ocr_without_clock_substitution(tmp_path):
    session = core.CaptureSession(tmp_path)
    assert session.submit(np.zeros((10,20,3),np.uint8),
                          {'raw_time': None, 'read_status': 'observed'}, now=0)
    assert finish(session) == ''
    metadata = json.loads((session.path/'0001'/'metadata.json').read_text(encoding='utf-8'))
    assert metadata['raw_time'] is None and metadata['read_status'] == 'uncertain'


@pytest.fixture(autouse=True)
def game_boundary(monkeypatch):
    monkeypatch.setattr(HaloCaptureSection,'_foreground_target',lambda self:(11,22,0,0,1920,1080))


def finish(session):
    if session.thread is not None:
        session.thread.join(timeout=3)
        assert not session.thread.is_alive()
    return session.poll()


def test_lossless_unique_sessions_rate_and_change(tmp_path):
    frame = np.zeros((30,100,3),np.uint8)
    frame[4:20,20:30] = 255
    session = core.CaptureSession(tmp_path / '한글 수집')
    assert session.submit(frame,{'test':'샘플'},now=0)
    assert not session.submit(frame,{},now=.5,force=True)
    assert finish(session) == ''
    original = frame.copy()
    assert not session.submit(frame,{},now=1)
    frame[4:20,35:40] = 255
    assert session.submit(frame,{},now=1)
    assert finish(session) == ''
    assert session.count == 2
    assert np.array_equal(image_io.imread(session.path/'0001'/'frame.png'),original)
    assert np.array_equal(image_io.imread(session.path/'0002'/'frame.png'),frame)
    metadata = json.loads((session.path/'0001'/'metadata.json').read_text(encoding='utf-8'))
    assert metadata['raw_time'] is None and metadata['read_status'] == 'not_implemented'
    assert metadata['sequence'] == 1 and metadata['captured_at']
    other = core.CaptureSession(tmp_path / '한글 수집')
    assert other.path != session.path


def test_same_reading_ignores_background_change_and_changed_reading_saves(tmp_path):
    session = core.CaptureSession(tmp_path)
    frame = np.zeros((20,100,3),np.uint8)
    assert session.submit(frame, {'raw_time':881}, now=0)
    assert finish(session) == ''
    background = np.full_like(frame,255)
    assert not session.submit(background, {'raw_time':881}, now=1)
    assert session.submit(background, {'raw_time':880}, now=1)
    assert finish(session) == ''
    assert session.count == 2
    assert session.submit(frame, {'raw_time':None}, now=2)
    assert finish(session) == ''
    assert session.last_raw is None


@pytest.mark.parametrize('failure',['mkdir','png','metadata'])
def test_storage_failure_never_counts_or_overwrites(tmp_path,monkeypatch,failure):
    session = core.CaptureSession(tmp_path)
    frame = np.zeros((10,20,3),np.uint8)
    if failure == 'mkdir':
        def denied(*a,**k): raise PermissionError('controlled')
        monkeypatch.setattr(Path,'mkdir',denied)
    elif failure == 'png':
        monkeypatch.setattr(cv2,'imencode',lambda *a:(False,None))
    else:
        original = Path.write_bytes
        def write(path,data):
            if path.name == 'metadata.json': raise OSError('disk full')
            return original(path,data)
        monkeypatch.setattr(Path,'write_bytes',write)
    assert session.submit(frame,{},now=0)
    assert finish(session)
    assert session.count == session.bytes == 0
    assert not (session.path/'0001').exists()


def test_limits_and_cancellation(tmp_path,monkeypatch):
    frame = np.zeros((10,20,3),np.uint8)
    session = core.CaptureSession(tmp_path)
    monkeypatch.setattr(core,'MAX_SHOTS',1)
    assert session.submit(frame,{},now=0)
    assert finish(session) == ''
    with pytest.raises(ValueError): session.submit(frame,{},now=1,force=True)
    other = core.CaptureSession(tmp_path)
    monkeypatch.setattr(core,'MAX_BYTES',1)
    assert other.submit(frame,{},now=0)
    assert finish(other)
    assert other.count == other.bytes == 0
    other.stop()
    assert not other.submit(frame,{},now=2,force=True)


def test_creator_only_region_capture_and_stop(window,monkeypatch,tmp_path):
    w,app = window
    user = {'id':feature_access.CREATOR_DISCORD_ID}
    monkeypatch.setattr(config,'load_discord_user',lambda:user)
    section = w.boss_tab.halo_capture
    section._root = tmp_path / '수집'
    section._watcher = SimpleNamespace(is_game_active=lambda:True)
    frame = np.zeros((20,100,3),np.uint8)
    monkeypatch.setattr(section,'_grab',lambda *a:frame)
    before = config._read_local_config()
    section._save_region(0,0,100,20)
    w._open_setup_feature('boss')
    w.boss_tab.pattern_tabs.setCurrentIndex(1)
    section._tick()
    assert not section.isHidden() and not section.collect.isChecked()
    assert not section.preview.pixmap().isNull()
    section.collect.setChecked(True)
    section.set_boss_context('lenen_miir_hoehan')
    section._tick()
    session = section._session
    assert finish(session) == ''
    assert session.count == 1
    user.clear()  # 로그아웃: 수집(제작자)만 멈추고 1분 헤일로 화면·판독은 계속(2026-10-28 전체 공개)
    section._tick()
    assert not section.isHidden() and not section.collect.isChecked()
    assert session.cancelled.is_set()
    assert not section._timer.isActive()  # fixture stops owned timers before test
    after = config._read_local_config()
    assert {k:v for k,v in after.items() if k != 'haloTimer'} == {k:v for k,v in before.items() if k != 'haloTimer'}
    assert after['haloTimer'].get('enabled') == before.get('haloTimer',{}).get('enabled')
    assert (session.path/'0001'/'frame.png').exists()
    section.shutdown()
    assert not section._timer.isActive()


def test_capture_failure_and_region_change_do_not_mix_sessions(window,monkeypatch):
    w,_ = window
    monkeypatch.setattr(config,'load_discord_user',lambda:{'id':feature_access.CREATOR_DISCORD_ID})
    s = w.boss_tab.halo_capture
    s._watcher = SimpleNamespace(is_game_active=lambda:True)
    s._save_region(0,0,100,20)
    monkeypatch.setattr(s,'_grab',lambda *a:None)
    s.collect.setChecked(True)
    session = s._session
    s._tick()
    assert session.count == 0 and '대기' in s.state.text()
    s._save_region(10,10,100,20)
    assert not s.collect.isChecked() and session.cancelled.is_set()
    s.collect.setChecked(True)
    assert s._session.path != session.path
    s.shutdown()


def test_write_failure_stops_collection(window,monkeypatch):
    w,_ = window
    monkeypatch.setattr(config,'load_discord_user',lambda:{'id':feature_access.CREATOR_DISCORD_ID})
    s = w.boss_tab.halo_capture
    s._watcher = SimpleNamespace(is_game_active=lambda:True)
    s._save_region(0,0,100,20)
    monkeypatch.setattr(s,'_grab',lambda *a:np.zeros((20,100,3),np.uint8))
    monkeypatch.setattr(cv2,'imencode',lambda *a:(False,None))
    s.collect.setChecked(True)
    s.set_boss_context('lenen_miir_hoehan')
    s._tick()
    s._session.thread.join(timeout=3)
    s._tick()
    assert not s.collect.isChecked()
    assert s._session.count == 0
    assert '저장하지 못' in s.state.text()


def test_cancel_during_encode_has_no_queue_or_new_files(tmp_path,monkeypatch):
    entered,release = threading.Event(),threading.Event()
    original = cv2.imencode
    def encode(*args):
        entered.set()
        assert release.wait(timeout=3)
        return original(*args)
    monkeypatch.setattr(cv2,'imencode',encode)
    session = core.CaptureSession(tmp_path)
    frame = np.zeros((20,100,3),np.uint8)
    assert session.submit(frame,{},now=0)
    try:
        assert entered.wait(timeout=3)
        for n in range(1,20):
            assert not session.submit(frame,{},now=n,force=True)
        session.stop()
    finally:
        release.set()
    assert finish(session) == 'cancelled'
    assert session.count == 0 and not session.path.exists()


def test_twenty_writes_leave_no_worker_and_metadata_stays_paired(tmp_path):
    session = core.CaptureSession(tmp_path)
    for n in range(20):
        frame = np.full((10,20,3),n,np.uint8)
        assert session.submit(frame,{'sample':n},now=n,force=True)
        assert finish(session) == ''
        assert session.count == n+1
        target = session.path/f'{n+1:04d}'
        assert np.array_equal(image_io.imread(target/'frame.png'),frame)
        assert json.loads((target/'metadata.json').read_text(encoding='utf-8'))['sample'] == n
        assert session.thread is None


def test_logged_out_user_never_collects_saved_region(window,monkeypatch,tmp_path):
    # 2026-10-28 전체 공개: 미로그인도 1분 헤일로를 쓰지만(화면 보임) 수집은 하지 않는다
    w,_ = window
    monkeypatch.setattr(config,'load_discord_user',lambda:None)
    section = w.boss_tab.halo_capture
    section._root = tmp_path / '수집'
    section._region = dict(x=0,y=0,w=100,h=20)
    section._watcher = SimpleNamespace(is_game_active=lambda:True)
    monkeypatch.setattr(section,'_grab',lambda *a:np.zeros((20,100,3),np.uint8))
    section._tick()
    section._snapshot()
    section.collect.setChecked(True)
    assert not section.isHidden() and not section.collect.isChecked()
    assert section._session is None and not section._root.exists()


def test_outside_game_or_target_change_never_saves(window,monkeypatch):
    w,_ = window
    monkeypatch.setattr(config,'load_discord_user',lambda:{'id':feature_access.CREATOR_DISCORD_ID})
    s = w.boss_tab.halo_capture
    s._watcher = SimpleNamespace(is_game_active=lambda:True)
    s._save_region(0,0,100,20)
    s.set_boss_context('lenen_miir_hoehan')
    monkeypatch.setattr(s,'_foreground_target',lambda:(11,22,200,200,100,100))
    monkeypatch.setattr(s,'_grab',lambda *a:pytest.fail('outside game'))
    s._snapshot()
    assert s._session is None
    targets = iter([(11,22,0,0,1920,1080),None])
    monkeypatch.setattr(s,'_foreground_target',lambda:next(targets))
    monkeypatch.setattr(s,'_grab',lambda *a:np.zeros((20,100,3),np.uint8))
    s._snapshot()
    assert s._session is None


@pytest.mark.parametrize('boss_id', [None, 'lenen_miir', 'petach', 'lenen_miir_hoehan'])
def test_collection_requires_fresh_target_boss(window,monkeypatch,boss_id):
    import mabinogi_addon.ui.halo_capture_section as module
    s = window[0].boss_tab.halo_capture
    monkeypatch.setattr(config,'load_discord_user',lambda:{'id':feature_access.CREATOR_DISCORD_ID})
    s._save_region(0,0,100,20)
    now = [0.0]
    monkeypatch.setattr(module.time,'monotonic',lambda:now[0])
    s.set_boss_context(boss_id)
    if boss_id == 'lenen_miir_hoehan':
        now[0] = 2.0
    s._store(np.zeros((20,100,3),np.uint8))
    s._snapshot()
    assert s._session is None


@pytest.mark.parametrize('foreground,minimized,allowed',[(11,False,True),(99,False,False),(11,True,False)])
def test_native_target_requires_real_foreground_window(window,monkeypatch,foreground,minimized,allowed):
    from mabinogi_addon.system import window_capture
    target = (11,22,0,0,1920,1080)
    monkeypatch.setattr(window_capture,'registered_game_target',lambda *a:target)
    monkeypatch.setitem(sys.modules,'win32gui',SimpleNamespace(GetForegroundWindow=lambda:foreground,IsIconic=lambda hwnd:minimized))
    assert native_target(window[0].boss_tab.halo_capture) == (target if allowed else None)


@pytest.mark.parametrize('pixels',[12,20])
def test_creator_halo_layout_has_no_horizontal_scroll(window,monkeypatch,pixels):
    w,app = window
    monkeypatch.setattr(config,'load_discord_user',lambda:{'id':feature_access.CREATOR_DISCORD_ID})
    section = w.boss_tab.halo_capture
    section._refresh()
    section.disclosure.setChecked(True)
    w._open_setup_feature('boss')
    w.boss_tab.pattern_tabs.setCurrentIndex(1)
    for widget in w.boss_tab.findChildren(QWidget):
        font = QFont(widget.font())
        font.setPixelSize(pixels)
        widget.setFont(font)
    for _ in range(10): app.processEvents()
    scroll = w._combat_pages['boss']
    scroll.ensureWidgetVisible(section)
    assert scroll.horizontalScrollBar().maximum() == 0
    assert w.boss_tab.pattern_tabs.widget(1).horizontalScrollBar().maximum() == 0
    assert section.region_btn.isEnabled()


def test_third_tabs_follow_beta_access_without_resetting_settings(window,monkeypatch):
    w,app = window
    user = {'id':feature_access.CREATOR_DISCORD_ID}
    monkeypatch.setattr(config,'load_discord_user',lambda:user or None)
    boss = w.boss_tab
    tabs = boss.pattern_tabs
    before = config._read_local_config()
    boss.halo_capture._refresh()
    assert [tabs.tabText(i) for i in range(tabs.count())] == ['체력별 패턴','1분 헤일로']  # 0.25.0 띄어쓰기(앱 문구 명세 10절)
    assert tabs.isTabVisible(1)
    w._open_setup_feature('boss')
    for _ in range(10):
        tabs.setCurrentIndex(1)
        app.processEvents()
        assert boss.halo_capture.isVisible()
        tabs.setCurrentIndex(0)
        assert not boss.halo_capture.isVisible()
    tabs.setCurrentIndex(1)
    user['id'] = 'ordinary'
    boss.halo_capture._tick()
    assert tabs.isTabVisible(1)
    assert not boss.halo_capture.disclosure.isVisible()
    user.clear()  # 2026-10-28 전체 공개: 로그아웃해도 1분 헤일로 탭은 그대로
    boss.halo_capture._tick()
    assert tabs.isTabVisible(1)
    boss._apply_collect_gate()
    assert tabs.isTabVisible(1)
    assert config._read_local_config() == before
