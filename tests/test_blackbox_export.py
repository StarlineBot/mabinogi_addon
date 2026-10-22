from dataclasses import replace
import os
from pathlib import Path
from threading import Event, Thread

import pytest

from mabinogi_addon.blackbox import BufferFullError, ReplayBuffer, Segment
from mabinogi_addon.blackbox_export import ExportJob


def plan():
    replay = ReplayBuffer('run', max_bytes=100, max_segments=10, max_saves=2)
    replay.append(Segment('run', 'source', 0, 10, 10, 'test'))
    return replay, replay.request_save(10)


def encode(plan, sink):
    sink.write(b'complete-test-video')


def validate(path, plan):
    assert path.read_bytes() == b'complete-test-video'


def test_publish_only_after_validation_preserves_pins_and_final_clip(tmp_path):
    replay, saved = plan()
    output = tmp_path / 'clip.bin'
    job = ExportJob(saved, output, max_output_bytes=100)
    def check(path, request):
        assert not output.exists()
        validate(path, request)
    result = job.run(encode, check)
    assert result.completed and result.validated
    assert result.partial is None and result.output == output
    assert output.read_bytes() == b'complete-test-video'
    with pytest.raises(BufferFullError):
        replay.clear()  # only the control thread may release the plan
    replay.release_save(saved)
    replay.clear()
    job.discard_partial()
    assert output.read_bytes() == b'complete-test-video'
    with pytest.raises(RuntimeError):
        job.run(encode, validate)


def test_existing_destination_is_never_overwritten(tmp_path):
    _, saved = plan()
    output = tmp_path / 'clip.bin'
    output.write_bytes(b'existing')
    def forbidden(*args):
        pytest.fail('encoding must not start')
    result = ExportJob(saved, output, max_output_bytes=100).run(forbidden, forbidden)
    assert not result.completed and result.partial is None
    assert output.read_bytes() == b'existing'


def test_destination_collision_during_encode_keeps_verified_partial_for_retry(tmp_path):
    _, saved = plan()
    output = tmp_path / 'clip.bin'
    job = ExportJob(saved, output, max_output_bytes=100)
    def race(plan, sink):
        encode(plan, sink)
        output.write_bytes(b'other export won')
    result = job.run(race, validate)
    assert not result.completed and result.validated
    assert result.partial.read_bytes() == b'complete-test-video'
    assert output.read_bytes() == b'other export won'
    retry = job.retry_publish(tmp_path / 'retry.bin')
    assert retry.completed
    assert retry.output.read_bytes() == b'complete-test-video'
    assert not result.partial.exists()
    assert output.read_bytes() == b'other export won'


@pytest.mark.parametrize('failure', ['encode', 'validate', 'empty', 'limit', 'fsync', 'link'])
def test_failures_preserve_recovery_material_and_never_create_success(tmp_path, monkeypatch, failure):
    replay, saved = plan()
    output = tmp_path / 'clip.bin'
    job = ExportJob(saved, output, max_output_bytes=20)
    def write(plan, sink):
        if failure == 'empty':
            return
        sink.write(b'partial')
        if failure == 'encode':
            raise TimeoutError('encoder timed out')
        if failure == 'limit':
            sink.write(b'x' * 21)
        else:
            sink.write(b'-data')
    def check(path, plan):
        if failure == 'validate':
            raise ValueError('undecodable')
    def io_failure(*args):
        raise OSError('disk or filesystem failure')
    if failure in ('fsync', 'link'):
        monkeypatch.setattr(os, failure, io_failure)
    result = job.run(write, check)
    assert not result.completed and result.error
    assert not output.exists()
    assert result.partial.is_file()
    assert result.partial.stat().st_size <= 20
    assert result.validated is (failure == 'link')
    with pytest.raises(BufferFullError):
        replay.clear()
    if not result.validated:
        with pytest.raises(ValueError):
            job.retry_publish()
    job.discard_partial()
    assert not result.partial.exists()


def test_publish_cleanup_failure_is_completed_with_explicit_leftover(tmp_path, monkeypatch):
    _, saved = plan()
    job = ExportJob(saved, tmp_path / 'clip.bin', max_output_bytes=100)
    original = Path.unlink
    def fail_partial(path, *args, **kwargs):
        if path.suffix == '.partial':
            raise PermissionError('cleanup denied')
        return original(path, *args, **kwargs)
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, 'unlink', fail_partial)
        result = job.run(encode, validate)
    assert result.completed and result.cleanup_error
    assert result.partial.is_file() and result.output.is_file()
    job.discard_partial()
    assert result.output.read_bytes() == b'complete-test-video'


def test_changed_validated_partial_cannot_be_published(tmp_path, monkeypatch):
    _, saved = plan()
    job = ExportJob(saved, tmp_path / 'clip.bin', max_output_bytes=100)
    with monkeypatch.context() as scoped:
        scoped.setattr(os, 'link', lambda *a: (_ for _ in ()).throw(OSError('unavailable')))
        result = job.run(encode, validate)
    result.partial.write_bytes(b'changed')
    retry = job.retry_publish()
    assert not retry.completed and not retry.validated
    assert not job.output.exists()


def test_replaced_partial_is_not_deleted_or_retried(tmp_path, monkeypatch):
    _, saved = plan()
    job = ExportJob(saved, tmp_path / 'clip.bin', max_output_bytes=100)
    with monkeypatch.context() as scoped:
        scoped.setattr(os, 'link', lambda *a: (_ for _ in ()).throw(OSError('unavailable')))
        result = job.run(encode, validate)
    foreign = tmp_path / 'foreign'
    foreign.write_bytes(b'foreign')
    os.replace(foreign, result.partial)
    retry = job.retry_publish()
    assert not retry.completed and not retry.validated
    with pytest.raises(OSError):
        job.discard_partial()
    assert result.partial.read_bytes() == b'foreign'


def test_same_job_concurrent_run_and_cleanup_are_rejected(tmp_path):
    _, saved = plan()
    job = ExportJob(saved, tmp_path / 'clip.bin', max_output_bytes=100)
    started, finish = Event(), Event()
    results = []
    def delayed(plan, sink):
        started.set()
        assert finish.wait(5)
        encode(plan, sink)
    thread = Thread(target=lambda: results.append(job.run(delayed, validate)))
    thread.start()
    try:
        assert started.wait(5)
        with pytest.raises(RuntimeError):
            job.run(encode, validate)
        with pytest.raises(RuntimeError):
            job.discard_partial()
        with pytest.raises(RuntimeError):
            job.retry_publish()
    finally:
        finish.set()
        thread.join(5)
    assert not thread.is_alive() and results[0].completed


@pytest.mark.parametrize('limit', [0, -1, True, float('inf')])
def test_invalid_limit_rejected(tmp_path, limit):
    _, saved = plan()
    with pytest.raises(ValueError):
        ExportJob(saved, tmp_path / 'clip', max_output_bytes=limit)


def test_invalid_plan_rejected_before_creating_files(tmp_path):
    before = set(tmp_path.iterdir())  # 공통 fixture가 만든 격리 앱 디렉터리는 보존
    _, saved = plan()
    for bad in (replace(saved, slices=()), replace(saved, request_us=0),
                replace(saved, slices=(replace(saved.slices[0], duration_us=11),))):
        with pytest.raises(ValueError):
            ExportJob(bad, tmp_path / 'clip', max_output_bytes=100)
    assert set(tmp_path.iterdir()) == before


@pytest.mark.parametrize('variant', ['memoryview', 'subclass'])
def test_nonbyte_memoryview_cannot_bypass_output_limit(tmp_path, variant):
    from array import array
    class MisleadingBytes(bytes):
        def __len__(self):
            return 1
    _, saved = plan()
    job = ExportJob(saved, tmp_path / 'clip.bin', max_output_bytes=2)
    def wrong_type(plan, sink):
        data = memoryview(array('I', [123])) if variant == 'memoryview' else MisleadingBytes(b'12345')
        sink.write(data)
    result = job.run(wrong_type, lambda *args: pytest.fail('must not validate'))
    assert not result.completed and not result.validated
    assert result.partial.stat().st_size == 0


def test_cancel_during_fsync_never_starts_validation(tmp_path, monkeypatch):
    from threading import Event
    _, saved = plan()
    cancel = Event()
    original = os.fsync
    def sync(fd):
        original(fd)
        cancel.set()
    monkeypatch.setattr(os, 'fsync', sync)
    job = ExportJob(saved, tmp_path / 'clip', max_output_bytes=100)
    def forbidden(*args):
        pytest.fail('validation started after cancellation')
    result = job.run(encode, forbidden, cancel=cancel)
    assert not result.completed and 'ExportCancelled' in result.error


def test_accepted_job_limits_and_plan_are_readonly(tmp_path):
    _, saved = plan()
    job = ExportJob(saved, tmp_path / 'clip', max_output_bytes=100)
    for name, value in [('max_output_bytes', 10000), ('output', tmp_path / 'other'), ('plan', None)]:
        with pytest.raises(AttributeError):
            setattr(job, name, value)
    assert job.max_output_bytes == 100 and job.plan is saved
