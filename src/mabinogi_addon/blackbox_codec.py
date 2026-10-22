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

    def __post_init__(self):
        if self.encoder not in ('h264_nvenc', 'h264_qsv', 'h264_amf', 'h264_mf', 'libx264'):
            raise ValueError('explicit supported H.264 encoder required')
        if any(type(v) is not int or v <= 0 for v in (self.bitrate, self.fps)):
            raise ValueError('positive bitrate/fps required')
        if type(self.tolerance_us) is not int or self.tolerance_us < 0:
            raise ValueError('explicit nonnegative boundary tolerance required')
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError('finite timeout required')
        if not all(Path(p).is_absolute() and Path(p).is_file() for p in (self.ffmpeg, self.ffprobe)):
            raise ValueError('explicit existing absolute codec binaries required')


def seconds(us):
    return f'{us // 1_000_000}.{us % 1_000_000:06d}'


class FFmpegEncoder:
    def __init__(self, settings: CodecSettings, resolve):
        self.settings, self.resolve = settings, resolve

    def _output(self, audio=False):
        s = self.settings
        audio_args = []
        if audio:
            if type(s.audio_bitrate) is not int or s.audio_bitrate <= 0:
                raise ValueError('explicit audio bitrate required')
            audio_args = ['-c:a', 'aac', '-b:a', str(s.audio_bitrate)]
        hardware = ['-hw_encoding', '1'] if s.encoder == 'h264_mf' else []
        pixel_format = 'nv12' if s.encoder == 'h264_mf' else 'yuv420p'
        return [*audio_args, '-r', str(s.fps), '-c:v', s.encoder, *hardware, '-b:v', str(s.bitrate), '-threads', '1', '-bf', '0',
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
        command += self._output(audio=audio)
        stream_process(command, sink, timeout=self.settings.timeout, chunks=(manifest,), host=self.settings.host)

    def validate(self, path, plan):
        output = io.BytesIO()
        stream_process([str(self.settings.ffprobe), '-v', 'error',
            '-show_entries', 'stream=codec_type,start_time,duration,width,height', '-of', 'json', str(path)],
            ByteSink(output, 65536), timeout=self.settings.timeout, host=self.settings.host)
        streams = json.loads(output.getvalue())['streams']
        videos = [s for s in streams if s.get('codec_type') == 'video']
        audios = [s for s in streams if s.get('codec_type') == 'audio']
        expects_audio = plan.slices[0].segment.format_key.endswith(':audio')
        if len(videos) != 1 or len(audios) != int(expects_audio) or len(streams) != 1 + int(expects_audio):
            raise ValueError('encoded video/audio streams differ from requested format')
        if int(videos[0]['width']) > 1920 or int(videos[0]['height']) > 1080:
            raise ValueError('video exceeds 1080p bounds')
        if any(abs(float(s.get('start_time', 0))) * 1_000_000 > self.settings.tolerance_us for s in streams):
            raise ValueError('stream start offset exceeds explicit tolerance')
        if expects_audio:
            audio_duration = float(audios[0]['duration']) * 1_000_000
            if not math.isfinite(audio_duration) or abs(audio_duration - plan.duration_us) > self.settings.tolerance_us:
                raise ValueError('audio duration exceeds explicit tolerance')
        actual = float(videos[0]['duration']) * 1_000_000
        if not math.isfinite(actual) or abs(actual - plan.duration_us) > self.settings.tolerance_us:
            raise ValueError('encoded duration exceeds explicit tolerance')
        # 실제 디코딩 실패도 완료로 표시하지 않는다.
        stream_process([str(self.settings.ffmpeg), '-v', 'error', '-nostdin', '-xerror', '-err_detect', 'explode', '-i', str(path),
            '-map', '0:v:0', '-map', '0:a?', '-f', 'null', '-'], ByteSink(io.BytesIO(), 1), timeout=self.settings.timeout, host=self.settings.host)
