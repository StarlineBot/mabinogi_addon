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
