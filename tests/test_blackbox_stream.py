"""0.15.0 블랙박스 상주 인코더: fMP4 조각 분할, 실제 ffmpeg 조각 단독·이어 붙여 재생, 생산자 재시작·저장 요청·오류 경로."""
from test_support.blackbox_codec import codec_host, codec_tools
import io
import logging
import struct
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from mabinogi_addon import blackbox_producer
from mabinogi_addon.blackbox import Segment, SavePlan, Slice
from mabinogi_addon.blackbox_codec import CodecSettings, EncoderStream, FFmpegEncoder
from mabinogi_addon.blackbox_export import ByteSink
from mabinogi_addon.blackbox_fmp4 import FragmentSplitter, rebase_fragment
from mabinogi_addon.blackbox_producer import CaptureProducer, ProducerLimits


def box(kind, payload=b''):
    return struct.pack('>I4s', 8 + len(payload), kind) + payload


def moof(base, samples, version=1):
    tfdt = box(b'tfdt', bytes([version, 0, 0, 0]) + (struct.pack('>Q', base) if version else struct.pack('>I', base)))
    trun = box(b'trun', bytes(4) + struct.pack('>I', samples))
    return box(b'moof', box(b'mfhd', bytes(8)) + box(b'traf', box(b'tfhd', bytes(8)) + tfdt + trun))


def test_splitter_cuts_fragments_byte_by_byte_and_rebases_start_to_zero():
    init = box(b'ftyp', b'isom') + box(b'moov', b'm' * 20)
    stream = init + moof(0, 15) + box(b'mdat', b'a' * 30) + moof(3840, 15, 0) + box(b'mdat', b'b' * 7) + box(b'mfra', b'z')
    splitter, out = FragmentSplitter(), []
    for n in range(len(stream)):
        out += splitter.feed(stream[n:n + 1])
    assert [frames for _, frames in out] == [15, 15] and splitter.pending == 0
    second = out[1][0]
    assert second.startswith(init) and second.endswith(box(b'mdat', b'b' * 7))
    assert second == init + moof(0, 15, 0) + box(b'mdat', b'b' * 7)  # tfdt 3840 → 0


def test_splitter_largesize_box_and_truncated_output_is_reported_as_pending():
    init = box(b'ftyp') + box(b'moov')
    large = struct.pack('>I4sQ', 1, b'mdat', 16 + 5) + b'12345'
    splitter = FragmentSplitter()
    assert [n for _, n in splitter.feed(init + moof(7, 3) + large)] == [3]
    splitter.feed(moof(9, 3)[:-4])
    assert splitter.pending > 0  # 조각 중간에서 끝남 → EncoderStream.finish가 오류로 본다


@pytest.mark.parametrize('stream, message', [
    (moof(0, 1), 'moov 전에'),
    (box(b'ftyp') + box(b'moov') + box(b'mdat', b'x'), 'moof 없는'),
    (box(b'ftyp') + box(b'moov') + moof(0, 1) + moof(0, 1), 'mdat 없이'),
])
def test_splitter_rejects_out_of_order_boxes(stream, message):
    with pytest.raises(ValueError, match=message):
        FragmentSplitter().feed(stream)


def test_rebase_requires_timing_boxes():
    with pytest.raises(ValueError):
        rebase_fragment(bytearray(box(b'moof', box(b'mfhd', bytes(8)))))


def _settings(fps=60, gop_bitrate=500000):
    return CodecSettings(*codec_tools(), 'libx264', gop_bitrate, fps, 30, 50000, host=codec_host())


def test_real_ffmpeg_stream_fragments_play_alone_and_concat_like_old_segments(tmp_path):
    settings = _settings()
    paths = {}
    encoder = FFmpegEncoder(settings, lambda key: paths[key])
    red, blue, green = (bytes(c) * (64 * 48) for c in ((0, 0, 255, 255), (255, 0, 0, 255), (0, 255, 0, 255)))
    fragments = []
    stream = encoder.open_stream(64, 48, 15, lambda data, frames: fragments.append((data, frames)))
    for frame in [red] * 15 + [blue] * 15 + [green] * 10:
        stream.write(frame)
    stream.finish(30)
    assert [frames for _, frames in fragments] == [15, 15, 10]
    segments = []
    for n, (data, frames) in enumerate(fragments):
        path = tmp_path / f'seg{n}.mp4'
        path.write_bytes(data)
        paths[str(n)] = path
        probe = subprocess.check_output([str(settings.ffprobe), '-v', 'error', '-count_frames', '-show_entries',
                                         'stream=start_time,nb_read_frames', '-of', 'csv=p=0', str(path)], text=True)
        start, count = probe.strip().split(',')
        assert float(start) == 0 and int(count) == frames  # 예전 구간 파일처럼 0초 시작·단독 재생
        segments.append(Segment('s', str(n), 1_000_000 + n * 250_000, 1_000_000 + n * 250_000 + frames * 1_000_000 // 60,
                                path.stat().st_size, '64x48:60:video'))
    plan = SavePlan(1_600_000, (Slice(segments[0], 100_000, 150_000), Slice(segments[1], 0, 250_000),
                                Slice(segments[2], 0, 100_000)))
    clip = tmp_path / 'clip.mp4'
    with clip.open('wb') as output:
        encoder.encode(plan, ByteSink(output, 1 << 20))
    encoder.validate(clip, plan)
    raw = subprocess.check_output([str(settings.ffmpeg), '-v', 'error', '-i', str(clip), '-f', 'rawvideo',
                                   '-pix_fmt', 'rgb24', 'pipe:1'], timeout=20)
    size = 64 * 48 * 3
    def color(frame):
        r, g, b = frame[0], frame[1], frame[2]
        return 'red' if r > 150 else 'blue' if b > 150 else 'green' if g > 150 else 'other'
    colors = [color(raw[n + size // 2:n + size // 2 + 3]) for n in range(0, len(raw), size)]
    assert colors == ['red'] * 9 + ['blue'] * 15 + ['green'] * 6


def test_encoder_stream_crash_reports_exit_code_and_stderr():
    fake = [sys.executable, '-c', "import sys; sys.stderr.write('h264_nvenc: OpenEncodeSessionEx failed\\n'); sys.exit(1)"]
    stream = EncoderStream(fake, lambda data, frames: None)
    with pytest.raises(OSError, match='encoder exited 1: h264_nvenc: OpenEncodeSessionEx failed') as caught:
        for _ in range(200):
            stream.write(bytes(1 << 20))
    assert not isinstance(caught.value, BrokenPipeError)
    stream.abort()


# ---- 생산자(가짜 장치·상주 인코더) ----

class Device:
    audio = (None, None)
    def __init__(self, frames): self.frames = list(frames)
    def open(self, target): pass
    def read(self): return self.frames.pop(0) if self.frames else None
    def read_audio(self): return None
    def close(self): pass


class StreamCodec:
    """조각은 실제 mp4 muxer처럼 다음 키프레임이 들어올 때(또는 끝낼 때) 나온다."""
    settings = SimpleNamespace(fps=10, timeout=5)
    def __init__(self, fail=False):
        self.opened, self.fail = [], fail
    def encoder(self): return 'h264_test'
    def open_stream(self, width, height, gop, on_fragment):
        codec = self
        class Stream:
            held = 0
            def write(self, data):
                if codec.fail:
                    raise OSError('encoder exited 1: h264_nvenc: OpenEncodeSessionEx failed')
                if self.held == gop:
                    on_fragment(b'f' * gop, gop); self.held = 0
                self.held += 1
                return 0.0
            def finish(self, timeout):
                if self.held:
                    on_fragment(b'f' * self.held, self.held); self.held = 0
            def abort(self): pass
        self.opened.append((width, height, gop))
        return Stream()


class Spool:
    def __init__(self): self.n = 0
    def write(self, produce, max_bytes=None):
        self.n += 1; produce(io.BytesIO()); return str(self.n)
    def resolve(self, key): return SimpleNamespace(stat=lambda: SimpleNamespace(st_size=1))
    def discard(self, key): pass


def _producer(frames, codec, gop=3):
    limits = ProducerLimits(gop, 1, 64, 64 * gop * 3, 1000, 50_000)
    return CaptureProducer(SimpleNamespace(session='s'), Device(frames), codec, Spool(), limits, allowed=lambda: True)


def _drain(producer, results, until, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not until():
        while not producer.results.empty():
            results.append(producer.results.get_nowait())
        time.sleep(.005)


def _stop(producer, results):
    producer.request_stop()
    _drain(producer, results, producer.is_stopped)
    while not producer.results.empty():
        results.append(producer.results.get_nowait())


def test_one_encoder_for_continuous_recording_and_restart_only_after_gap():
    frame = b'\x00' * 64
    stamps = [1_000_000 + n * 100_000 for n in range(9)] + [3_000_000 + n * 100_000 for n in range(3)]
    codec = StreamCodec()
    producer = _producer([(frame, 4, 4, t) for t in stamps], codec)
    producer.start()
    results = []
    _drain(producer, results, lambda: not producer.native.frames)
    _stop(producer, results)
    spans = [(item.start_us, item.end_us) for kind, item in results if kind == 'segment']
    assert producer.error is None and producer.gaps == 1
    assert codec.opened == [(4, 4, 3), (4, 4, 3)] and producer.restarts == 1  # 공백에서만 다시 연다
    assert spans == [(1_000_000, 1_300_000), (1_300_000, 1_600_000), (1_600_000, 1_900_000), (3_000_000, 3_300_000)]


def test_save_request_waits_for_fragment_then_closes_encoder_when_screen_is_static(monkeypatch):
    monkeypatch.setattr(blackbox_producer, 'FLUSH_WAIT_S', 0.2)
    frame = b'\x00' * 64
    codec = StreamCodec()
    producer = _producer([(frame, 4, 4, 1_000_000 + n * 100_000) for n in range(4)], codec)
    producer.start()
    results = []
    _drain(producer, results, lambda: not producer.native.frames)
    time.sleep(.05)
    producer.request_flush('token', 1_350_000)
    _drain(producer, results, lambda: any(kind == 'flush' for kind, _ in results))
    kinds = [kind for kind, _ in results]
    assert kinds == ['segment', 'segment', 'flush']  # 요청 전 프레임(4장)이 모두 구간이 된 뒤에 저장 진행
    assert [(item.start_us, item.end_us) for kind, item in results if kind == 'segment'] == [
        (1_000_000, 1_300_000), (1_300_000, 1_400_000)]
    assert producer.restarts == 1
    _stop(producer, results)
    assert producer.error is None


def test_encoder_failure_stops_recording_through_existing_error_path(caplog):
    caplog.set_level(logging.WARNING)
    frame = b'\x00' * 64
    producer = _producer([(frame, 4, 4, 1_000_000 + n * 100_000) for n in range(3)], StreamCodec(fail=True))
    producer.start()
    results = []
    _drain(producer, results, producer.is_stopped)
    assert producer.is_stopped()
    assert 'OpenEncodeSessionEx failed' in producer.error
    assert '블랙박스 인코딩 오류로 녹화 중단' in caplog.text


def test_summary_reports_input_wait_fill_distinct_fps_read_and_gap_increase(monkeypatch, caplog):
    monkeypatch.setattr(blackbox_producer, '_TIMING_EVERY', 2)
    caplog.set_level(logging.INFO, logger='mabinogi_addon.blackbox_producer')
    stamps = [1_000_000, 1_100_000, 1_300_000, 1_400_000, 1_500_000, 1_600_000]  # 1.2초 누락 → 반복 채움 1칸
    producer = _producer([(bytes([n]) * 64, 4, 4, t) for n, t in enumerate(stamps)], StreamCodec())
    producer.start()
    results = []
    _drain(producer, results, lambda: not producer.native.frames)
    _stop(producer, results)
    summary = [r.getMessage() for r in caplog.records if '최근 2개' in r.getMessage()]
    assert summary, caplog.text
    line = summary[0]
    assert '블랙박스 인코더 입력 대기 최근 2개' in line and '구간 길이 초과 0개' in line
    assert '반복 채움 +1칸' in line and '서로 다른 화면 8.3FPS' in line  # 6칸(0.6초) 중 서로 다른 화면 5장
    assert '캡처 읽기 평균' in line and '프레임 공백 +0회(누적 0)' in line and '인코더 재시작 누적 0회' in line
