"""명시적 FFmpeg 바이너리를 사용하는 유한 스트리밍 어댑터. 바이너리를 동봉/다운로드하지 않는다.

코덱/비트레이트/오차/시간 제한은 필수 입력이다. FFmpeg 빌드와 재배포 라이선스는 별도 검토한다.
전체 구간 재인코딩으로 경계를 맞춘다. 경계 외 무재인코딩 최적화는 하지 않는다.
"""
from dataclasses import dataclass
import io
import json
import logging
import math
import os
import signal
import sys
from pathlib import Path
import subprocess
import threading
import time

from .blackbox_export import ByteSink

_log = logging.getLogger(__name__)


def stream_process(command, sink, *, timeout: float, chunks=(), host=None):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('finite positive encoder timeout required')
    if type(chunks) not in (tuple, list) or any(type(chunk) is not bytes for chunk in chunks):
        raise TypeError("finite bytes sequence required")
    sink.check_cancelled()
    if sys.platform == 'win32':
        if host is None or not Path(host).is_absolute() or not Path(host).is_file():
            raise ValueError('built Windows codec host required for process-tree lifetime')
        command = [str(host), *command]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, shell=False, start_new_session=sys.platform != 'win32',
        creationflags=0x08000000 if sys.platform == 'win32' else 0)
    errors, diagnostic = [], bytearray()
    lock = threading.Lock()
    def output():
        try:
            while chunk := process.stdout.read(65536):
                sink.write(chunk)
        except BaseException as exc:
            errors.append(exc)
    def input_():
        try:
            for chunk in chunks:
                sink.check_cancelled()
                if type(chunk) is not bytes:
                    raise TypeError('encoder input must be bytes')
                process.stdin.write(chunk)
            process.stdin.close()
        except BaseException as exc:
            errors.append(exc)
    def stderr():
        try:
            while chunk := process.stderr.read(4096):
                with lock:
                    diagnostic.extend(chunk)
                    del diagnostic[:-8192]
        except OSError as exc:
            errors.append(exc)
    threads = [threading.Thread(target=fn, name='blackbox-codec-pipe') for fn in (output, input_, stderr)]
    deadline = time.monotonic() + timeout
    def exited():
        """인코더가 비정상 종료했으면 종료 코드·stderr 오류를 만든다(파이프 오류보다 우선).

        인코더가 먼저 죽으면 입력 스레드는 BrokenPipe를 받는다. 그 오류만 보이면 실제 원인
        (예: 하드웨어 인코더 초기화 실패)이 가려지므로 종료 코드와 진단을 먼저 확인한다."""
        try:
            process.wait(min(1.0, max(0.0, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            return None
        if not process.returncode:
            return None
        threads[2].join(min(1.0, max(0.0, deadline - time.monotonic())))  # stderr 수집 마무리
        with lock:
            text = diagnostic.decode(errors='replace').strip()
        _log.error('blackbox encoder exited %s: %s', process.returncode, text)
        return OSError(f'encoder exited {process.returncode}: {text}')
    try:
        for thread in threads:
            thread.start()
        while process.poll() is None:
            sink.check_cancelled()
            if errors:
                raise exited() or errors[0]
            if time.monotonic() >= deadline:
                raise TimeoutError('encoder deadline exceeded')
            time.sleep(0.02)
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads):
            raise TimeoutError('encoder pipe did not finish')
        sink.check_cancelled()
        if process.returncode:
            raise exited()
        if errors:
            raise errors[0]
    finally:
        if sys.platform != 'win32':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        process.wait()
        for pipe in (process.stdin, process.stdout, process.stderr):
            try:
                pipe.close()
            except OSError:
                pass
        for thread in threads:
            if thread.ident is not None:
                thread.join()


@dataclass(frozen=True)
class CodecSettings:
    ffmpeg: Path
    ffprobe: Path
    encoder: str
    bitrate: int
    fps: int
    timeout: float
    tolerance_us: int
    host: Path | None = None
    audio_bitrate: int | None = None
    # 하드웨어 인코더 후보(순서대로 시험 인코딩해 처음 열리는 것을 쓴다). 비우면 encoder 하나만 쓴다.
    candidates: tuple[str, ...] = ()

    def __post_init__(self):
        if self.encoder not in ('h264_nvenc', 'h264_qsv', 'h264_amf', 'h264_mf', 'libx264'):
            raise ValueError('explicit supported H.264 encoder required')
        object.__setattr__(self, 'candidates', tuple(self.candidates))
        if self.candidates and (any(c not in HARDWARE_ENCODERS for c in self.candidates)
                                or len(set(self.candidates)) != len(self.candidates)
                                or self.candidates[-1] != self.encoder):
            # 소프트웨어 인코더로 자동 전환하지 않는다(명세). 마지막 후보가 기본 encoder.
            raise ValueError('hardware encoder candidates ending with the configured encoder required')
        if any(type(v) is not int or v <= 0 for v in (self.bitrate, self.fps)):
            raise ValueError('positive bitrate/fps required')
        if type(self.tolerance_us) is not int or self.tolerance_us < 0:
            raise ValueError('explicit nonnegative boundary tolerance required')
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError('finite timeout required')
        if not all(Path(p).is_absolute() and Path(p).is_file() for p in (self.ffmpeg, self.ffprobe)):
            raise ValueError('explicit existing absolute codec binaries required')


HARDWARE_ENCODERS = ('h264_nvenc', 'h264_amf', 'h264_qsv', 'h264_mf')
_PROBE_SIZE = (320, 240)  # 하드웨어 인코더 최소 크기(NVENC 등)보다 큰 작은 시험 입력


def _last_line(text):
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    return lines[-1] if lines else str(text)


def seconds(us):
    return f'{us // 1_000_000}.{us % 1_000_000:06d}'


class FFmpegEncoder:
    def __init__(self, settings: CodecSettings, resolve):
        self.settings, self.resolve = settings, resolve
        self._lock = threading.Lock()
        self.selected = None if settings.candidates else settings.encoder
        self.attempts = {}  # 후보 → 실패 사유(마지막 시험 기준, 진단 표시용)
        # 진행 중인 저장(0.14.1 저장 진행 표시): dict(stage='encode'|'validate', duration_us, started, path) 또는 None.
        # 저장 작업은 한 번에 하나라 속성 하나로 충분하다. UI는 progress_snapshot()만 읽는다.
        self.progress = None

    def encoder(self):
        """사용할 인코더. 후보가 있으면 처음 한 번 시험 인코딩으로 고르고 실행 중 캐시한다.

        AMD 내장+NVIDIA 같은 다중 GPU에서 h264_mf(MFT 열거 첫 항목만 사용)가 엉뚱한 GPU의
        MFT를 골라 'could not set output type'으로 실패했다(0.11.3 실사용). 게임 GPU 제조사의
        전용 인코더를 먼저 시험한다(NVENC → AMF → MF). 모두 실패하면 후보별 오류로 중단한다."""
        with self._lock:
            if self.selected is not None:
                return self.selected
            for candidate in self.settings.candidates:
                started = time.perf_counter()
                try:
                    self._probe(candidate)
                except Exception as exc:  # noqa: BLE001 — 후보별 실패를 모아 보여준다
                    self.attempts[candidate] = _last_line(exc)
                    _log.info('블랙박스 인코더 시험 %s 실패 %.2f초', candidate, time.perf_counter() - started)
                    self._diagnose(candidate)
                    continue
                self.selected = candidate
                _log.info('블랙박스 인코더 선택: %s · 시험 %.2f초 (시험 실패: %s)', candidate,
                          time.perf_counter() - started, self.attempts or '없음')
                return candidate
            detail = '; '.join(f'{name}: {reason}' for name, reason in self.attempts.items())
            raise OSError('하드웨어 H.264 인코더를 열지 못했어요(소프트웨어 인코더로 대신하지 않아요) · ' + detail)

    def _probe_command(self, encoder, verbosity):
        width, height = _PROBE_SIZE
        return [str(self.settings.ffmpeg), '-v', verbosity, '-nostdin', '-xerror', '-f', 'rawvideo',
                '-pix_fmt', 'bgra', '-video_size', f'{width}x{height}', '-framerate', str(self.settings.fps),
                '-i', 'pipe:0', '-an', *self._output(encoder=encoder)]

    def _probe(self, encoder, verbosity='error'):
        width, height = _PROBE_SIZE
        frames = (bytes(width * height * 4),) * 2
        stream_process(self._probe_command(encoder, verbosity), ByteSink(io.BytesIO(), 1 << 20),
                       timeout=min(self.settings.timeout, 30), chunks=frames, host=self.settings.host)

    def _diagnose(self, encoder):
        """인코더 열기 실패 시 -v verbose로 1회 다시 돌려 MFT/장치 선택 로그를 app.log에 남긴다."""
        try:
            self._probe(encoder, 'verbose')
        except Exception as exc:  # noqa: BLE001
            _log.warning('블랙박스 인코더 %s 열기 실패 진단(-v verbose):\n%s', encoder, exc)
        else:
            _log.warning('블랙박스 인코더 %s: 첫 시험은 실패했지만 진단 재실행은 성공(일시 오류 가능)', encoder)

    def _output(self, audio=False, encoder=None):
        s = self.settings
        encoder = encoder or self.encoder()
        audio_args = []
        if audio:
            if type(s.audio_bitrate) is not int or s.audio_bitrate <= 0:
                raise ValueError('explicit audio bitrate required')
            audio_args = ['-c:a', 'aac', '-b:a', str(s.audio_bitrate)]
        hardware = ['-hw_encoding', '1'] if encoder == 'h264_mf' else []
        pixel_format = 'nv12' if encoder in HARDWARE_ENCODERS else 'yuv420p'
        return [*audio_args, '-r', str(s.fps), '-c:v', encoder, *hardware, '-b:v', str(s.bitrate), '-threads', '1', '-bf', '0',
                '-pix_fmt', pixel_format, '-movflags', 'frag_keyframe+delay_moov+default_base_moof',
                '-f', 'mp4', 'pipe:1']

    def encode_frames(self, frames, width, height, sink, *, audio_path=None):
        if width < 2 or height < 2:
            raise ValueError('source must have at least two pixels per dimension')
        chunks = tuple(frames)
        if not chunks or any(type(data) is not bytes or len(data) != width * height * 4 for data in chunks):
            raise ValueError('invalid BGRA frames')
        command = [str(self.settings.ffmpeg), '-v', 'error', '-nostdin', '-xerror', '-err_detect', 'explode', '-f', 'rawvideo',
            '-pix_fmt', 'bgra', '-video_size', f'{width}x{height}', '-framerate', str(self.settings.fps),
            '-i', 'pipe:0']
        command += ['-i', str(audio_path), '-map', '0:v:0', '-map', '1:a:0'] if audio_path else ['-an']
        command += ['-vf', "scale=w='min(1920,iw)':h='min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"]
        command += self._output(audio=audio_path is not None)
        stream_process(command, sink, timeout=self.settings.timeout, chunks=chunks, host=self.settings.host)

    def encode(self, plan, sink):
        # A concat input opens segments sequentially, avoiding Windows command-line
        # limits and thousands of concurrent decoder contexts for a ten-minute save.
        audio = plan.slices[0].segment.format_key.endswith(':audio')
        lines = ['ffconcat version 1.0']
        for part in plan.slices:
            path = Path(self.resolve(part.segment.source)).absolute().as_posix()
            if '\n' in path or '\r' in path:
                raise ValueError('newline in source path')
            quoted = ("file:" + path).replace("'", "'\\''")
            lines += ["file '" + quoted + "'",
                      'inpoint ' + seconds(part.offset_us),
                      'duration ' + seconds(part.duration_us)]
        manifest = ('\n'.join(lines) + '\n').encode('utf-8')
        if len(manifest) > 4 * 1024 * 1024:
            raise ValueError('concat manifest exceeds bound')
        command = [str(self.settings.ffmpeg), '-v', 'error', '-nostdin', '-xerror',
            '-err_detect', 'explode', '-threads', '1', '-copyts', '-f', 'concat', '-safe', '0',
            '-protocol_whitelist', 'file,pipe', '-segment_time_metadata', '1', '-i', 'pipe:0',
            '-map', '0:v:0', '-vf', 'select=concatdec_select,setpts=PTS-STARTPTS']
        if audio:
            command += ['-map', '0:a:0', '-af',
                'aselect=concatdec_select,aresample=async=1:first_pts=0,atrim=duration=' + seconds(plan.duration_us)]
        else:
            command += ['-an']
        import tempfile, uuid
        report = Path(tempfile.gettempdir()) / f'mabinogi-blackbox-progress-{uuid.uuid4().hex}.txt'
        command += ['-progress', str(report), '-stats_period', '0.5']  # 처리한 영상 시각(out_time_us)을 주기적으로 기록
        command += self._output(audio=audio)
        self.progress = dict(stage='encode', duration_us=plan.duration_us, started=time.monotonic(), path=report)
        try:
            stream_process(command, sink, timeout=self.settings.timeout, chunks=(manifest,), host=self.settings.host)
        finally:
            try:
                report.unlink(missing_ok=True)
            except OSError:
                pass

    def progress_snapshot(self):
        """(단계, 저장 분량 µs, 경과 초, 인코딩 진행 0~1 또는 None). 저장 중이 아니면 None."""
        progress = getattr(self, 'progress', None)
        if progress is None:
            return None
        fraction = None
        if progress['stage'] == 'encode':
            try:
                text = progress['path'].read_text(encoding='utf-8', errors='replace')
                times = [line.split('=', 1)[1] for line in text.splitlines() if line.startswith('out_time_us=')]
                if times and times[-1].strip().lstrip('-').isdigit():
                    fraction = max(0.0, min(1.0, int(times[-1]) / max(1, progress['duration_us'])))
            except OSError:
                pass
        return progress['stage'], progress['duration_us'], time.monotonic() - progress['started'], fraction

    def validate(self, path, plan):
        if getattr(self, 'progress', None) is not None:
            self.progress = dict(self.progress, stage='validate')
        try:
            return self._validate(path, plan)
        finally:
            self.progress = None

    def _validate(self, path, plan):
        output = io.BytesIO()
        stream_process([str(self.settings.ffprobe), '-v', 'error',
            '-show_entries', 'stream=codec_type,start_time,duration,width,height', '-of', 'json', str(path)],
            ByteSink(output, 65536), timeout=self.settings.timeout, host=self.settings.host)
        streams = json.loads(output.getvalue())['streams']
        videos = [s for s in streams if s.get('codec_type') == 'video']
        audios = [s for s in streams if s.get('codec_type') == 'audio']
        expects_audio = plan.slices[0].segment.format_key.endswith(':audio')
        def detail():  # 실패 원인 판정용(0.13.6 실사용: 길이 없이 '초과'만 남아 판정 불가)
            def seconds_of(items):
                return ', '.join(f"{float(s.get('duration', 'nan')):.3f}초" for s in items) or '없음'
            return (f' (영상 {seconds_of(videos)} · 소리 {seconds_of(audios)} · 계획 {plan.duration_us / 1_000_000:.3f}초'
                    f' · 구간 {len(plan.slices)}개 · 허용 {self.settings.tolerance_us / 1000:.0f}ms)')
        if len(videos) != 1 or len(audios) != int(expects_audio) or len(streams) != 1 + int(expects_audio):
            raise ValueError('encoded video/audio streams differ from requested format' + detail())
        if int(videos[0]['width']) > 1920 or int(videos[0]['height']) > 1080:
            raise ValueError('video exceeds 1080p bounds')
        if any(abs(float(s.get('start_time', 0))) * 1_000_000 > self.settings.tolerance_us for s in streams):
            raise ValueError('stream start offset exceeds explicit tolerance' + detail())
        if expects_audio:
            audio_duration = float(audios[0]['duration']) * 1_000_000
            if not math.isfinite(audio_duration) or abs(audio_duration - plan.duration_us) > self.settings.tolerance_us:
                raise ValueError('audio duration exceeds explicit tolerance' + detail())
        actual = float(videos[0]['duration']) * 1_000_000
        if not math.isfinite(actual) or abs(actual - plan.duration_us) > self.settings.tolerance_us:
            raise ValueError('encoded duration exceeds explicit tolerance' + detail())
        # 실제 디코딩 실패도 완료로 표시하지 않는다.
        stream_process([str(self.settings.ffmpeg), '-v', 'error', '-nostdin', '-xerror', '-err_detect', 'explode', '-i', str(path),
            '-map', '0:v:0', '-map', '0:a?', '-f', 'null', '-'], ByteSink(io.BytesIO(), 1), timeout=self.settings.timeout, host=self.settings.host)
