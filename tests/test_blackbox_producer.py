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
