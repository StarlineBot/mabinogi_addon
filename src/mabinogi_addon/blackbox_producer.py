"""장치와 코덱을 주입하는 유한 영상 생산자. UI 스레드는 결과 큐만 읽는다.

원시 프레임 큐가 차면 오류로 중단하고 무음 누락/무제한 메모리 증가로 대체하지 않는다.
게임 PCM은 같은 시간 구간이 완전히 있을 때만 결합한다. 누락 시 실패하고 무음으로 대체하지 않는다.
"""
from collections import deque
from dataclasses import dataclass
from queue import Queue, Empty, Full
from threading import Event, Thread, Lock
import logging
import os
import sys
import time

from .blackbox import Segment
from .blackbox_native import NativeTransition
from .system.blackbox_capture import frame_bytes
from .blackbox_audio import PcmTimeline
import io
import wave

_log = logging.getLogger(__name__)
_TIMING_FIRST = 3        # 처음 몇 구간은 인코딩 시간을 하나씩 남긴다
_TIMING_EVERY = 240      # 이후에는 이만큼(60FPS·15프레임 기준 약 60초)마다 요약
FILL_LIMIT_US = 250_000  # 이 안의 프레임 공백은 직전 프레임 반복으로 채우고, 넘으면 구간을 끊는다
FLUSH_WAIT_S = 1.0       # 저장 요청 지점이 담긴 조각을 기다리는 상한(화면이 멈춰 프레임이 안 오면 인코더를 닫아 마무리)
AUDIO_WAIT_S = 3.0       # 한 묶음이 소리를 기다리는 상한. 넘으면 소리가 있는 만큼만 쓰고 이어 녹화(무음 채움 없음)


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


CPU_PASS_PERCENT = 5.0  # 블랙박스 11.4 합격선: 녹화 중 앱+인코더 합계(작업 관리자 기준, 전체 코어 = 100%)


def _default_cpu_meter():
    if sys.platform != 'win32':
        return None
    from .system.process_threads import ProcessTreeCpu
    return ProcessTreeCpu()


class CaptureProducer:
    def __init__(self, target, native, codec, spool, limits: ProducerLimits, *, allowed, cpu_meter=None):
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
        self.filled = 0  # 직전 프레임 반복으로 채운 칸 수
        self._timing = []
        # 녹화 진단(0.15.0 검증 지표): 캡처 읽기 시간, 직전 요약 이후 반복 채움·공백 증가분·서로 다른 화면 수
        self._reads = deque(maxlen=8192)
        self._distinct, self._slots = 0, 0
        self._logged_filled = self._logged_gaps = 0
        self.restarts = 0  # 상주 인코더를 다시 연 횟수(공백·저장 마무리)
        self.pixel_format_logged = None  # 처음 받은 캡처 형식(로그 1회)
        # 블랙박스 11.4 검증 지표: 요약마다 앱 전체(하위 프로세스 포함)·인코더 CPU를 함께 남긴다
        self._cpu_meter = cpu_meter if cpu_meter is not None else _default_cpu_meter()
        self._encoder_pid = None
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

    def _pump_audio(self):
        """도착한 소리 묶음을 모두 타임라인에 넣는다(캡처 스레드 전용)."""
        if self.audio is not None:
            while packet := self.native.read_audio():
                self.audio.push(*packet)

    def _put(self, queue, item, pump=False):
        # bounded backpressure; controller drains results while shutdown is pending
        while True:
            try:
                queue.put(item, timeout=0.05)
                return
            except Full:
                if self._error is not None:
                    raise RuntimeError('producer failed while queue was full')
                if pump:
                    # 인코딩 스레드가 소리를 기다리는 동안 캡처가 대기열에서 막혀 소리를 못 읽으면 교착된다(0.13.2 QA).
                    self._pump_audio()

    def _capture_loop(self):
        frames, stamps, dimensions = [], [], None
        def flush():
            nonlocal frames, stamps
            if frames:
                self._put(self._batches, (tuple(frames), tuple(stamps), dimensions), pump=True)
                frames, stamps = [], []
        try:
            while not self._ready.is_set():
                if self._stop.wait(0.02):
                    return
            self.native.open(self.target)
            period = 1_000_000 / self.codec.settings.fps
            previous = None
            last = None  # 반복 채움에 쓸 직전 프레임(같은 bytes 참조, 복사 없음)
            origin, count = None, 0
            while not self._stop.is_set():
                if self.allowed() is not True:
                    raise PermissionError('blackbox access revoked')
                with self._flush_lock:
                    requests, self._flush = self._flush, []
                if requests:
                    flush()
                    for request in requests:
                        self._put(self._batches, ('flush', request), pump=True)
                self._pump_audio()
                read_started = time.perf_counter()
                frame = self.native.read()
                if frame is not None:
                    self._reads.append(time.perf_counter() - read_started)
                if frame is None:
                    self._stop.wait(0.002)
                    continue
                # 블랙박스 11.4: NV12(GPU 색 변환)면 다섯 번째 값이 'nv12'. 없으면 BGRA(이전 방식·구버전 DLL).
                data, width, height, stamp, *rest = frame
                pixel_format = rest[0] if rest else 'bgra'
                if self._stop.is_set() or self.allowed() is not True:
                    break
                if self.limits.max_width is not None and (width > self.limits.max_width or height > self.limits.max_height):
                    raise ValueError(f'블랙박스 영상 {width}×{height}이 출력 한도 '
                                     f'{self.limits.max_width}×{self.limits.max_height}를 넘었어요(축소 결과 확인 실패).')
                if len(data) > self.limits.max_frame_bytes or len(data) != frame_bytes(width, height, pixel_format):
                    raise ValueError('native frame exceeds bound')
                if dimensions is not None and dimensions[:2] != (width, height):
                    raise ValueError('capture dimensions changed; new format required')
                if dimensions is not None and dimensions[2] != pixel_format:
                    # GPU가 NV12를 못 해 BGRA로 내려온 경우: 지금까지를 닫고 새 형식 인코더로 이어 간다.
                    _log.warning('블랙박스 GPU 색 변환(NV12) 불가 · %s로 이어서 녹화(인코더 CPU 사용 증가)', pixel_format)
                    flush()
                    last = None
                if dimensions is None and self.pixel_format_logged is None:
                    self.pixel_format_logged = pixel_format
                    _log.info('블랙박스 캡처 형식 %s %d×%d(%s)', pixel_format, width, height,
                              'GPU 색 변환' if pixel_format == 'nv12' else 'ffmpeg CPU 색 변환')
                dimensions = width, height, pixel_format
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
                lag = stamp - (origin + count * period)
                if lag > FILL_LIMIT_US or lag < -self.limits.frame_tolerance_us:
                    # 긴 공백(로딩·멈춤·인코딩 지연): 녹화를 멈추지 않고 지금까지를 한 구간으로 닫은 뒤
                    # 이 프레임부터 새 시각 기준으로 이어 간다(빈 시간은 저장 영상에서 빠짐).
                    flush()
                    origin, count = stamp, 0
                    self.gaps += 1
                    if self.gaps <= 3 or self.gaps % 100 == 0:
                        _log.info('블랙박스 프레임 공백 %.0fms · 새 구간으로 이어서 녹화(누적 %d회)', lag / 1000, self.gaps)
                elif lag >= period / 2 and last is not None:
                    # 게임이 60FPS보다 느리게 그리거나 화면이 멈춰 프레임이 덜 왔다: 직전 프레임을 반복해 빈 칸을 채워
                    # 실제 시간과 같은 속도로 재생되게 한다(2026-10-23 사용자 결정, 일반 녹화 프로그램 방식).
                    for _ in range(round(lag / period)):
                        frames.append(last); stamps.append(round(origin + count * period))
                        count += 1
                        self.filled += 1
                        if len(frames) >= self.limits.segment_frames:
                            flush()
                normalized = round(origin + count * period)
                count += 1
                previous = stamp
                frames.append(data); stamps.append(normalized)
                last = data
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

    def _diagnostics(self):
        """직전 요약 이후 녹화 진단 문자열을 만들고 누적을 비운다(영상 끊김 원인 구분용)."""
        reads, self._reads = list(self._reads), deque(maxlen=8192)
        fps = self._distinct / (self._slots / self.codec.settings.fps) if self._slots else 0.0
        filled, gaps = self.filled - self._logged_filled, self.gaps - self._logged_gaps
        self._logged_filled, self._logged_gaps, self._distinct, self._slots = self.filled, self.gaps, 0, 0
        read = (f'평균 {sum(reads) / len(reads) * 1000:.1f}ms·최대 {max(reads) * 1000:.1f}ms' if reads else '없음')
        return (f'반복 채움 +{filled}칸 · 서로 다른 화면 {fps:.1f}FPS · 캡처 읽기 {read} · '
                f'프레임 공백 +{gaps}회(누적 {self.gaps}) · 인코더 재시작 누적 {self.restarts}회'
                f'{self._cpu_text()}')

    def _cpu_sample(self):
        if self._cpu_meter is None:
            return None
        try:
            return self._cpu_meter.sample(os.getpid(), self._encoder_pid)
        except Exception as exc:  # 진단 실패가 녹화를 멈추지 않게
            self._cpu_meter = None
            _log.info('블랙박스 CPU 측정 중단: %s', exc)
            return None

    def _cpu_text(self):
        """직전 요약 이후 CPU. 앱 전체는 인코더 등 하위 프로세스를 포함한 합계(합격선과 같은 기준)."""
        used = self._cpu_sample()
        if used is None:
            return ''
        total, encoder = used
        verdict = '합격선 이내' if total <= CPU_PASS_PERCENT else '합격선 초과'
        return (f' · CPU(전체 코어 기준) 앱+인코더 {total:.1f}%(인코더 {encoder:.1f}%) · '
                f'{verdict}(최대 {CPU_PASS_PERCENT:.0f}%)')

    def _segment_timing(self, seconds, frames, distinct=None, label='구간 인코딩'):
        """구간(묶음)마다 걸린 시간. 상주 인코더에서는 인코더 입력(stdin) 대기 시간이다."""
        budget = frames / self.codec.settings.fps
        self._timing.append(seconds)
        self._slots += frames
        self._distinct += frames if distinct is None else distinct
        count = len(self._timing)
        if count <= _TIMING_FIRST:
            _log.info('블랙박스 %s %.3f초(구간 길이 %.3f초)', label, seconds, budget)
        if count % _TIMING_EVERY == 0:
            recent = self._timing[-_TIMING_EVERY:]
            _log.info('블랙박스 %s 최근 %d개: 평균 %.3f초 · 최대 %.3f초 · 구간 길이 초과 %d개 · %s'
                      ' · 소리 공백 누적 %d회', label, len(recent), sum(recent) / len(recent), max(recent),
                      sum(t > budget for t in recent), self._diagnostics(),
                      self.audio.gaps if self.audio is not None else 0)
            del self._timing[:-_TIMING_EVERY]

    @staticmethod
    def _distinct_frames(frames):
        # 반복 채움 칸은 직전 프레임과 같은 bytes 객체라 객체 비교로 서로 다른 화면 수를 센다
        return 1 + sum(frames[i] is not frames[i - 1] for i in range(1, len(frames)))

    def _stream_loop(self):
        """상주 인코더(0.15.0): 연속 구간 동안 ffmpeg 1개에 프레임을 계속 흘리고 조각마다 구간을 만든다.

        공백(시각이 이어지지 않음)·화면 크기 변경·종료 때만 인코더를 닫고 다시 연다. 저장 요청(flush)은
        요청 전까지 넣은 프레임이 모두 조각으로 나온 뒤에 결과로 넘긴다(조각은 다음 키프레임이 와야 나오므로
        보통 0.25~0.5초 뒤). 화면이 멈춰 FLUSH_WAIT_S 안에 안 나오면 인코더를 닫아 마무리한다."""
        fps = self.codec.settings.fps
        period = 1_000_000 / fps
        lock = Lock()
        state = dict(stream=None, dims=None, expected=None, written=0, emitted=0)
        stamps = deque()
        pending = []  # (이 시점까지 넣은 프레임 수, 저장 요청, 받은 시각)

        def on_fragment(data, count):  # 인코더 출력 스레드
            if len(stamps) < count:
                raise ValueError(f'인코더 조각 프레임 수 {count}가 넣은 프레임보다 많아요')
            start = stamps[0]
            for _ in range(count):
                stamps.popleft()
            width, height = state['dims'][:2]
            source = self.spool.write(lambda sink: sink.write(data), max_bytes=self.limits.max_segment_bytes)
            segment = Segment(self.target.session, source, start, start + round(count * 1_000_000 / fps),
                              self.spool.resolve(source).stat().st_size, f'{width}x{height}:{fps}:video')
            self._put(self.results, ('segment', segment))
            self.segments += 1
            with lock:
                state['emitted'] += count
                ready = [request for written, request, _ in pending if written <= state['emitted']]
                pending[:] = [item for item in pending if item[0] > state['emitted']]
            for request in ready:
                self._put(self.results, ('flush', request))

        def close(graceful=True):
            stream = state['stream']
            if stream is None:
                return
            state['stream'] = None
            if graceful:
                stream.finish(self.codec.settings.timeout)
                if stamps:
                    raise ValueError(f'인코더가 넣은 프레임 {len(stamps)}개를 구간으로 내보내지 않았어요')
            else:
                stream.abort()
            stamps.clear()
            with lock:
                ready, pending[:] = [request for _, request, _ in pending], []
            for request in ready:
                self._put(self.results, ('flush', request))

        def restarted(reason):
            self.restarts += 1
            if self.restarts <= 3 or self.restarts % 100 == 0:
                _log.info('블랙박스 인코더 다시 시작(%s) · 누적 %d회', reason, self.restarts)

        try:
            while not self._captured.is_set() or not self._batches.empty():
                with lock:
                    waiting = pending and time.monotonic() - pending[0][2] > FLUSH_WAIT_S
                if waiting:
                    close()  # 화면이 멈춰 다음 조각이 안 나옴: 남은 프레임을 마무리해 저장을 진행한다
                    restarted('저장 요청 마무리')
                try:
                    batch = self._batches.get(timeout=0.05)
                except Empty:
                    continue
                if batch[0] == 'flush':
                    with lock:
                        if state['stream'] is None or state['written'] <= state['emitted']:
                            ready = True
                        else:
                            ready = False
                            pending.append((state['written'], batch[1], time.monotonic()))
                    if ready:
                        self._put(self.results, batch)
                    continue
                frames, batch_stamps, dims = batch
                if state['stream'] is not None and (dims != state['dims'] or abs(batch_stamps[0] - state['expected']) > period / 2):
                    close()  # 공백·크기 변경: 이 지점에서 영상이 이어지지 않으므로 새 인코더로
                    restarted(('화면 크기 변경' if dims[:2] != state['dims'][:2] else '캡처 형식 변경')
                              if dims != state['dims'] else '프레임 공백')
                if state['stream'] is None:
                    state['dims'] = dims
                    with lock:
                        state['written'] = state['emitted'] = 0
                    started = time.perf_counter()
                    extra = {} if dims[2] == 'bgra' else {'pixel_format': dims[2]}
                    state['stream'] = self.codec.open_stream(dims[0], dims[1], self.limits.segment_frames, on_fragment, **extra)
                    self._encoder_pid = getattr(getattr(state['stream'], 'process', None), 'pid', None)
                    if not self.restarts:
                        self._cpu_sample()  # 기준 표본: 첫 요약이 녹화 시작부터의 CPU가 되게
                    if not self.restarts:
                        _log.info('블랙박스 상주 인코더 시작 %d×%d %s · %.2f초', dims[0], dims[1], dims[2],
                                  time.perf_counter() - started)
                waited = 0.0
                for data, stamp in zip(frames, batch_stamps):
                    stamps.append(stamp)
                    waited += state['stream'].write(data)
                    with lock:
                        state['written'] += 1
                state['expected'] = batch_stamps[-1] + period
                self._segment_timing(waited, len(frames), self._distinct_frames(frames), '인코더 입력 대기')
            close()
        except BaseException:
            try:
                close(graceful=False)
            except Exception:
                pass
            raise

    def _encode_loop(self):
        try:
            select = getattr(self.codec, 'encoder', None)
            if select is not None:
                started = time.perf_counter()
                encoder = select()  # 후보 시험 인코딩은 캡처 시작 전에(첫 구간이 밀리지 않게)
                _log.info('블랙박스 인코더 준비 %.2f초: %s', time.perf_counter() - started, encoder)
            self._ready.set()
            if self.audio is None and hasattr(self.codec, 'open_stream'):
                return self._stream_loop()
            while not self._captured.is_set() or not self._batches.empty():
                try:
                    batch = self._batches.get(timeout=0.05)
                except Empty:
                    continue
                if batch[0] == 'flush':
                    self._put(self.results, batch)
                    continue
                frames, stamps, (width, height, pixel_format) = batch
                if pixel_format != 'bgra':
                    raise ValueError(f'구간 인코딩은 BGRA만 받아요({pixel_format})')
                duration = round(len(frames) * 1_000_000 / self.codec.settings.fps)
                audio_source = None
                if self.audio is not None:
                    # 소리가 멈춘(게임 무음) 동안 무한정 기다리지 않는다. 상한 뒤에는 확보한 만큼만 쓴다.
                    covered = self.audio.covered_end(stamps[0] + duration, timeout=AUDIO_WAIT_S, partial=True)
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
                    pcm = self.audio.slice(stamps[0], stamps[0] + duration, timeout=AUDIO_WAIT_S)
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
                self._segment_timing(time.perf_counter() - started, len(frames), self._distinct_frames(frames))
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
