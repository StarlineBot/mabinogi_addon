from dataclasses import replace

import pytest

from mabinogi_addon import config
from mabinogi_addon.blackbox import BufferFullError, ReplayBuffer, Segment
from mabinogi_addon.blackbox_session import BlackboxSession, CaptureContext, State


def make_session(*, creator=True, max_bytes=100, enabled=True, persist=None):
    access = [creator]
    replay = ReplayBuffer('run1', max_bytes=max_bytes, max_segments=10, max_saves=2)
    session = BlackboxSession(replay, enabled=enabled,
                              persist_enabled=persist or (lambda value: None),
                              creator_check=lambda: access[0])
    session.update_context(CaptureContext('run1', foreground=True, ready=True))
    return session, replay, access


def chunk(start=0, end=10):
    return Segment('run1', f'chunk-{start}', start, end, 10, 'test')


def test_preparing_is_not_recording_until_valid_segment_arrives():
    session, replay, _ = make_session()
    assert session.state == State.PREPARING
    permit = session.capture_permit()
    assert session.state == State.PREPARING
    session.append(permit, chunk())
    assert session.state == State.RECORDING
    assert replay.available_us == 10


@pytest.mark.parametrize('changes,state', [
    ({'session': None}, State.WAITING), ({'session': 'new-game-run'}, State.WAITING),
    ({'foreground': False}, State.PAUSED), ({'minimized': True}, State.PAUSED),
    ({'locked': True}, State.PAUSED), ({'suspended': True}, State.PAUSED),
    ({'ready': False}, State.PREPARING)])
def test_context_changes_stop_new_capture_keep_video_and_reject_late_results(changes, state):
    session, replay, _ = make_session()
    active = CaptureContext('run1', foreground=True, ready=True)
    permit = session.capture_permit()
    session.append(permit, chunk())
    session.update_context(replace(active, **changes))
    assert session.state == state
    assert session.enabled
    with pytest.raises(PermissionError):
        session.append(permit, chunk(10, 20))
    plan = session.request_save(20)
    assert plan.duration_us == 10
    session.update_context(active)
    with pytest.raises(PermissionError, match='stale'):
        session.append(permit, chunk(10, 20))
    session.append(session.capture_permit(), chunk(30, 40))
    assert replay.available_us == 20  # pause is not recording time


@pytest.mark.parametrize('access_value', [False, None, 'creator', 1])
def test_revoked_or_invalid_access_blocks_new_work_but_keeps_accepted_save(access_value):
    session, replay, access = make_session()
    permit = session.capture_permit()
    session.append(permit, chunk())
    plan = session.request_save(10)
    access[0] = access_value
    assert session.state == State.ACCESS_DENIED
    assert session.enabled
    with pytest.raises(PermissionError):
        session.request_save(20)
    with pytest.raises(PermissionError):
        session.append(permit, chunk(10, 20))
    session.begin_close()
    with pytest.raises(BufferFullError):
        session.finish_close()
    assert replay.retained_bytes == 10
    session.release_save(plan)
    assert session.finish_close() == (chunk(),)
    assert session.state == State.CLOSED
    assert session.enabled


def test_actual_feature_access_is_public_and_revocation_still_denies(monkeypatch):
    # 2026-10-28 기능 공개 정책 7절: 로그인하지 않아도 녹화·저장 가능(이전: 로그인 사용자만).
    user = [None]
    monkeypatch.setattr(config, 'load_discord_user', lambda: user[0])
    replay = ReplayBuffer('run1', max_bytes=10, max_segments=1, max_saves=1)
    session = BlackboxSession(replay, enabled=True, persist_enabled=lambda value: None)
    session.update_context(CaptureContext('run1', foreground=True, ready=True))
    session.capture_permit()  # 미로그인도 허용
    allowed = [True]  # 접근 판정이 거부로 바뀌는 경로는 그대로 막는다
    revocable = BlackboxSession(ReplayBuffer('run2', max_bytes=10, max_segments=1, max_saves=1), enabled=True,
                                persist_enabled=lambda value: None, creator_check=lambda: allowed[0])
    revocable.update_context(CaptureContext('run2', foreground=True, ready=True))
    revocable.capture_permit()
    allowed[0] = False
    with pytest.raises(PermissionError):
        revocable.capture_permit()
    with pytest.raises(PermissionError):
        revocable.request_save(0)


def test_capture_continues_during_save_and_plan_keeps_original_end():
    session, replay, _ = make_session()
    permit = session.capture_permit()
    session.append(permit, chunk())
    plan = session.request_save(10)
    session.append(permit, chunk(10, 20))
    assert plan.duration_us == 10
    assert plan.slices[-1].segment.end_us == 10
    assert replay.available_us == 20
    assert session.state == State.RECORDING


def test_disable_and_game_exit_preserve_save_opportunity_until_app_close():
    saved = []
    session, replay, _ = make_session(persist=saved.append)
    permit = session.capture_permit()
    session.append(permit, chunk())
    session.set_enabled(False)
    session.update_context(CaptureContext())
    assert session.state == State.DISABLED
    assert saved == [False]
    plan = session.request_save(20)
    with pytest.raises(PermissionError):
        session.append(permit, chunk(20, 30))
    session.begin_close()
    with pytest.raises(PermissionError):
        session.request_save(20)
    with pytest.raises(BufferFullError):
        session.finish_close()
    session.release_save(plan)
    assert session.finish_close() == (chunk(),)
    assert replay.retained_bytes == 0
    assert not session.enabled


def test_capacity_error_is_visible_preserves_enabled_and_requires_explicit_recovery():
    session, replay, _ = make_session(max_bytes=10)
    permit = session.capture_permit()
    session.append(permit, chunk())
    plan = session.request_save(10)
    with pytest.raises(BufferFullError):
        session.append(permit, chunk(10, 20))
    assert session.state == State.ERROR
    assert session.error and session.enabled
    with pytest.raises(PermissionError):
        session.capture_permit()
    session.release_save(plan)
    session.acknowledge_recovery()
    assert session.state == State.PREPARING
    session.append(session.capture_permit(), chunk(10, 20))
    assert session.state == State.RECORDING


def test_failed_persistence_does_not_change_enabled_or_permit():
    def fail(value):
        raise OSError('disk full')
    session, _, _ = make_session(persist=fail)
    permit = session.capture_permit()
    with pytest.raises(OSError):
        session.set_enabled(False)
    assert session.enabled
    assert session.capture_permit() is permit


def test_persisted_enabled_restarts_with_empty_video_and_waits_for_valid_target(tmp_path):
    path = tmp_path / 'config.json'
    config._write_local_config({'other': {'value': 42}, 'blackbox': {'future': 1}}, path)
    persist = lambda value: config.save_blackbox_enabled(value, path)
    session, _, _ = make_session(enabled=config.load_blackbox_enabled(path), persist=persist)
    assert session.state == State.DISABLED
    session.set_enabled(True)
    session.append(session.capture_permit(), chunk())
    session.begin_close()
    session.finish_close()
    assert config.load_blackbox_enabled(path)
    replay = ReplayBuffer('new-app-run', max_bytes=10, max_segments=1, max_saves=1)
    restarted = BlackboxSession(replay, enabled=config.load_blackbox_enabled(path),
                                persist_enabled=persist, creator_check=lambda: True)
    assert restarted.state == State.WAITING
    assert replay.available_us == 0
    restarted.set_enabled(False)
    assert not config.load_blackbox_enabled(path)
    assert config._read_local_config(path) == {
        'other': {'value': 42}, 'blackbox': {'future': 1, 'enabled': False}}


@pytest.mark.parametrize('value', [None, True, 'true', {'enabled': 'true'}, {'enabled': 1}])
def test_corrupt_settings_never_auto_enable(tmp_path, value):
    path = tmp_path / 'config.json'
    config._write_local_config({'blackbox': value}, path)
    assert not config.load_blackbox_enabled(path)


def test_access_lookup_exception_fails_closed():
    session, _, _ = make_session()
    def fail():
        raise OSError('unavailable')
    session._creator_check = fail
    assert session.state == State.ACCESS_DENIED
    with pytest.raises(PermissionError):
        session.request_save(0)


def test_late_worker_error_cannot_poison_resumed_capture_or_closed_session():
    session, _, _ = make_session()
    old = session.capture_permit()
    session.append(old, chunk())
    session.update_context(CaptureContext())
    session.update_context(CaptureContext('run1', foreground=True, ready=True))
    current = session.capture_permit()
    session.append(current, chunk(20, 30))
    assert not session.report_error(old, 'old worker failed')
    assert session.state == State.RECORDING
    assert session.error is None
    assert session.report_error(current, 'current worker failed')
    assert session.state == State.ERROR
    session.acknowledge_recovery()
    current = session.capture_permit()
    session.begin_close()
    assert not session.report_error(current, 'shutdown callback')
    assert session.error is None
