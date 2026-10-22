import os
from threading import Event

import pytest

from mabinogi_addon.blackbox import BufferFullError, ReplayBuffer, Segment
from mabinogi_addon.blackbox_budget import BudgetError, DiskBudget
from mabinogi_addon.blackbox_export import ExportJob
from mabinogi_addon.blackbox_queue import ExportQueue, QueueFullError


def saved_plan():
    replay = ReplayBuffer('run', max_bytes=100, max_segments=10, max_saves=2)
    replay.append(Segment('run', 'source', 0, 10, 10, 'test'))
    return replay, replay.request_save(10)


def encode(plan, sink):
    sink.write(b'video')


def validate(path, plan):
    assert path.read_bytes() == b'video'


@pytest.fixture
def queues():
    created = []
    yield created
    for queue in created:
        queue.begin_close()
        for ticket in list(queue._entries):
            queue.cancel(ticket)
        assert queue.wait_idle(5), 'test adapter failed to stop'
        for ticket in list(queue._entries):
            queue.discard_partial(ticket)
            queue.acknowledge(ticket)
        assert queue.finish_close()


def make_queue(queues, *, slots=2, workers=1, total=100, access=lambda: True, free=lambda p: 1000):
    budget = DiskBudget(max_bytes=total, min_free_bytes=10, max_entries=10, disk_free=free)
    queue = ExportQueue(budget, max_workers=workers, max_jobs=slots, creator_check=access)
    queues.append(queue)
    return queue


def test_source_and_export_share_aggregate_budget_without_deleting_anything(tmp_path, queues):
    queue = make_queue(queues, total=15)
    source = tmp_path / 'source'
    source.write_bytes(b'12345')
    receipt = queue.budget.retain_existing(source)
    entered, finish = Event(), Event()
    replay, plan = saved_plan()
    def delayed(plan, sink):
        entered.set()
        assert finish.wait(5)
        encode(plan, sink)
    ticket = queue.submit(ExportJob(plan, tmp_path / 'clip', max_output_bytes=10), delayed, validate)
    try:
        assert entered.wait(5)
        assert queue.budget.accounted_bytes == 15
        with pytest.raises(BudgetError):
            queue.submit(ExportJob(plan, tmp_path / 'other', max_output_bytes=1), encode, validate)
        with pytest.raises(BufferFullError):
            replay.clear()
    finally:
        finish.set()
    assert queue.wait_idle(5)
    assert queue.result(ticket).completed
    assert queue.budget.accounted_bytes == 5
    assert source.read_bytes() == b'12345'
    queue.budget.release(receipt)
    assert source.exists()  # accounting is not file deletion


def test_access_revocation_and_close_do_not_cancel_accepted_work(tmp_path, queues):
    access = [True]
    queue = make_queue(queues, access=lambda: access[0])
    entered, finish = Event(), Event()
    replay, plan = saved_plan()
    def delayed(plan, sink):
        entered.set()
        assert finish.wait(5)
        encode(plan, sink)
    ticket = queue.submit(ExportJob(plan, tmp_path / 'clip', max_output_bytes=10), delayed, validate)
    try:
        assert entered.wait(5)
        access[0] = False
        queue.begin_close()
        with pytest.raises(PermissionError):
            queue.submit(ExportJob(plan, tmp_path / 'other', max_output_bytes=10), encode, validate)
        assert not queue.wait_idle(0)
        assert not queue.finish_close()
        assert queue.result(ticket) is None
    finally:
        finish.set()
    assert queue.wait_idle(5)
    assert queue.acknowledge(ticket).completed
    assert queue.finish_close()
    with pytest.raises(BufferFullError):
        replay.clear()  # result handoff does not release originals on worker thread
    replay.release_save(plan)


def test_queued_cancellation_never_runs_encoder(tmp_path, queues):
    queue = make_queue(queues)
    _, plan = saved_plan()
    entered, finish = Event(), Event()
    def delayed(plan, sink):
        entered.set()
        assert finish.wait(5)
        encode(plan, sink)
    first = queue.submit(ExportJob(plan, tmp_path / 'first', max_output_bytes=10), delayed, validate)
    try:
        assert entered.wait(5)
        def forbidden(*args):
            pytest.fail('cancelled queued encoder ran')
        second = queue.submit(ExportJob(plan, tmp_path / 'second', max_output_bytes=10), forbidden, validate)
        assert queue.cancel(second)
        assert queue.result(second) is None
    finally:
        finish.set()
    assert queue.wait_idle(5)
    assert queue.result(first).completed
    cancelled = queue.result(second)
    assert not cancelled.completed and 'ExportCancelled' in cancelled.error
    assert cancelled.partial is None and not (tmp_path / 'second').exists()


@pytest.mark.parametrize('stage', ['encode', 'validate'])
def test_running_cancellation_preserves_partial_until_explicit_cleanup(tmp_path, queues, stage):
    queue = make_queue(queues)
    _, plan = saved_plan()
    entered, finish = Event(), Event()
    def writer(plan, sink):
        encode(plan, sink)
        if stage == 'encode':
            entered.set()
            assert finish.wait(5)
            sink.check_cancelled()
    def checker(path, plan):
        validate(path, plan)
        if stage == 'validate':
            entered.set()
            assert finish.wait(5)
    ticket = queue.submit(ExportJob(plan, tmp_path / 'clip', max_output_bytes=10), writer, checker)
    try:
        assert entered.wait(5)
        queue.cancel(ticket)
        assert queue.result(ticket) is None  # cancellation request is not completed cancellation
        assert not queue.wait_idle(0)
    finally:
        finish.set()
    assert queue.wait_idle(5)
    result = queue.result(ticket)
    assert not result.completed and result.partial.read_bytes() == b'video'
    assert queue.budget.accounted_bytes == 5
    with pytest.raises(RuntimeError):
        queue.acknowledge(ticket)
    queue.discard_partial(ticket)
    assert queue.budget.accounted_bytes == 0
    assert not queue.acknowledge(ticket).completed


def test_cancel_after_atomic_commit_does_not_erase_success(tmp_path, queues, monkeypatch):
    queue = make_queue(queues)
    _, plan = saved_plan()
    entered, finish = Event(), Event()
    original = os.link
    def link(*args):
        original(*args)
        entered.set()
        assert finish.wait(5)
    monkeypatch.setattr(os, 'link', link)
    ticket = queue.submit(ExportJob(plan, tmp_path / 'clip', max_output_bytes=10), encode, validate)
    try:
        assert entered.wait(5)
        queue.cancel(ticket)
    finally:
        finish.set()
    assert queue.wait_idle(5)
    assert queue.result(ticket).completed
    assert (tmp_path / 'clip').read_bytes() == b'video'


def test_result_slots_remain_bounded_until_acknowledgement(tmp_path, queues):
    queue = make_queue(queues, slots=1)
    _, plan = saved_plan()
    job = ExportJob(plan, tmp_path / 'clip', max_output_bytes=10)
    ticket = queue.submit(job, encode, validate)
    assert queue.wait_idle(5)
    with pytest.raises(QueueFullError):
        queue.submit(ExportJob(plan, tmp_path / 'next', max_output_bytes=10), encode, validate)
    queue.acknowledge(ticket)
    with pytest.raises(ValueError):
        queue.submit(job, encode, validate)
    assert queue.budget.accounted_bytes == 0


def test_retry_accepted_save_after_access_revocation_uses_same_bytes(tmp_path, queues, monkeypatch):
    access = [True]
    queue = make_queue(queues, access=lambda: access[0])
    _, plan = saved_plan()
    with monkeypatch.context() as scoped:
        scoped.setattr(os, 'link', lambda *a: (_ for _ in ()).throw(OSError('temporary failure')))
        ticket = queue.submit(ExportJob(plan, tmp_path / 'clip', max_output_bytes=10), encode, validate)
        assert queue.wait_idle(5)
    assert queue.result(ticket).validated
    assert queue.budget.accounted_bytes == 5
    access[0] = False
    queue.begin_close()
    queue.retry_publish(ticket)
    assert queue.wait_idle(5)
    assert queue.result(ticket).completed
    assert queue.budget.accounted_bytes == 0


def test_cleanup_failure_keeps_result_and_budget(tmp_path, queues, monkeypatch):
    queue = make_queue(queues)
    _, plan = saved_plan()
    def fail(plan, sink):
        sink.write(b'bad')
        raise ValueError('encoding failed')
    ticket = queue.submit(ExportJob(plan, tmp_path / 'clip', max_output_bytes=10), fail, validate)
    assert queue.wait_idle(5)
    path = queue.result(ticket).partial
    with monkeypatch.context() as scoped:
        scoped.setattr(type(path), 'unlink', lambda *a: (_ for _ in ()).throw(PermissionError('busy')))
        with pytest.raises(PermissionError):
            queue.discard_partial(ticket)
    assert queue.budget.accounted_bytes == 3 and path.exists()
    with pytest.raises(RuntimeError):
        queue.acknowledge(ticket)


def test_worker_system_exit_is_reported_without_losing_partial(tmp_path, queues):
    queue = make_queue(queues)
    _, plan = saved_plan()
    def abort(plan, sink):
        sink.write(b'bad')
        raise SystemExit(7)
    ticket = queue.submit(ExportJob(plan, tmp_path / 'clip', max_output_bytes=10), abort, validate)
    assert queue.wait_idle(5)
    result = queue.result(ticket)
    assert not result.completed and 'SystemExit' in result.error
    assert result.partial.read_bytes() == b'bad'
    assert queue.budget.accounted_bytes == 3


def test_repeated_jobs_do_not_accumulate_entries(tmp_path, queues):
    queue = make_queue(queues)
    _, plan = saved_plan()
    for i in range(100):
        ticket = queue.submit(ExportJob(plan, tmp_path / f'clip-{i}', max_output_bytes=10), encode, validate)
        assert queue.wait_idle(5)
        assert queue.acknowledge(ticket).completed
        assert queue.budget.entry_count == 0 and queue.budget.accounted_bytes == 0


def test_free_space_and_reservations_fail_closed_without_deleting_clips(tmp_path):
    budget = DiskBudget(max_bytes=100, min_free_bytes=10, max_entries=3, disk_free=lambda p: 30)
    clip = tmp_path / 'permanent'
    clip.write_bytes(b'keep')
    token = budget.reserve(tmp_path, 20)
    with pytest.raises(BudgetError):
        budget.reserve(tmp_path, 1)
    assert budget.entry_count == 1 and budget.accounted_bytes == 20
    budget.settle(token, 5)
    second = budget.reserve(tmp_path, 20)
    assert budget.accounted_bytes == 25
    budget.release(second)
    budget.release(token)
    assert clip.read_bytes() == b'keep'


def test_existing_inode_and_zero_byte_files_count_toward_entry_bound(tmp_path):
    budget = DiskBudget(max_bytes=10, min_free_bytes=0, max_entries=1)
    source = tmp_path / 'source'
    source.touch()
    token = budget.retain_existing(source)
    with pytest.raises(BudgetError):
        budget.retain_existing(source)
    with pytest.raises(BudgetError):
        budget.reserve(tmp_path, 1)
    budget.release(token)


def test_oversized_settlement_records_actual_size_and_blocks_new_admission(tmp_path):
    budget = DiskBudget(max_bytes=10, min_free_bytes=0, max_entries=2)
    token = budget.reserve(tmp_path, 5)
    with pytest.raises(BudgetError):
        budget.settle(token, 12)
    assert budget.accounted_bytes == 12
    with pytest.raises(BudgetError):
        budget.reserve(tmp_path, 1)
    budget.release(token)


@pytest.mark.parametrize('free', [None, -1, True, float('inf')])
def test_unknown_disk_free_never_admits_work(tmp_path, free):
    budget = DiskBudget(max_bytes=10, min_free_bytes=0, max_entries=2, disk_free=lambda p: free)
    with pytest.raises(OSError):
        budget.reserve(tmp_path, 1)
    assert budget.entry_count == 0


def test_missing_partial_can_be_explicitly_discarded_but_missing_volume_cannot(tmp_path, queues):
    queue = make_queue(queues)
    _, plan = saved_plan()
    folder = tmp_path / 'output'
    folder.mkdir()
    def fail(plan, sink):
        sink.write(b'bad')
        raise ValueError('failed')
    ticket = queue.submit(ExportJob(plan, folder / 'clip', max_output_bytes=10), fail, validate)
    assert queue.wait_idle(5)
    partial = queue.result(ticket).partial
    moved = tmp_path / 'unmounted'
    folder.rename(moved)
    try:
        with pytest.raises(FileNotFoundError):
            queue.discard_partial(ticket)
        assert queue.budget.accounted_bytes == 3
    finally:
        moved.rename(folder)
    partial.unlink()
    queue.discard_partial(ticket)
    assert queue.budget.accounted_bytes == 0
    assert not queue.acknowledge(ticket).completed


def test_retry_rejects_job_already_waiting_on_another_ticket(tmp_path, queues):
    queue = make_queue(queues, slots=3, workers=1, total=100)
    _, plan = saved_plan()
    def fail(plan, sink):
        raise OSError('failed')
    first = queue.submit(ExportJob(plan, tmp_path / 'one', max_output_bytes=10), fail, validate)
    assert queue.wait_idle(5)
    started, release = Event(), Event()
    def block(plan, sink):
        started.set()
        assert release.wait(5)
        encode(plan, sink)
    try:
        queue.submit(ExportJob(plan, tmp_path / 'two', max_output_bytes=10), block, validate)
        assert started.wait(5)
        replacement = ExportJob(plan, tmp_path / 'three', max_output_bytes=10)
        queue.submit(replacement, encode, validate)
        before = queue.budget.accounted_bytes
        with pytest.raises(ValueError):
            queue.retry_encode(first, replacement, encode, validate)
        assert queue.budget.accounted_bytes == before
    finally:
        release.set()
        assert queue.wait_idle(5)
