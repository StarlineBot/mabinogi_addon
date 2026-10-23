from test_support.blackbox_codec import codec_host, codec_tools
from pathlib import Path
import time

from mabinogi_addon.blackbox_codec import CodecSettings
from mabinogi_addon.blackbox_native import Target
from mabinogi_addon.blackbox_producer import ProducerLimits
from mabinogi_addon.blackbox_service import ServiceSettings, BlackboxService


class Native:
    def __init__(self, *args, **kwargs):
        rate = kwargs.get('audio_rate')
        self.audio = (rate, 1, 96000, 100) if rate else (None, None, None, None)
        self.audio_buffer_bytes = 100000 if rate else None
        self.frames = [(b'\x00\x00\xff\xff' * 16, 4, 4, 1000000 + n * 100000) for n in range(4)]
        self.sound = [(b'\x00\x00' * 48000, 1000000)] if rate else []
        self.closed = False
    def open(self, target):
        pass
    def read(self):
        return self.frames.pop(0) if self.frames else None
    def read_audio(self):
        return self.sound.pop(0) if self.sound else None
    def close(self):
        self.closed = True


def run_pipeline(tmp_path, audio):
    codec = CodecSettings(*codec_tools(), 'libx264',
                          100000, 10, 10, 50000, audio_bitrate=64000 if audio else None, host=codec_host())
    audio_settings = dict(audio_rate=48000, audio_channels=1, max_audio_bytes=96000,
                          activation_timeout_ms=100, audio_buffer_bytes=100000) if audio else None
    settings = ServiceSettings(tmp_path, tmp_path, tmp_path / 'test.dll', 1000000, 0, 20,
        100000, 10, 200000, ProducerLimits(2, 2, 64, 1024, 100000, 1000), codec, False, audio_settings)
    service = BlackboxService(settings, enabled=True, persist_enabled=lambda v: None,
                               allowed=lambda: True, native_factory=Native)
    target = Target(1, 2, 3)
    service.tick(target, active=True)
    producer = service.producer
    try:
        deadline = time.monotonic() + 5
        while producer.native.frames and time.monotonic() < deadline:
            time.sleep(.001)
        assert not producer.native.frames, 'synthetic frames were not delivered'
        service.request_save(1300000)
        deadline = time.monotonic() + 10
        saved = []
        while time.monotonic() < deadline:
            service.tick(target, active=True)
            saved = [r for kind, r in service.completed if kind == 'saved']
            if saved or service.error:
                break
            time.sleep(.01)
        assert not service.error, service.error
        assert saved and saved[0].completed
    finally:
        service.prepare_close()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            service.tick(None, active=False)
            if producer.is_stopped():
                break
            time.sleep(.01)
        assert producer.is_stopped(), producer.error
    assert service.prepare_close(), service.error
    assert service.budget.accounted_bytes == 0 and producer.native.closed
    assert saved[0].output.exists()


def test_video_pipeline_with_real_codec_and_fake_native(tmp_path):
    run_pipeline(tmp_path, False)


def test_game_pcm_pipeline_with_real_codec_and_fake_native(tmp_path):
    run_pipeline(tmp_path, True)


def _abi_capture(video=None, audio=None):
    """No OS calls: exercise the real ctypes consumer with bounded fake outputs."""
    import ctypes as C
    from types import SimpleNamespace
    from mabinogi_addon.system.blackbox_capture import NativeCapture
    capture = NativeCapture(Path('unused.dll'), max_frame_bytes=64, cursor=False,
        audio_rate=48000, audio_channels=2, max_audio_bytes=16,
        activation_timeout_ms=100, audio_buffer_bytes=64)
    capture._dll = SimpleNamespace(bb_read=video, bb_audio_read=audio)
    capture._video = C.c_void_p(1)
    capture._audio = C.c_void_p(2)
    capture._buffer = C.create_string_buffer(64)
    capture._audio_buffer = C.create_string_buffer(16)
    return capture


def test_native_capacity_failure_identifies_video_geometry_without_growing_buffer():
    import pytest
    def video(handle, output, capacity, width, height, stamp):
        width._obj.value, height._obj.value = 5, 4
        return -2147024774  # HRESULT_FROM_WIN32(ERROR_INSUFFICIENT_BUFFER)
    capture = _abi_capture(video=video)
    with pytest.raises(OSError, match='게임 영상 입력 5×4: 필요 80 bytes, 버퍼 한도 64 bytes'):
        capture.read()
    assert len(capture._buffer) == capture.limit == 64
    assert capture._buffer.raw == bytes(64)


def test_native_capacity_failure_identifies_audio_packet_without_growing_buffer():
    import pytest
    def audio(handle, output, capacity, size, stamp):
        size._obj.value = 20
        return -2147024774
    capture = _abi_capture(audio=audio)
    with pytest.raises(OSError, match='게임 오디오 패킷: 필요 20 bytes, 버퍼 한도 16 bytes'):
        capture.read_audio()
    assert len(capture._audio_buffer) == capture.audio[2] == 16
    assert capture._audio_buffer.raw == bytes(16)


def test_native_unknown_capacity_failure_does_not_invent_geometry():
    import pytest
    # Old DLLs and OS API failures may not provide any required size.
    capture = _abi_capture(video=lambda *args: -2147024774,
                           audio=lambda *args: -2147024774)
    for method, stage in ((capture.read, '게임 영상 읽기'), (capture.read_audio, '게임 오디오 읽기')):
        with pytest.raises(OSError, match=stage + ': HRESULT 0x8007007a'):
            method()


def test_native_read_empty_and_transition_remain_distinct_from_recording_error():
    import pytest
    from mabinogi_addon.system.blackbox_capture import NativeTransition
    capture = _abi_capture(video=lambda *args: 1, audio=lambda *args: 1)
    assert capture.read() is None
    assert capture.read_audio() is None
    for hr in (-2147024891, -2147023659):  # E_ACCESSDENIED, ERROR_RETRY
        capture._dll.bb_read = lambda *args: hr
        capture._dll.bb_audio_read = lambda *args: hr
        with pytest.raises(NativeTransition):
            capture.read()
        with pytest.raises(NativeTransition):
            capture.read_audio()


def test_native_read_success_checks_bounds_and_preserves_timestamps():
    import pytest
    def video(handle, output, capacity, width, height, stamp):
        width._obj.value, height._obj.value, stamp._obj.value = 4, 4, 123450
        return 0
    def audio(handle, output, capacity, size, stamp):
        size._obj.value, stamp._obj.value = 16, 123450
        return 0
    capture = _abi_capture(video=video, audio=audio)
    assert capture.read() == (bytes(64), 4, 4, 12345)
    assert capture.read_audio() == (bytes(16), 12345)
    def invalid_video(handle, output, capacity, width, height, stamp):
        width._obj.value, height._obj.value = 5, 4
        return 0
    def invalid_audio(handle, output, capacity, size, stamp):
        size._obj.value = 20
        return 0
    capture._dll.bb_read, capture._dll.bb_audio_read = invalid_video, invalid_audio
    with pytest.raises(OSError, match='invalid native frame bounds'):
        capture.read()
    with pytest.raises(OSError, match='invalid native audio bounds'):
        capture.read_audio()


# --- 0.11.2: 고해상도 게임 창은 GPU에서 1080p 안으로 축소 (사용자 결정 2026-10-23) ---------------
import pytest as _pytest


@_pytest.mark.parametrize('size, expected', [
    ((2560, 1440), (1920, 1080)),   # 사용자 제보 해상도
    ((3840, 2160), (1920, 1080)),   # 입력 상한
    ((1920, 1080), (1920, 1080)),   # 그대로
    ((1280, 720), (1280, 720)),     # 1080p 미만: 확대 없음
    ((3440, 1440), (1920, 802)),    # 21:9: 비율 유지, 짝수
    ((1600, 1200), (1440, 1080)),   # 4:3: 높이 기준
    ((1919, 1081), (1916, 1080)),   # 홀수 → 짝수
])
def test_fit_output_keeps_aspect_even_and_never_upscales(size, expected):
    from mabinogi_addon.system.blackbox_capture import fit_output
    out = fit_output(*size, 1920, 1080)
    assert out == expected
    assert out[0] <= 1920 and out[1] <= 1080
    if size != out:
        assert out[0] % 2 == 0 and out[1] % 2 == 0
        assert abs(out[0] / out[1] - size[0] / size[1]) < 0.01  # 왜곡 없음(검은 띠 없이 맞춤)


def _bounded_capture(video):
    import ctypes as C
    from types import SimpleNamespace
    from mabinogi_addon.system.blackbox_capture import NativeCapture
    capture = NativeCapture(Path('unused.dll'), max_frame_bytes=1920 * 1080 * 4, cursor=False,
                            max_output=(1920, 1080), max_input=(3840, 2160))
    capture._dll = SimpleNamespace(bb_read=video)
    capture._video = C.c_void_p(1)
    capture._buffer = C.create_string_buffer(64)
    return capture


def test_native_input_over_4k_and_gpu_scale_failure_stop_with_guidance():
    def too_large(handle, output, capacity, width, height, stamp):
        width._obj.value, height._obj.value = 5120, 2880
        return -2147024846  # HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED)
    with _pytest.raises(OSError, match='5120×2880은 블랙박스 최대 입력 3840×2160'):
        _bounded_capture(too_large).read()
    with _pytest.raises(OSError, match='GPU에서 게임 영상을 1920×1080 안으로 줄이지 못해.*CPU 축소로 대신하지 않아요'):
        _bounded_capture(lambda *a: -2147220991).read()  # 0x80040201


@_pytest.mark.parametrize('kwargs', [dict(max_output=(1920, 1080)), dict(max_input=(3840, 2160)),
                                     dict(max_output=(1920, 1080), max_input=(1280, 720)),
                                     dict(max_output=(3840, 2160), max_input=(3840, 2160))])
def test_native_bounds_must_be_explicit_pairs_within_frame_buffer(kwargs):
    from mabinogi_addon.system.blackbox_capture import NativeCapture
    with _pytest.raises(ValueError):
        NativeCapture(Path('unused.dll'), max_frame_bytes=1920 * 1080 * 4, cursor=False, **kwargs)


def test_python_and_native_use_the_same_open_abi_and_fit_formula():
    """Python이 부르는 내보내기 이름·인자 수와 DLL 정의가 어긋나면 실행 시에만 드러난다."""
    import re
    root = Path(__file__).resolve().parents[1]
    native = (root / 'native/blackbox/capture.cpp').read_text(encoding='utf-8')
    python = (root / 'src/mabinogi_addon/system/blackbox_capture.py').read_text(encoding='utf-8')
    signature = re.search(r'BB HRESULT __cdecl bb_open_fit\(([^)]*)\)', native, re.S)
    assert signature and len(signature.group(1).split(',')) == 9
    argtypes = re.search(r'bb_open_fit\.argtypes = \[([^\]]*)\]', python)
    assert argtypes and len(argtypes.group(1).split(',')) == 9
    assert 'bb_open(' not in native and 'dll.bb_open.' not in python
    # 축소 계산: 너비 기준 → 높이 초과 시 높이 기준, 짝수 내림(양쪽 동일).
    assert '(long long)h * max_w / w' in native and '(long long)w * max_h / h' in native
    assert 'height * max_width // width' in python and 'width * max_height // height' in python


def test_service_passes_product_output_and_input_bounds_to_native(tmp_path):
    from test_blackbox_service import make_service
    from mabinogi_addon.blackbox_producer import ProducerLimits
    from mabinogi_addon.system.blackbox_capture import Target
    import dataclasses
    service = make_service(tmp_path)
    calls = []
    service._native_factory = lambda *a, **k: calls.append(k) or object()
    service.settings = dataclasses.replace(service.settings, producer=ProducerLimits(
        2, 2, 1920 * 1080 * 4, 1920 * 1080 * 4 * 2 * 4, 10000, 1000, 1920, 1080, 3840, 2160))
    service.tick(Target(1, 2, 3), active=True)
    assert calls[0]['max_output'] == (1920, 1080) and calls[0]['max_input'] == (3840, 2160)
    service.producer.request_stop()


def test_encoder_crash_reports_exit_code_and_stderr_instead_of_broken_pipe(caplog):
    """0.11.2 실사용: 인코더가 먼저 죽으면 BrokenPipe만 보여 실제 원인이 가려졌다."""
    import io, sys, logging
    from mabinogi_addon.blackbox_codec import stream_process
    from mabinogi_addon.blackbox_export import ByteSink
    fake = [sys.executable, '-c', "import sys; sys.stderr.write('h264_mf: device init failed\\n'); sys.exit(1)"]
    frames = (bytes(1920 * 1080 * 4),) * 15
    caplog.set_level(logging.ERROR)
    for _ in range(3):
        with _pytest.raises(OSError) as caught:
            stream_process(fake, ByteSink(io.BytesIO(), 1 << 20), timeout=20, chunks=frames)
        assert not isinstance(caught.value, BrokenPipeError)
        assert 'encoder exited 1: h264_mf: device init failed' in str(caught.value)
    assert 'h264_mf: device init failed' in caplog.text


def _direct_producer(frames, codec_calls):
    """CaptureProducer를 가짜 장치·코덱으로 직접 돌린다(0.13.0 실사용 회귀)."""
    from types import SimpleNamespace
    from mabinogi_addon.blackbox_producer import CaptureProducer

    class Device:
        audio = (None, None)
        def __init__(self): self.frames = list(frames)
        def open(self, target): codec_calls.append('open')
        def read(self): return self.frames.pop(0) if self.frames else None
        def read_audio(self): return None
        def close(self): pass

    class Codec:
        settings = SimpleNamespace(fps=10, timeout=5)
        def encoder(self):
            codec_calls.append('probe')
            return 'h264_test'
        def encode_frames(self, frames, width, height, sink, audio_path=None):
            sink.write(b'x')

    class Spool:
        def __init__(self): self.n = 0
        def write(self, produce, max_bytes=None):
            import io
            self.n += 1; produce(io.BytesIO()); return str(self.n)
        def resolve(self, key):
            return SimpleNamespace(stat=lambda: SimpleNamespace(st_size=1))
        def discard(self, key): pass

    limits = ProducerLimits(3, 1, 64, 64 * 3 * 3, 1000, 50_000)
    return CaptureProducer(SimpleNamespace(session='s'), Device(), Codec(), Spool(), limits, allowed=lambda: True)


def test_frame_gap_starts_new_segment_instead_of_stopping_recording():
    # 0.13.0 실사용: 게임 끊김·인코딩 지연으로 프레임 시각이 허용 오차를 넘게 밀리면 녹화 전체가 중단됐다.
    frame = b'\x00' * 64
    stamps = [1_000_000 + n * 100_000 for n in range(3)] + [2_000_000 + n * 100_000 for n in range(3)]
    calls = []
    producer = _direct_producer([(frame, 4, 4, t) for t in stamps], calls)
    producer.start()
    segments = []
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and len(segments) < 2:
        while not producer.results.empty():
            kind, item = producer.results.get_nowait()
            if kind == 'segment': segments.append(item)
        time.sleep(.005)
    producer.request_stop()
    while not producer.is_stopped():
        while not producer.results.empty(): producer.results.get_nowait()
        time.sleep(.005)
    assert producer.error is None and producer.gaps == 1
    assert [(s.start_us, s.end_us) for s in segments] == [(1_000_000, 1_300_000), (2_000_000, 2_300_000)]
    assert calls[:2] == ['probe', 'open']  # 후보 시험 인코딩은 캡처 시작 전에


def test_app_bundled_tools_are_not_cpu_affinity_targets(monkeypatch):
    # 0.13.0 실사용: 7+1에서 앱의 ffmpeg·codec host가 백그라운드 1코어로 묶여 녹화가 밀렸다.
    import sys
    from mabinogi_addon.system.optimization import WindowsOptimization
    game = {'pid': 1, 'birth': '1'}
    base = dict(target={'pid': 456, 'birth': '2'}, same_user=True, same_session=True, protected=False)
    monkeypatch.setattr(sys, '_MEIPASS', 'C:/Users/me/AppData/Local/Temp/_MEI1234', raising=False)
    bundled = dict(base, name='ffmpeg.exe', path='C:/Users/me/AppData/Local/Temp/_MEI1234/blackbox/ffmpeg.exe')
    host = dict(base, name='blackbox_codec_host.exe', path='D:/dev/blackbox_codec_host.exe')
    other = dict(base, name='ffmpeg.exe', path='C:/Tools/ffmpeg.exe')  # 사용자가 따로 쓰는 ffmpeg는 대상
    assert not WindowsOptimization.background_candidate(bundled, game)
    assert not WindowsOptimization.background_candidate(host, game)
    assert WindowsOptimization.background_candidate(other, game)


def test_producer_error_is_logged_with_target_and_segment_count(caplog):
    # 0.13.0 실사용 로그 QA: 화면에만 보이던 생산자 오류를 app.log에 남긴다.
    frame = b'\x00' * 64
    calls = []
    producer = _direct_producer([(frame, 4, 4, 1_000_000), (frame, 4, 4, 900_000)], calls)  # 역순 프레임
    producer.start()
    deadline = time.monotonic() + 5
    while not producer.is_stopped() and time.monotonic() < deadline:
        producer.request_stop() if producer.error else None
        time.sleep(.005)
    assert 'out-of-order' in producer.error
    assert any('녹화 중단' in r.getMessage() and '완료 구간 0개' in r.getMessage() for r in caplog.records)


def test_audio_gap_starts_new_segment_instead_of_stopping_recording():
    # 0.13.1 실사용: 소리 묶음이 끊겼다 재개되면 'audio gap or overlap'으로 녹화가 멈춰 0초 저장이 됐다.
    # 50ms 소리 공백: 녹화는 계속하고, 소리가 연속인 프레임만 구간으로 만든다(공백은 무음으로 채우지 않음).
    from types import SimpleNamespace
    from mabinogi_addon.blackbox_producer import CaptureProducer
    frame = b'\x00' * 64
    sound = [(b'\x01\x00' * 100, 1_000_000 + n * 100_000) for n in range(3)]           # 1.00~1.30초
    sound += [(b'\x01\x00' * 100, 1_350_000 + n * 100_000) for n in range(5)]          # 1.35~1.85초
    video = [(frame, 4, 4, 1_000_000 + n * 100_000) for n in range(9)]                  # 1.0~1.8초

    class Device:
        audio = (1000, 1)
        audio_buffer_bytes = 1 << 16
        def __init__(self): self.video, self.sound = list(video), list(sound)
        def open(self, target): pass
        def read(self): return self.video.pop(0) if self.video else None
        def read_audio(self): return self.sound.pop(0) if self.sound else None
        def close(self): pass

    class Codec:
        settings = SimpleNamespace(fps=10, timeout=5)
        def encode_frames(self, frames, width, height, sink, audio_path=None): sink.write(b'x')

    class Spool:
        def __init__(self): self.n = 0
        def write(self, produce, max_bytes=None):
            import io
            self.n += 1; produce(io.BytesIO()); return str(self.n)
        def resolve(self, key): return SimpleNamespace(stat=lambda: SimpleNamespace(st_size=1))
        def discard(self, key): pass

    producer = CaptureProducer(SimpleNamespace(session='s'), Device(), Codec(), Spool(),
                               ProducerLimits(3, 1, 64, 64 * 3 * 3, 1000, 50_000), allowed=lambda: True)
    producer.start()
    deadline = time.monotonic() + 3
    while producer.native.video and time.monotonic() < deadline:
        time.sleep(.005)
    producer.request_stop()
    segments = []
    while not producer.is_stopped() or not producer.results.empty():
        while not producer.results.empty():
            kind, item = producer.results.get_nowait()
            if kind == 'segment': segments.append((item.start_us, item.end_us))
        time.sleep(.005)
    assert producer.error is None and producer.audio.gaps == 1
    assert segments == [(1_000_000, 1_300_000), (1_400_000, 1_600_000), (1_600_000, 1_800_000)]


def test_capture_keeps_reading_sound_while_waiting_for_full_queue():
    # 0.13.2 QA: 인코딩은 소리를 기다리고 캡처는 가득 찬 대기열에서 막혀 재개된 소리를 못 읽던 교착.
    import threading
    from types import SimpleNamespace
    from mabinogi_addon.blackbox_producer import CaptureProducer
    sound = [(b'\x01\x00' * 100, 1_000_000 + n * 100_000) for n in range(3)]

    class Device:
        audio = (1000, 1)
        audio_buffer_bytes = 1 << 16
        def read_audio(self): return sound.pop(0) if sound else None

    codec = SimpleNamespace(settings=SimpleNamespace(fps=10, timeout=5))
    producer = CaptureProducer(SimpleNamespace(session='s'), Device(), codec, None,
                               ProducerLimits(3, 1, 64, 64 * 3 * 3, 1000, 50_000), allowed=lambda: True)
    producer._batches.put('occupied')  # 인코딩 스레드가 아직 비우지 못한 대기열
    worker = threading.Thread(target=producer._put, args=(producer._batches, 'next'), kwargs=dict(pump=True))
    worker.start()
    deadline = time.monotonic() + 2
    while sound and time.monotonic() < deadline:
        time.sleep(.01)
    assert not sound and producer.audio.covered_end(1_300_000, timeout=.1) == 1_300_000
    producer._batches.get()
    worker.join(2)
    assert producer._batches.get_nowait() == 'next'


def test_sound_wait_is_bounded_and_uses_what_was_captured():
    # 0.13.2 QA: 게임 무음 동안 codec timeout(1200초)까지 오류 없이 멈춰 있지 않는다.
    from mabinogi_addon.blackbox_audio import PcmTimeline
    timeline = PcmTimeline(1000, 1, 1 << 16)
    timeline.push(b'\x01\x00' * 100, 1_000_000)
    started = time.monotonic()
    assert timeline.covered_end(1_500_000, timeout=.2, partial=True) == 1_100_000
    assert time.monotonic() - started < 1
    import pytest
    with pytest.raises(TimeoutError):
        timeline.covered_end(1_500_000, timeout=.05)
