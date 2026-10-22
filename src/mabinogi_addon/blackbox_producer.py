"""장치와 코덱을 주입하는 유한 영상 생산자. UI 스레드는 결과 큐만 읽는다.

원시 프레임 큐가 차면 오류로 중단하고 무음 누락/무제한 메모리 증가로 대체하지 않는다.
게임 PCM은 같은 시간 구간이 완전히 있을 때만 결합한다. 누락 시 실패하고 무음으로 대체하지 않는다.
"""
from dataclasses import dataclass
from queue import Queue, Empty, Full
from threading import Event, Thread, Lock

from .blackbox import Segment
from .blackbox_native import NativeTransition
from .blackbox_audio import PcmTimeline
import io
import wave


@dataclass(frozen=True)
class ProducerLimits:
    segment_frames: int
    queued_segments: int
    max_frame_bytes: int
    max_raw_bytes: int
    max_segment_bytes: int
    frame_tolerance_us: int
    max_width: int | None = None
    max_height: int | None = None

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for key, v in vars(self).items() if key not in ('max_width', 'max_height')):
            raise ValueError('explicit positive producer bounds required')
        if (self.max_width is None) != (self.max_height is None) or any(
                v is not None and (type(v) is not int or v <= 0) for v in (self.max_width, self.max_height)):
            raise ValueError('explicit paired source dimensions required')
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
                    raise ValueError(f'게임창 입력은 최대 {self.limits.max_width}×{self.limits.max_height}이에요. 창 크기를 줄여 주세요.')
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
                    raise ValueError('frame clock drift exceeds bound')
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
        finally:
            try:
                self.native.close()
            except Exception as exc:
                self._error = f'native close failed: {exc}'
            if self.audio is not None:
                self.audio.close()
            self._captured.set()

    def _encode_loop(self):
        try:
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
                    count = min(len(frames), max(0, int(((covered or stamps[0]) - stamps[0]) * self.codec.settings.fps / 1_000_000 + 1e-6)))
                    if not count:
                        continue  # 종료 경계의 불완전 A/V 프레임을 영상이나 무음으로 꾸미지 않는다.
                    frames = frames[:count]
                    duration = round(count * 1_000_000 / self.codec.settings.fps)
                    pcm = self.audio.slice(stamps[0], stamps[0] + duration, timeout=self.codec.settings.timeout)
                    wav = io.BytesIO()
                    with wave.open(wav, 'wb') as writer:
                        writer.setnchannels(self.native.audio[1]); writer.setsampwidth(2)
                        writer.setframerate(self.native.audio[0]); writer.writeframes(pcm)
                    audio_source = self.spool.write(lambda sink: sink.write(wav.getvalue()),
                                                   max_bytes=len(pcm) + 44)
                audio_path = self.spool.resolve(audio_source) if audio_source else None
                source = self.spool.write(lambda sink: self.codec.encode_frames(frames, width, height, sink,
                                          audio_path=audio_path), max_bytes=self.limits.max_segment_bytes)
                segment = Segment(self.target.session, source, stamps[0], stamps[0] + duration,
                    self.spool.resolve(source).stat().st_size, f'{width}x{height}:{self.codec.settings.fps}:' + ('audio' if self.audio is not None else 'video'))
                self._put(self.results, ('segment', segment))
                if audio_source is not None:
                    self.spool.discard(audio_source)
        except BaseException as exc:
            self.transition = False
            self._error = f'{type(exc).__name__}: {exc}'
            self._stop.set()
        finally:
            self._encoded.set()
