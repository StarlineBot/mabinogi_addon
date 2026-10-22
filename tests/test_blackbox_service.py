from test_support.blackbox_codec import codec_tools
from pathlib import Path
from queue import Queue
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
    codec = CodecSettings(*codec_tools(), 'libx264',
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


def test_revoked_inflight_source_is_kept_while_running_and_cleaned_on_app_close(tmp_path):
    """실행 중에는 미완성 자료를 자동 삭제하지 않는다(복구 창에서 처리). 앱을 닫으면 원본 버퍼가
    사라져 쓸 수 없으므로 묻지 않고 지우며, 그 자료 때문에 종료가 막히지 않는다(2026-10-23 결정)."""
    access = [True]
    service = make_service(tmp_path, access)
    target = Target(1, 2, 3)
    service.tick(target, active=True)
    source = add_segment(service)
    path = service.spool._files[source].path
    access[0] = False
    service.tick(target, active=True)
    assert source in service.orphan_sources() and path.exists()
    assert service.prepare_close()
    assert not path.exists() and not service.spool.directory.exists()


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


def test_failed_save_is_cleaned_on_app_close_without_blocking(tmp_path):
    """저장 실패 자료가 있어도 앱 종료가 막히지 않고, 실패 partial은 지워진다(저장한 영상은 없음)."""
    service = make_service(tmp_path)
    def broken(plan, sink):
        sink.write(b'half')
        raise OSError('encoder exited 1: h264_mf failed')
    service.codec.encode = broken
    target = Target(1, 2, 3)
    service.tick(target, active=True)
    add_segment(service, 0, 100)
    token = service.request_save(75)
    service.producer.results.put(('flush', (token, 75)))
    service.tick(target, active=True)
    assert service.queue.wait_idle(5)
    ticket, = service.current.tickets
    assert service.current.queue.result(ticket).completed is False
    assert list(tmp_path.glob('.blackbox-*.partial'))  # 실행 중에는 재시도를 위해 보존
    close(service)
    assert not list(tmp_path.glob('.blackbox-*.partial')) and not list(tmp_path.glob('blackbox-*.mp4'))
    assert not service.spool.directory.exists() and service.budget.accounted_bytes == 0


def test_next_start_cleans_leftovers_from_previous_run(tmp_path):
    old = tmp_path / 'blackbox-oldrun'
    old.mkdir()
    (old / 'segment-1.partial').write_bytes(b'x')
    foreign = tmp_path / 'blackbox-foreign'
    foreign.mkdir()
    (foreign / 'notes.txt').write_text('keep')  # 우리가 만든 이름이 아니면 지우지 않는다
    (tmp_path / '.blackbox-abc.partial').write_bytes(b'y')
    (tmp_path / 'clip.mp4').write_bytes(b'saved')
    service = make_service(tmp_path)
    assert not old.exists() and not (tmp_path / '.blackbox-abc.partial').exists()
    assert (foreign / 'notes.txt').read_text() == 'keep' and (tmp_path / 'clip.mp4').exists()
    assert len(service.leftover_failures) == 2  # 알 수 없는 파일 + 그 폴더를 비우지 못함
    assert service.spool.directory.exists() and service.spool.directory != old
    close(service)
