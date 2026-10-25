"""Qt와 분리된 앱 실행 제어. tick은 한 제어 스레드에서 호출한다.

숫자/바이너리 경로는 완전한 명시적 profile이 있을 때만 생성한다. 초기 제품 기본값 없음.
게임 재실행은 별도 ReplayBuffer로 보존하며 모든 실행이 하나의 1worker/2slot 큐를 공유한다.
"""
from dataclasses import dataclass
import logging
from pathlib import Path
from queue import Empty
import time
import uuid

from .blackbox import ReplayBuffer, DEFAULT_RETENTION_US
from .blackbox_budget import DiskBudget
from .blackbox_codec import CodecSettings, FFmpegEncoder
from .blackbox_native import NativeCapture
from .blackbox_producer import CaptureProducer, ProducerLimits
from .blackbox_queue import ExportQueue
from .blackbox_runtime import BlackboxRuntime
from .blackbox_session import BlackboxSession, CaptureContext
from .blackbox_spool import DiskSpool, clean_leftovers
from .feature_access import blackbox_available

_log = logging.getLogger(__name__)


MIN_SAVE_US = 1_000_000  # 이보다 짧은 보관분은 저장하지 않는다


class TooShortToSave(ValueError):
    """보관한 영상이 너무 짧아 저장하지 않음. recording_error면 녹화 오류로 보관분이 없는 경우."""

    def __init__(self, message, recording_error=False):
        super().__init__(message)
        self.recording_error = recording_error


@dataclass(frozen=True)
class ServiceSettings:
    temp_parent: Path
    output_folder: Path
    library: Path
    max_bytes: int
    min_free_bytes: int
    max_entries: int
    max_buffer_bytes: int
    max_segments: int
    max_output_bytes: int
    producer: ProducerLimits
    codec: CodecSettings
    cursor: bool
    audio: dict | None = None
    min_save_us: int = 0  # 제품 설정은 from_dict에서 MIN_SAVE_US(1초). 직접 만든 설정(검사용)은 제한 없음

    def __post_init__(self):
        if self.audio is not None and (type(self.codec.audio_bitrate) is not int or self.codec.audio_bitrate <= 0):
            raise ValueError('explicit audio bitrate required')
        if any(type(v) is not int or v <= 0 for v in (self.max_bytes, self.max_entries,
                self.max_buffer_bytes, self.max_segments, self.max_output_bytes)):
            raise ValueError('explicit positive storage limits required')
        if type(self.min_free_bytes) is not int or self.min_free_bytes < 0 or type(self.cursor) is not bool:
            raise ValueError('explicit free space and cursor policy required')
        if not all(Path(p).is_dir() for p in (self.temp_parent, self.output_folder)):
            raise ValueError('existing temporary/output directories required')

    @classmethod
    def from_dict(cls, profile):
        p = dict(profile)
        mode = p.pop('audio')
        audio = p.pop('audio_settings', None)
        if mode == 'process':
            expected = {'audio_rate', 'audio_channels', 'max_audio_bytes', 'activation_timeout_ms', 'audio_buffer_bytes'}
            if not isinstance(audio, dict) or set(audio) != expected or any(type(v) is not int or v <= 0 for v in audio.values()):
                raise ValueError('complete explicit process audio settings required')
        elif mode == 'disabled-for-validation':
            if audio is not None:
                raise ValueError('audio settings conflict with video-only validation')
        else:
            raise ValueError('explicit process audio or video-only validation mode required')
        p['audio'] = audio
        p.setdefault('min_save_us', MIN_SAVE_US)
        p.pop('hotkey_modifiers'); p.pop('hotkey_vk')
        p['producer'] = ProducerLimits(**p['producer'])
        c = dict(p['codec'])
        for key in ('ffmpeg', 'ffprobe', 'host'):
            if c.get(key) is not None:
                c[key] = Path(c[key])
        p['codec'] = CodecSettings(**c)
        for key in ('temp_parent', 'output_folder', 'library'):
            p[key] = Path(p[key]).absolute()
        return cls(**p)


class BlackboxService:
    def __init__(self, settings: ServiceSettings, *, enabled, persist_enabled,
                 allowed=blackbox_available, producer_factory=CaptureProducer, native_factory=NativeCapture):
        self.settings, self.enabled, self.persist = settings, enabled, persist_enabled
        self.allowed = allowed
        self.budget = DiskBudget(max_bytes=settings.max_bytes, min_free_bytes=settings.min_free_bytes,
                                 max_entries=settings.max_entries)
        # 이전 실행이 남긴 임시 자료(종료 시 정리 실패·비정상 종료)를 새 저장소를 만들기 전에 정리한다.
        removed, self.leftover_failures = clean_leftovers(settings.temp_parent, settings.output_folder)
        if removed:
            _log.info('지난 실행의 블랙박스 임시 자료 %d개를 정리했어요.', removed)
        if self.leftover_failures:
            _log.warning('지난 실행의 블랙박스 임시 자료 일부를 지우지 못했어요: %s', self.leftover_failures)
        self.spool = DiskSpool(settings.temp_parent, self.budget)
        self.queue = ExportQueue(self.budget, max_workers=1, max_jobs=2, creator_check=allowed)
        self.codec = FFmpegEncoder(settings.codec, self.spool.resolve)
        self._producer_factory, self._native_factory = producer_factory, native_factory
        self.runtimes = {}
        self.current = None
        self.producer = None
        self._permit = None
        self._pending = {}
        self._closing = False
        self._closed = False
        self.status = 'waiting'
        self.error = None
        self.completed = []  # UI drains; never an unbounded history
        self._retention = DEFAULT_RETENTION_US
        self._producer_target = None
        self._failed_target = None

    def _allowed(self):
        try:
            return self.allowed() is True
        except Exception:
            return False

    def set_enabled(self, value):
        if type(value) is not bool or not self._allowed() or self._closing:
            raise PermissionError('blackbox settings unavailable')
        self.persist(value)
        self.enabled = value
        self._failed_target = None
        if value:
            self.error = None
        if not value and self.producer:
            self.producer.request_stop()

    def set_retention(self, duration_us):
        if not self._allowed() or self._closing or type(duration_us) is not int or duration_us <= 0:
            raise ValueError('positive retention and blackbox access required')
        self._retention = duration_us
        for runtime in self.runtimes.values():
            runtime._retire_segments(runtime.session._replay.set_retention(duration_us))

    def _runtime(self, target):
        if target.session not in self.runtimes:
            s = self.settings
            if len(self.runtimes) >= s.max_entries:
                raise RuntimeError('session metadata bound reached; originals preserved')
            replay = ReplayBuffer(target.session, max_bytes=s.max_buffer_bytes, max_segments=s.max_segments,
                                  max_saves=2, retention_us=self._retention)
            session = BlackboxSession(replay, enabled=True, persist_enabled=lambda value: None,
                                      creator_check=self.allowed)
            self.runtimes[target.session] = BlackboxRuntime(session, self.budget,
                max_output_bytes=s.max_output_bytes, encode=self.codec.encode, validate=self.codec.validate,
                retire=self.spool.retire, creator_check=self.allowed, queue=self.queue)
        return self.runtimes[target.session]

    def tick(self, target, *, active: bool):
        """状態 events와 worker 결과를 직렬화. 캡처 API/인코더 대기를 UI에서 하지 않는다."""
        should_run = self.enabled and self._allowed() and not self._closing and target is not None and active
        if self.producer is not None:
            if not should_run or target != self._producer_target:
                self.producer.request_stop()
            while True:
                try:
                    kind, item = self.producer.results.get_nowait()
                except Empty:
                    break
                if kind == 'segment':
                    try:
                        retired = self.current.session.append(self._permit, item)
                        self.current._retire_segments(retired)
                    except Exception as exc:
                        retained = False
                        for runtime, reservation, stamp in self._pending.values():
                            if runtime is self.current and item.start_us < stamp:
                                try:
                                    runtime.retain_reserved(reservation, item)
                                    retained = True
                                except Exception:
                                    pass
                        if not retained:
                            self.error = f'captured segment retained for recovery: {exc}'
                        self.producer.request_stop()
                else:
                    token, stamp = item
                    if token in self._pending:
                        self._finish_pending(token)
            if self.producer.is_stopped():
                if self.producer.error:
                    if getattr(self.producer, 'transition', False):
                        self._failed_target = None
                    else:
                        self.error = self.producer.error
                        self._failed_target = self._producer_target
                self.producer = None
                for token in tuple(self._pending):
                    self._finish_pending(token)
            else:
                self.status = ('recording' if self.current.session.state.value == 'recording' else 'preparing') if should_run else 'pausing'
        if self.producer is None:
            if self.current is not None:
                self.current.session.update_context(CaptureContext())
            if not should_run:
                self.status = ('waiting' if target is None else 'paused') if self.enabled else 'disabled'
                if target is None:
                    self._failed_target = None
            elif target != self._failed_target:
                self.current = self._runtime(target)
                self.current.session.update_context(CaptureContext(target.session, foreground=True, ready=True))
                self._permit = self.current.session.capture_permit()
                limits = self.settings.producer
                bounds = {} if limits.max_input_width is None else dict(
                    max_output=(limits.max_width, limits.max_height),
                    max_input=(limits.max_input_width, limits.max_input_height))
                # 블랙박스 11.4: 소리 없는 상주 인코더 녹화는 GPU 색 변환(NV12)으로 받아 인코더 CPU를 줄인다.
                if not self.settings.audio and hasattr(self.codec, 'open_stream'):
                    bounds['pixel_format'] = 'nv12'
                native = self._native_factory(self.settings.library, max_frame_bytes=limits.max_frame_bytes,
                                               cursor=self.settings.cursor, **bounds, **(self.settings.audio or {}))
                producer = self._producer_factory(target, native, self.codec, self.spool,
                                                   self.settings.producer, allowed=self._allowed)
                self.producer, self._producer_target = producer, target
                producer.start()
                self.status = 'preparing'
            else:
                self.status = 'error'
        # 완료 파일은 제어 스레드가 인수. 복구 partial이 있으면 명시적 처리까지 유지.
        for runtime in self.runtimes.values():
            for ticket in runtime.tickets:
                result = self.queue.result(ticket)
                if result is not None and result.completed:
                    try:
                        result = runtime.accept_completed(ticket)
                        self.completed.append(('saved', result))
                    except RuntimeError:
                        pass
        # 알림은 UI가 drain한다. 오류 폭주로 메모리를 늘리지 않는다.
        del self.completed[:-100]

    def request_save(self, request_us, output=None):
        if not self._allowed() or self._closing or self.current is None:
            raise PermissionError('save unavailable')
        if self.current.session._replay.available_us < self.settings.min_save_us:
            # 녹화가 막 시작됐거나 중단돼 보관분이 거의 없을 때 0초짜리 파일을 만들지 않는다(0.13.1 실사용).
            if getattr(self, 'status', None) == 'error' and self.current.session._replay.available_us <= 0:
                # 녹화 오류로 한 구간도 없으면 '짧아요'가 아니라 오류를 알린다(0.15.0 인코더 시작 실패 실게임).
                raise TooShortToSave('녹화 오류로 저장할 영상이 없어요 · 앱에서 확인해 주세요.', recording_error=True)
            raise TooShortToSave('저장할 영상이 너무 짧아요 · 1초 이상 보관된 뒤 다시 저장해 주세요.')
        if len(self._pending) + sum(len(r.tickets) for r in self.runtimes.values()) >= 2:
            raise RuntimeError('one active and one queued save already reserved')
        output = Path(output) if output else self.settings.output_folder / f'blackbox-{uuid.uuid4().hex}.mp4'
        if self.producer is not None:
            token = uuid.uuid4().hex
            reservation = self.current.reserve_save(request_us, output)
            self._pending[token] = (self.current, reservation, request_us)
            try:
                self.producer.request_flush(token, request_us)
            except BaseException:
                self._pending.pop(token)
                self.current.cancel_reserved(reservation)
                raise
            return token
        return self.current.request_save(request_us, output)

    def _finish_pending(self, token):
        runtime, reservation, _ = self._pending.pop(token)
        try:
            ticket = runtime.complete_reserved(reservation)
            self.completed.append(('accepted', ticket))
        except Exception as exc:
            if reservation in runtime._pending:
                runtime.cancel_reserved(reservation)
            self.completed.append(('rejected', str(exc)))

    def retry_cleanup(self) -> int:
        """정리 대기 원본을 다시 지운다(미완성 캡처 자료는 명시적 폐기 대상이라 건드리지 않음)."""
        return sum(runtime.retry_cleanup() or 0 for runtime in self.runtimes.values())

    def orphan_sources(self):
        if self.producer is not None:
            return ()
        owned = {segment.source for runtime in self.runtimes.values()
                 for segment in runtime.session._replay._owned}
        owned.update(segment.source for runtime in self.runtimes.values() for segment in runtime._pending_retired)
        return tuple(source for source in self.spool.sources if source not in owned)

    def request_saved_session(self, session_id, request_us):
        if not self._allowed() or self._closing:
            raise PermissionError('new save unavailable')
        runtime = self.runtimes[session_id]
        if runtime is self.current:
            return self.request_save(request_us)
        output = self.settings.output_folder / f'blackbox-{uuid.uuid4().hex}.mp4'
        return runtime.request_save(request_us, output)

    def recoveries(self):
        return [(r, ticket, self.queue.result(ticket)) for r in self.runtimes.values()
                for ticket in r.tickets] + [(r, token, None) for token, (r, _, _) in self._pending.items()]

    def cancel_save(self, runtime, ticket):
        # 이미 접수된 작업의 중단/보호는 권한 해제 뒤에도 가능하다.
        if ticket in self._pending:
            owner, reservation, _ = self._pending[ticket]
            if owner is not runtime:
                raise ValueError('save owner mismatch')
            del self._pending[ticket]
            runtime.cancel_reserved(reservation)
            self.completed.append(('cancelled', '저장 요청을 중단했어요. 보관 중인 영상은 유지해요.'))
            return True
        if runtime not in self.runtimes.values() or ticket not in runtime.tickets:
            raise ValueError('unknown save')
        accepted = self.queue.cancel(ticket)
        if accepted:
            self.completed.append(('cancelled', '저장 중단을 요청했어요. 처리 후 실패 자료는 복구 화면에서 확인하세요.'))
        return accepted

    def close_wait_reason(self):
        """종료가 안 끝난 이유: 'capture'(녹화 중지 진행 중뿐 — 잠시 뒤 자동으로 끝남) | 'save'(저장 대기·결과 미인수) | None."""
        if self._pending or any(r.queue.result(t) is None for r in self.runtimes.values() for t in r.tickets):
            return 'save'
        if self.producer:
            return 'capture'
        return None

    def prepare_close(self):
        self._closing = True
        if self.producer:
            self.producer.request_stop()
            return False  # tick이 유효한 기존 segment/flush 결과를 먼저 인수
        if self._closed:
            return True
        # 진행 중인 저장은 결과가 나올 때까지 기다린다(성공할 수 있는 영상을 버리지 않는다).
        if self._pending or any(r.queue.result(t) is None for r in self.runtimes.values() for t in r.tickets):
            return False
        # 앱을 닫으면 다시 저장할 원본 버퍼가 사라지므로, 실패·미완성 자료는 묻지 않고 지운다
        # (2026-10-23 사용자 결정). 이미 저장한 영상은 지우지 않는다. 지우기 실패는 종료를 막지 않고
        # 다음 실행 시작 때 clean_leftovers가 다시 정리한다.
        leftover = []
        for runtime in self.runtimes.values():
            for ticket in runtime.tickets:
                try:
                    if runtime.queue.result(ticket).completed:
                        runtime.queue.discard_partial(ticket)  # 저장 완료·정리 대기
                        runtime.accept_completed(ticket)
                    else:
                        runtime.discard_failed(ticket)
                except Exception as exc:
                    leftover.append(f'저장 자료: {exc}')
        try:
            for runtime in self.runtimes.values():
                runtime.begin_close()
            self.queue.begin_close()
            for runtime in self.runtimes.values():
                if not runtime.finish_close():
                    leftover.append('저장 큐 정리 대기')
            if not self.queue.finish_close():
                leftover.append('저장 큐 정리 대기')
            for source in self.spool.sources:  # 남은 미완성 캡처 자료(영상으로 쓸 수 없음)
                try:
                    self.spool.discard(source)
                except Exception as exc:
                    leftover.append(f'미완성 자료: {exc}')
            self.spool.close()
        except Exception as exc:
            leftover.append(str(exc))
        if leftover:
            _log.warning('블랙박스 임시 자료 일부를 지우지 못했어요(다음 실행에서 다시 정리): %s', leftover)
        self._closed = True
        return True
