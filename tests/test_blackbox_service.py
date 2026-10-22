from pathlib import Path
from queue import Queue
import shutil
import time

import pytest

from mabinogi_addon.blackbox import Segment
from mabinogi_addon.blackbox_codec import CodecSettings
from mabinogi_addon.blackbox_native import Target
from mabinogi_addon.blackbox_producer import ProducerLimits
from mabinogi_addon.blackbox_service import ServiceSettings, BlackboxService


class Producer:
    def __init__(self, *args, **kwargs):
        self.results = Queue()
        self.error = None
        self.stop = False
        self.flushed = []
    def start(self):
        pass
    def request_stop(self):
        self.stop = True
    def is_stopped(self):
        return self.stop and self.results.empty()
    def request_flush(self, token, stamp):
        self.flushed.append((token, stamp))


def make_service(tmp_path, access=None):
    access = access if access is not None else [True]
    codec = CodecSettings(Path(shutil.which('ffmpeg')), Path(shutil.which('ffprobe')), 'libx264',
                          100000, 10, 10, 100000)
    settings = ServiceSettings(tmp_path, tmp_path, tmp_path / 'test.dll', 1000000, 0, 20,
        100000, 10, 200000, ProducerLimits(2, 2, 64, 1024, 10000, 1000), codec, False)
    service = BlackboxService(settings, enabled=True, persist_enabled=lambda v: None,
        allowed=lambda: access[0], producer_factory=Producer, native_factory=lambda *a, **k: object())
    service.codec.encode = lambda plan, sink: sink.write(b'video')
    service.codec.validate = lambda *a: None
    return service


def add_segment(service, start=0, end=100):
    source = service.spool.write(lambda sink: sink.write(b'video'), max_bytes=10)
    segment = Segment(service.current.session._replay.session, source, start, end, 5, 'test')
    service.producer.results.put(('segment', segment))
    return source


def close(service):
    service.prepare_close()
    service.tick(None, active=False)
    assert service.prepare_close()


def test_flush_preserves_original_request_end_and_shutdown_saved_file(tmp_path):
    service = make_service(tmp_path)
    target = Target(1, 2, 3)
    service.tick(target, active=True)
    add_segment(service, 0, 100)
    token = service.request_save(75)
    producer = service.producer
    producer.results.put(('flush', (token, 75)))
    service.tick(target, active=True)
    assert service.queue.wait_idle(5)
    ticket, = service.current.tickets
    assert service.current._plans[ticket].slices[-1].duration_us == 75
    service.tick(target, active=True)
    saved = [r for kind, r in service.completed if kind == 'saved']
    assert saved and saved[0].output.read_bytes() == b'video'
    close(service)
    assert saved[0].output.exists() and service.budget.accounted_bytes == 0


def test_restarts_share_queue_keep_prior_buffer_and_allow_older_save(tmp_path):
    service = make_service(tmp_path)
    one, two = Target(1, 2, 3), Target(4, 5, 6)
    service.tick(one, active=True)
    add_segment(service)
    service.tick(one, active=True)
    service.tick(two, active=True)
    assert len(service.runtimes) == 2
    old, new = service.runtimes.values()
    assert old.queue is new.queue and len(service.spool.sources) == 1
    ticket = service.request_saved_session(one.session, 100)
    assert service.queue.wait_idle(5)
    service.tick(two, active=True)
    assert ticket not in old.tickets
    close(service)


def test_revoked_inflight_source_is_recovery_not_automatically_deleted(tmp_path):
    access = [True]
    service = make_service(tmp_path, access)
    target = Target(1, 2, 3)
    service.tick(target, active=True)
    source = add_segment(service)
    access[0] = False
    service.tick(target, active=True)
    assert source in service.orphan_sources()
    assert not service.prepare_close()
    service.spool.discard(source)  # explicit discard after user decision
    assert service.prepare_close()


def test_profile_does_not_silently_disable_audio(tmp_path):
    with pytest.raises(ValueError, match='audio settings'):
        ServiceSettings.from_dict({'audio': 'process'})


def test_save_reserved_before_revoke_includes_only_requested_part(tmp_path):
    access = [True]
    service = make_service(tmp_path, access)
    target = Target(1, 2, 3)
    service.tick(target, active=True)
    assert service.status == 'preparing'
    service.tick(target, active=True)
    assert service.status == 'preparing'
    encoded_plans = []
    def encode(plan, sink):
        encoded_plans.append(plan)
        sink.write(b'video')
    service.codec.encode = encode
    # Runtime was created above; bind the observation to its actual export path.
    service.current._encode = encode
    token = service.request_save(75)
    access[0] = False
    add_segment(service, 0, 100)
    service.producer.results.put(('flush', (token, 999)))
    service.tick(target, active=True)
    assert service.queue.wait_idle(5)
    plan, = encoded_plans
    assert plan.request_us == 75 and plan.duration_us == 75
    assert len([value for kind, value in service.completed if kind == 'accepted']) == 1
    service.tick(target, active=False)
    close(service)
