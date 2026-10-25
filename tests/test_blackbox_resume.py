"""2026-10-25 블랙박스 저장 실패: 게임 재실행(대상 교체) 뒤 녹화가 재개되지 않고 '보관 중 5:00'으로 남음(0.17.2 app.log).

- 대상 교체 → NV12 상주 인코더 녹화가 새 대상으로 이어지는지(실제 CaptureProducer, 가짜 캡처·인코더)
- 멈추지 않는 생산자는 STOP_GRACE_S 뒤 버리고 새로 시작(스레드 스택을 app.log에)
- 새 구간이 없으면 '보관 중'으로 두지 않고(녹화 멈춤), 오래가면 다시 시작
- 저장 요청 실패를 app.log에 남김
"""
import logging
from pathlib import Path
import threading
import time
from types import SimpleNamespace as NS

import pytest

from mabinogi_addon import blackbox_service as service_module
from mabinogi_addon.blackbox_native import NativeTransition, Target
from mabinogi_addon.blackbox_producer import CaptureProducer
from mabinogi_addon.system.blackbox_capture import frame_bytes
from mabinogi_addon.ui.blackbox_controller import blackbox_badge
from test_blackbox_service import Producer, make_service
import test_blackbox_stream as stream_tests


class Clock:
    def __init__(self): self.now = 1000.0
    def __call__(self): return self.now


def _service(tmp_path, producer_factory=Producer, native_factory=None):
    service = make_service(tmp_path)
    service._producer_factory = producer_factory
    if native_factory is not None:
        service._native_factory = native_factory
    service._clock = Clock()
    return service


# ---- 대상 교체 뒤 재개(실제 생산자) ----

class GameCapture:
    """NV12 프레임을 10FPS 시각으로 계속 낸다. 대상이 바뀌면(게임 재실행) 캡처가 끊긴다(0x80070005)."""
    audio = (None, None)
    audio_buffer_bytes = 0

    def __init__(self, target, **kwargs):
        self.target, self.kwargs, self.n, self.closed = target, kwargs, 0, False
        self.changed = threading.Event()

    def open(self, target): self.t0 = time.perf_counter()

    def read(self):
        if self.changed.is_set():
            raise NativeTransition('capture target changed: 0x80070005')
        due = self.t0 + self.n / 10
        if time.perf_counter() < due:
            return None
        self.n += 1
        return bytes([self.n % 256]) * frame_bytes(4, 4, 'nv12'), 4, 4, int(due * 1e6), 'nv12'

    def read_audio(self): return None
    def close(self): self.closed = True


def test_game_restart_resumes_nv12_recording_on_new_target(tmp_path):
    captures, producers = [], []

    def native(*args, **kwargs):
        captures.append(GameCapture(None, **kwargs))
        return captures[-1]

    def producer(target, native, codec, spool, limits, *, allowed):
        from test_blackbox_cpu import FormatCodec
        producers.append(CaptureProducer(target, native, FormatCodec(), spool,
                                         stream_tests.ProducerLimits(3, 1, 64, 64 * 3 * 3, 1000, 50_000), allowed=allowed))
        return producers[-1]

    service = _service(tmp_path, producer, native)
    first, second = Target(1, 3544, 1), Target(2, 22676, 2)  # 2026-10-25 로그: pid 3544 → 22676

    def run(target, until, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not until():
            service.tick(target, active=True)
            time.sleep(0.02)
        return until()

    assert run(first, lambda: service.status == 'recording' and service.current.session._replay.available_us > 0)
    assert captures[0].kwargs['pixel_format'] == 'nv12'
    captures[0].changed.set()  # 게임 재실행
    assert run(second, lambda: len(producers) == 2 and service.status == 'recording'
               and service.current.session._replay.available_us > 0)
    assert producers[0].is_stopped() and captures[0].closed and service.abandoned == 0
    service._stop_producer(service._clock(), 'test')
    assert run(None, lambda: service.producer is None)


# ---- 멈추지 않는 생산자 ----

class StuckProducer(Producer):
    """멈춤 요청을 받아도 끝나지 않는다(캡처 종료·인코더 종료가 걸린 경우 모형)."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.release = threading.Event()
        self._capture = threading.Thread(target=self.release.wait, name='blackbox-window', daemon=True)
        self._capture.start()
    def is_stopped(self): return False


def test_producer_that_never_stops_is_replaced_and_its_stack_logged(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    made = []
    service = _service(tmp_path, lambda *a, **k: made.append(StuckProducer()) or made[-1])
    one, two = Target(1, 2, 3), Target(4, 5, 6)
    service.tick(one, active=True)
    stuck = made[0]
    service.tick(two, active=True)
    assert stuck.stop and service.producer is stuck  # 아직 기다린다
    service._clock.now += service_module.STOP_GRACE_S - 1
    service.tick(two, active=True)
    assert service.producer is stuck
    service._clock.now += 2
    service.tick(two, active=True)  # 버림
    service.tick(two, active=True)  # 새 대상으로 새 생산자
    assert service.abandoned == 1 and service.producer is made[1] and service._producer_target == two
    text = ' '.join(r.getMessage() for r in caplog.records)
    assert '멈추지 않아 새로 시작해요' in text and 'blackbox-window 실행 중' in text and 'wait' in text
    assert '녹화 멈춤 요청: 게임 대상 변경' in text
    stuck.release.set()


# ---- 새 구간이 없으면 '보관 중'으로 두지 않기 ----

def _recording(service):
    service.current.session.state = NS(value='recording')


def test_no_new_segments_is_not_shown_as_recording_and_restarts(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service = _service(tmp_path)
    target = Target(1, 2, 3)
    service.tick(target, active=True)
    from test_blackbox_service import add_segment
    add_segment(service, 0, 100)
    service.tick(target, active=True)
    assert service.status in ('recording', 'preparing')
    service._clock.now += service_module.STALL_STATUS_S + 1
    service.tick(target, active=True)
    if service.current.session.state.value == 'recording':
        assert service.status == 'stalled'
        assert blackbox_badge(NS(enabled=True, status='stalled')) == ('● 블랙박스: 녹화 멈춤', 'muted')
    assert not service.producer.stop
    service._clock.now += service_module.STALL_RESTART_S
    service.tick(target, active=True)
    assert service.producer.stop and '새 영상이' in caplog.text and '녹화 멈춤 요청: 새 영상 없음' in caplog.text


def test_stall_status_uses_session_recording_state(tmp_path):
    service = _service(tmp_path)
    target = Target(1, 2, 3)
    service.tick(target, active=True)
    real = service.current.session
    service.current.session = NS(state=NS(value='recording'), append=real.append, update_context=real.update_context,
                                 _replay=real._replay)
    service.tick(target, active=True)
    assert service.status == 'recording'
    service._clock.now += service_module.STALL_STATUS_S + 0.5
    service.tick(target, active=True)
    assert service.status == 'stalled'
    service.current.session = real


# ---- 저장 실패 로그 ----

def test_save_request_failure_is_written_to_app_log(caplog, monkeypatch):
    from mabinogi_addon.ui import blackbox_controller as module
    caplog.set_level(logging.WARNING)
    c = module.BlackboxController.__new__(module.BlackboxController)
    module.QObject.__init__(c)
    monkeypatch.setattr(module.feature_access, 'blackbox_available', lambda: True)
    reacted = []
    c.window, c.panel, c.events = NS(_closing=False), None, NS(foreground=True)
    c._react = lambda *a: reacted.append(a)
    def fail(stamp): raise RuntimeError('capture not recording')
    c.service = NS(request_save=fail, status='recording')
    target = NS(hwnd=7)
    c._hotkey_pressed((123, 7), target, True)
    assert '블랙박스 저장 요청 실패(단축키): RuntimeError: capture not recording · 상태 recording' in caplog.text
    assert c.close_error == 'capture not recording' and reacted
    c._last_target = target
    c._request_save(5)
    assert '블랙박스 저장 요청 실패(버튼)' in caplog.text


# ---- 네이티브 캡처 닫기가 돌아오지 않는 경우(bb_close 멈춤, 실제 생산자) ----

class HangingCapture(GameCapture):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.release = threading.Event()
    def close(self):
        self.release.wait()  # bb_close가 돌아오지 않음
        self.closed = True


def _real(tmp_path, capture_type):
    captures, producers = [], []

    def native(*args, **kwargs):
        captures.append(capture_type(None, **kwargs))
        return captures[-1]

    def producer(target, native, codec, spool, limits, *, allowed):
        from test_blackbox_cpu import FormatCodec
        producers.append(CaptureProducer(target, native, FormatCodec(), spool,
                                         stream_tests.ProducerLimits(3, 1, 64, 64 * 3 * 3, 1000, 50_000), allowed=allowed))
        return producers[-1]
    return _service(tmp_path, producer, native), captures, producers


def _until(service, target, predicate, timeout=5, step=0.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not predicate():
        service.tick(target, active=True)
        service._clock.now += step
        time.sleep(0.02)
    return predicate()


def test_hanging_native_close_does_not_block_resume_on_new_target(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, captures, producers = _real(tmp_path, HangingCapture)
    first, second = Target(1, 3544, 1), Target(2, 22676, 2)
    assert _until(service, first, lambda: service.status == 'recording')
    captures[0].changed.set()  # 게임 재실행 → 캡처 끊김 → 닫기가 멈춤
    assert _until(service, second, lambda: 'blackbox-window 실행 중' in caplog.text, step=1.0)
    assert not producers[0].is_stopped() and service.abandoned == 1
    assert '블랙박스 캡처 닫기 시작' in caplog.text and 'close' in caplog.text  # 스택에 멈춘 위치(close)
    assert _until(service, second, lambda: len(producers) == 2 and service.status == 'recording'
                  and service.current.session._replay.available_us > 0)
    assert producers[0]._capture.daemon  # 남은 스레드가 앱 종료를 막지 않음
    for capture in captures:
        capture.release.set()
    service._stop_producer(service._clock(), 'test')
    assert _until(service, None, lambda: service.producer is None)


def test_app_close_does_not_wait_forever_for_hanging_native_close(tmp_path):
    service, captures, producers = _real(tmp_path, HangingCapture)
    target = Target(1, 3544, 1)
    assert _until(service, target, lambda: service.status == 'recording')
    captures[0].changed.set()
    assert not service.prepare_close() and service.close_wait_reason() == 'capture'
    service._clock.now += service_module.CLOSE_GRACE_S - 1
    service.tick(target, active=True)
    assert service.producer is not None  # 상한 전에는 기다린다
    service._clock.now += 2
    service.tick(target, active=True)
    assert service.producer is None and service.close_wait_reason() is None
    assert service.prepare_close()  # 종료·업데이트 진행
    captures[0].release.set()


def test_native_close_is_logged_with_duration(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    service, captures, producers = _real(tmp_path, GameCapture)
    target = Target(1, 3544, 1)
    assert _until(service, target, lambda: service.status == 'recording')
    service._stop_producer(service._clock(), 'test')
    assert _until(service, target, lambda: service.producer is None or producers[0].is_stopped())
    assert '블랙박스 캡처 닫기 시작 · 정상 멈춤' in caplog.text and '블랙박스 캡처 닫기 끝' in caplog.text


def test_native_destructor_releases_gpu_objects_before_closing_session():
    native = (Path(__file__).resolve().parents[1] / 'native/blackbox/capture.cpp').read_text(encoding='utf-8')
    body = native[native.index('~Capture() {'):native.index('bool valid()')]
    assert body.index('context->Flush()') < body.index('scaler = Scaler{}') < body.index('session.Close()')
    assert body.index('session.Close()') < body.index('pool.Close()')
