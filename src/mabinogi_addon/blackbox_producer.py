"""장치와 코덱을 주입하는 유한 영상 생산자. UI 스레드는 결과 큐만 읽는다.

원시 프레임 큐가 차면 오류로 중단하고 무음 누락/무제한 메모리 증가로 대체하지 않는다.
게임 PCM은 같은 시간 구간이 완전히 있을 때만 결합한다. 누락 시 실패하고 무음으로 대체하지 않는다.
"""
from dataclasses import dataclass
from queue import Queue, Empty, Full
from threading import Event, Thread, Lock
import logging
import time

from .blackbox import Segment
from .blackbox_native import NativeTransition
from .blackbox_audio import PcmTimeline
import io
import wave

_log = logging.getLogger(__name__)
_TIMING_FIRST = 3        # 처음 몇 구간은 인코딩 시간을 하나씩 남긴다
_TIMING_EVERY = 240      # 이후에는 이만큼(60FPS·15프레임 기준 약 60초)마다 요약


@dataclass(frozen=True)
class ProducerLimits:
    segment_frames: int
    queued_segments: int
    max_frame_bytes: int
    max_raw_bytes: int
    max_segment_bytes: int
    frame_tolerance_us: int
    max_width: int | None = None   # 출력(인코더 입력) 최대 크기 — 큰 게임 창은 GPU에서 이 안으로 축소
    max_height: int | None = None
    max_input_width: int | None = None   # 받아들일 게임 창 최대 크기
    max_input_height: int | None = None

    def __post_init__(self):
        optional = ('max_width', 'max_height', 'max_input_width', 'max_input_height')
        if any(type(v) is not int or v <= 0 for key, v in vars(self).items() if key not in optional):
            raise ValueError('explicit positive producer bounds required')
        if (self.max_width is None) != (self.max_height is None) or any(
                v is not None and (type(v) is not int or v <= 0) for v in (self.max_width, self.max_height)):
            raise ValueError('explicit paired source dimensions required')
        if (self.max_input_width is None) != (self.max_input_height is None) or (
                self.max_input_width is not None and (self.max_width is None or any(
                    type(v) is not int for v in (self.max_input_width, self.max_input_height))
                    or self.max_input_width < self.max_width or self.max_input_height < self.max_height)):
            raise ValueError('explicit paired input bounds at least the output bounds required')
        if self.max_frame_bytes * self.segment_frames * (self.queued_segments + 2) > self.max_raw_bytes:
            raise ValueError('raw frame queues exceed explicit RAM budget')


class CaptureProducer:
    def __init__(self, target, native, codec, spool, limits: ProducerLimits, *, allowed):
        self.audio = None
        if native.audio[0] is not None:
            self.audio = PcmTimeline(native.audio[0], native.audio[1], native.audio_buffer_bytes)
        self.target, self.native, self.codec, self.spool = target, native, codec, spool
        self.limits, self.allowed = limits, allowed
        self.results = Queue(maxsize=limits.queued_segments + 2)
        self._batches = Queue(maxsize=limits.queued_segments)
        self._stop, self._captured, self._encoded = Event(), Event(), Event()
        self._ready = Event()  # 인코더 후보 시험을 마친 뒤 캡처를 시작한다(첫 구간 지연이 캡처를 막지 않게)
        self.gaps = 0  # 프레임 시각이 크게 밀려 새 구간으로 이어 간 횟수
        self.segments = 0  # 완료한 구간 수(오류 로그용)
        self._timing = []
        self._flush = []
        self._flush_lock = Lock()
        self._error = None
        self.transition = False
        self._capture = Thread(target=self._capture_loop, name='blackbox-window')
        self._encoder = Thread(target=self._encode_loop, name='blackbox-segments')

    def start(self):
        self._encoder.start()
        self._capture.start()

    def request_stop(self):
        self._stop.set()

    def is_stopped(self):
        return self._captured.is_set() and self._encoded.is_set()

    @property
    def error(self):
        return self._error

    def request_flush(self, token, request_us):
        with self._flush_lock:
            if self._stop.is_set() or len(self._flush) >= 2:
                raise RuntimeError('capture flush unavailable')
            self._flush.append((token, request_us))

    def _put(self, queue, item):
        # bounded backpressure; controller drains results while shutdown is pending
        while True:
            try:
                queue.put(item, timeout=0.05)
                return
            except Full:
                if self._error is not None:
                    raise RuntimeError('producer failed while queue was full')

    def _capture_loop(self):
        frames, stamps, dimensions = [], [], None
        def flush():
            nonlocal frames, stamps
            if frames:
                self._put(self._batches, (tuple(frames), tuple(stamps), dimensions))
                frames, stamps = [], []
        try:
            while not self._ready.is_set():
                if self._stop.wait(0.02):
                    return
            self.native.open(self.target)
            period = 1_000_000 / self.codec.settings.fps
            previous = None
            origin, count = None, 0
            while not self._stop.is_set():
                if self.allowed() is not True:
                    raise PermissionError('creator access revoked')
                with self._flush_lock:
                    requests, self._flush = self._flush, []
                if requests:
                    flush()
                    for request in requests:
                        self._put(self._batches, ('flush', request))
                if self.audio is not None:
                    while packet := self.native.read_audio():
                        self.audio.push(*packet)
                frame = self.native.read()
                if frame is None:
                    self._stop.wait(0.002)
                    continue
                data, width, height, stamp = frame
                if self._stop.is_set() or self.allowed() is not True:
                    break
                if self.limits.max_width is not None and (width > self.limits.max_width or height > self.limits.max_height):
                    raise ValueError(f'블랙박스 영상 {width}×{height}이 출력 한도 '
                                     f'{self.limits.max_width}×{self.limits.max_height}를 넘었어요(축소 결과 확인 실패).')
                if len(data) > self.limits.max_frame_bytes or len(data) != width * height * 4:
                    raise ValueError('native frame exceeds bound')
                if dimensions is not None and dimensions != (width, height):
                    raise ValueError('capture dimensions changed; new format required')
                dimensions = width, height
                if previous is not None and stamp <= previous:
                    raise ValueError('out-of-order native frame')
                previous = stamp
                if origin is not None and stamp < origin + count * period - period / 2:
                    continue  # 높은 주사율 입력에서 설정 FPS에 가장 가까운 프레임 선택
                if origin is None and self.audio is not None:
                    audio_start = self.audio.start
                    if audio_start is None or stamp < audio_start:
                        continue
                if origin is None:
                    origin = stamp
                if abs(stamp - (origin + count * period)) > self.limits.frame_tolerance_us:
                    # 게임 끊김(로딩·장면 전환)이나 인코딩 지연으로 캡처가 밀렸다. 녹화를 멈추지 않고
                    # 지금까지를 한 구간으로 닫은 뒤 이 프레임부터 새 시각 기준으로 이어 간다(빈 시간은 저장 영상에서 빠짐).
                    lag = stamp - (origin + count * period)
                    flush()
                    origin, count = stamp, 0
                    self.gaps += 1
                    if self.gaps <= 3 or self.gaps % 100 == 0:
                        _log.info('블랙박스 프레임 공백 %.0fms · 새 구간으로 이어서 녹화(누적 %d회)', lag / 1000, self.gaps)
                normalized = round(origin + count * period)
                count += 1
                previous = stamp
                frames.append(data); stamps.append(normalized)
                if len(frames) >= self.limits.segment_frames:
                    flush()
            flush()
            with self._flush_lock:
                requests, self._flush = self._flush, []
            for request in requests:
                self._put(self._batches, ('flush', request))
        except BaseException as exc:
            try:
                flush()
            except Exception:
                pass
            self.transition = isinstance(exc, NativeTransition)
            self._error = f'{type(exc).__name__}: {exc}'
            self._log_error('캡처')
        finally:
            try:
                self.native.close()
            except Exception as exc:
                self._error = f'native close failed: {exc}'
            if self.audio is not None:
                self.audio.close()
            self._captured.set()

    def _log_error(self, stage):
        # 화면에만 보이던 생산자 오류를 app.log에 남긴다(발생 시각·원인 판단용, 0.13.0 실사용 로그 QA).
        _log.warning('블랙박스 %s 오류로 녹화 중단: %s · 대상 %s · 완료 구간 %d개 · 프레임 공백 %d회 · 소리 공백 %d회',
                     stage, self._error, self.target, self.segments, self.gaps,
                     self.audio.gaps if self.audio is not None else 0)

    def _segment_timing(self, seconds, frames):
        budget = frames / self.codec.settings.fps
        self._timing.append(seconds)
        count = len(self._timing)
        if count <= _TIMING_FIRST:
            _log.info('블랙박스 구간 인코딩 %.3f초(구간 길이 %.3f초)', seconds, budget)
        if count % _TIMING_EVERY == 0:
            recent = self._timing[-_TIMING_EVERY:]
            _log.info('블랙박스 구간 인코딩 최근 %d개: 평균 %.3f초 · 최대 %.3f초 · 구간 길이 초과 %d개 · 프레임 공백 누적 %d회'
                      ' · 소리 공백 누적 %d회', len(recent), sum(recent) / len(recent), max(recent),
                      sum(t > budget for t in recent), self.gaps, self.audio.gaps if self.audio is not None else 0)
            del self._timing[:-_TIMING_EVERY]

    def _encode_loop(self):
        try:
            select = getattr(self.codec, 'encoder', None)
            if select is not None:
                started = time.perf_counter()
                encoder = select()  # 후보 시험 인코딩은 캡처 시작 전에(첫 구간이 밀리지 않게)
                _log.info('블랙박스 인코더 준비 %.2f초: %s', time.perf_counter() - started, encoder)
            self._ready.set()
            while not self._captured.is_set() or not self._batches.empty():
                try:
                    batch = self._batches.get(timeout=0.05)
                except Empty:
                    continue
                if batch[0] == 'flush':
                    self._put(self.results, batch)
                    continue
                frames, stamps, (width, height) = batch
                duration = round(len(frames) * 1_000_000 / self.codec.settings.fps)
                audio_source = None
                if self.audio is not None:
                    covered = self.audio.covered_end(stamps[0] + duration, timeout=self.codec.settings.timeout)
                    # 소리가 연속인 구간에서만 영상을 만든다. 소리 공백에 걸친 프레임은 빼고(무음으로 채우지 않음)
                    # 공백 뒤 프레임은 다음 구간으로 넘어가지 않으므로 이 묶음에서 버린다.
                    run = self.audio.run_within(stamps[0], covered or stamps[0])
                    if run is None:
                        continue
                    first = next((i for i, stamp in enumerate(stamps) if stamp >= run[0] - 1), len(stamps))
                    count = min(len(frames) - first, max(0, int((run[1] - stamps[first]) * self.codec.settings.fps / 1_000_000 + 1e-6))
                                if first < len(stamps) else 0)
                    if count <= 0:
                        continue  # 종료 경계·소리 공백의 불완전 A/V 프레임을 영상이나 무음으로 꾸미지 않는다.
                    frames, stamps = frames[first:first + count], stamps[first:first + count]
                    duration = round(count * 1_000_000 / self.codec.settings.fps)
                    pcm = self.audio.slice(stamps[0], stamps[0] + duration, timeout=self.codec.settings.timeout)
                    wav = io.BytesIO()
                    with wave.open(wav, 'wb') as writer:
                        writer.setnchannels(self.native.audio[1]); writer.setsampwidth(2)
                        writer.setframerate(self.native.audio[0]); writer.writeframes(pcm)
                    audio_source = self.spool.write(lambda sink: sink.write(wav.getvalue()),
                                                   max_bytes=len(pcm) + 44)
                audio_path = self.spool.resolve(audio_source) if audio_source else None
                started = time.perf_counter()
                source = self.spool.write(lambda sink: self.codec.encode_frames(frames, width, height, sink,
                                          audio_path=audio_path), max_bytes=self.limits.max_segment_bytes)
                self._segment_timing(time.perf_counter() - started, len(frames))
                segment = Segment(self.target.session, source, stamps[0], stamps[0] + duration,
                    self.spool.resolve(source).stat().st_size, f'{width}x{height}:{self.codec.settings.fps}:' + ('audio' if self.audio is not None else 'video'))
                self._put(self.results, ('segment', segment))
                self.segments += 1
                if audio_source is not None:
                    self.spool.discard(audio_source)
        except BaseException as exc:
            self.transition = False
            self._error = f'{type(exc).__name__}: {exc}'
            self._log_error('인코딩')
            self._stop.set()
        finally:
            self._ready.set()
            self._encoded.set()
