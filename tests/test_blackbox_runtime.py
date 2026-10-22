from pathlib import Path
from threading import Event

import pytest

from mabinogi_addon.blackbox import ReplayBuffer, Segment
from mabinogi_addon.blackbox_budget import DiskBudget
from mabinogi_addon.blackbox_runtime import BlackboxRuntime
from mabinogi_addon.blackbox_session import BlackboxSession, CaptureContext
from mabinogi_addon.blackbox_spool import DiskSpool


def setup(tmp_path, encode=None):
    access = [True]
    budget = DiskBudget(max_bytes=1000, min_free_bytes=0, max_entries=20)
    spool = DiskSpool(tmp_path, budget)
    replay = ReplayBuffer('game', max_bytes=100, max_segments=10, max_saves=2, retention_us=10)
    session = BlackboxSession(replay, enabled=True, persist_enabled=lambda v: None,
                              creator_check=lambda: access[0])
    session.update_context(CaptureContext('game', foreground=True, ready=True))
    source = spool.write(lambda sink: sink.write(b'video'), max_bytes=10)
    session.append(session.capture_permit(), Segment('game', source, 0, 10, 5, 'test'))
    def default_encode(plan, sink):
        for part in plan.slices:
            sink.write(spool.resolve(part.segment.source).read_bytes())
    runtime = BlackboxRuntime(session, budget, max_output_bytes=20, encode=encode or default_encode,
                              validate=lambda p, plan: None, retire=spool.retire,
                              creator_check=lambda: access[0])
    return runtime, spool, budget, access


def test_two_requests_frozen_and_revoke_preserves_disk_sources(tmp_path):
    started, release = Event(), Event()
    def encode(plan, sink):
        started.set()
        assert release.wait(5)
        sink.write(b'saved')
    runtime, spool, budget, access = setup(tmp_path, encode)
    try:
        first = runtime.request_save(10, tmp_path / 'one')
        assert started.wait(5)
        second = runtime.request_save(10, tmp_path / 'two')
        with pytest.raises(RuntimeError):
            runtime.request_save(10, tmp_path / 'three')
        access[0] = False
        with pytest.raises(PermissionError):
            runtime.request_save(10, tmp_path / 'four')
        assert len(spool.sources) == 1
        runtime.begin_close()
        assert not runtime.finish_close()
    finally:
        release.set()
        assert runtime.queue.wait_idle(5)
    runtime.accept_completed(first)
    runtime.accept_completed(second)
    assert runtime.finish_close()
    spool.close()
    assert budget.accounted_bytes == 0
    assert (tmp_path / 'one').read_bytes() == (tmp_path / 'two').read_bytes() == b'saved'


def test_failed_export_explicit_discard_and_buffer_survives(tmp_path):
    def fail(plan, sink):
        sink.write(b'partial')
        raise OSError('encoder failed')
    runtime, spool, budget, access = setup(tmp_path, fail)
    ticket = runtime.request_save(10, tmp_path / 'saved')
    assert runtime.queue.wait_idle(5)
    partial = runtime.queue.result(ticket).partial
    assert partial.exists() and budget.accounted_bytes == 12
    access[0] = False
    runtime.discard_failed(ticket)
    assert not partial.exists() and len(spool.sources) == 1
    assert budget.accounted_bytes == 5
    runtime.begin_close()
    assert runtime.finish_close()
    spool.close()


def test_cleanup_failure_can_be_retried_without_losing_source(tmp_path, monkeypatch):
    runtime, spool, budget, _ = setup(tmp_path)
    runtime.begin_close()
    original = spool._owned
    monkeypatch.setattr(spool, '_owned', lambda r: (_ for _ in ()).throw(PermissionError('busy')))
    with pytest.raises(PermissionError):
        runtime.finish_close()
    assert budget.accounted_bytes == 5 and len(spool.sources) == 1
    monkeypatch.setattr(spool, '_owned', original)
    assert runtime.finish_close()
    spool.close()
    assert budget.accounted_bytes == 0


def test_spool_failed_and_replaced_sources_are_preserved(tmp_path):
    budget = DiskBudget(max_bytes=100, min_free_bytes=0, max_entries=5)
    spool = DiskSpool(tmp_path, budget)
    def fail(sink):
        sink.write(b'partial')
        raise OSError('fail')
    with pytest.raises(OSError):
        spool.write(fail, max_bytes=10)
    source, = spool.sources
    with pytest.raises(ValueError):
        spool.resolve(source)
    assert budget.accounted_bytes == 7
    spool.discard(source)
    source = spool.write(lambda sink: sink.write(b'original'), max_bytes=10)
    path = spool.resolve(source)
    moved = path.with_suffix('.old')
    path.rename(moved)
    path.write_bytes(b'foreign')
    with pytest.raises(OSError):
        spool.discard(source)
    assert path.read_bytes() == b'foreign' and budget.accounted_bytes == 8
    path.unlink()
    moved.rename(path)
    spool.discard(source)
    spool.close()


def test_missing_source_cleanup_and_unknown_file_protection(tmp_path):
    budget = DiskBudget(max_bytes=100, min_free_bytes=0, max_entries=5)
    spool = DiskSpool(tmp_path, budget)
    source = spool.write(lambda sink: sink.write(b'data'), max_bytes=10)
    spool.resolve(source).unlink()
    spool.discard(source)
    assert budget.accounted_bytes == 0
    foreign = spool.directory / 'foreign'
    foreign.write_bytes(b'keep')
    with pytest.raises(OSError):
        spool.close()
    assert foreign.read_bytes() == b'keep'


def test_reencode_retry_same_endpoint_after_access_revoked_preserves_old_partial(tmp_path):
    calls = []
    def encode(plan, sink):
        calls.append(plan)
        sink.write(b'video')
        if len(calls) == 1:
            raise OSError('first encoding failed')
    runtime, spool, budget, access = setup(tmp_path, encode)
    ticket = runtime.request_save(10, tmp_path / 'first')
    assert runtime.queue.wait_idle(5)
    old = runtime.queue.result(ticket).partial
    access[0] = False
    runtime.begin_close()
    runtime.retry_failed(ticket, tmp_path / 'retry')
    assert runtime.queue.wait_idle(5)
    assert old.exists() and calls[0] is calls[1]
    with pytest.raises(RuntimeError):
        runtime.accept_completed(ticket)
    runtime.queue.discard_partial(ticket)  # 명시적 이전 실패 자료 폐기, 성공 클립 유지
    runtime.accept_completed(ticket)
    assert runtime.finish_close()
    spool.close()
    assert budget.accounted_bytes == 0 and (tmp_path / 'retry').read_bytes() == b'video'


def test_success_result_survives_source_cleanup_failure(tmp_path, monkeypatch):
    runtime, spool, budget, _ = setup(tmp_path)
    ticket = runtime.request_save(10, tmp_path / 'saved')
    assert runtime.queue.wait_idle(5)
    newer = spool.write(lambda sink: sink.write(b'new'), max_bytes=10)
    runtime.session.append(runtime.session.capture_permit(), Segment('game', newer, 10, 20, 3, 'test'))
    original = spool.discard
    monkeypatch.setattr(spool, 'discard', lambda s: (_ for _ in ()).throw(PermissionError('busy')))
    result = runtime.accept_completed(ticket)
    assert result.completed and 'cleanup pending' in result.cleanup_error
    assert len(spool.sources) == 2
    monkeypatch.setattr(spool, 'discard', original)
    runtime.retry_cleanup()
    assert len(spool.sources) == 1
    runtime.begin_close()
    assert runtime.finish_close()
    spool.close()
