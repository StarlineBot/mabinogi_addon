from test_support.blackbox_codec import codec_host, codec_tools
import io
from pathlib import Path
import wave

import pytest

from mabinogi_addon.blackbox import Segment, SavePlan, Slice
from mabinogi_addon.blackbox_audio import PcmTimeline
from mabinogi_addon.blackbox_codec import CodecSettings, FFmpegEncoder
from mabinogi_addon.blackbox_export import ByteSink


def test_audio_slice_across_packets_and_missing_audio_is_not_filled():
    timeline = PcmTimeline(1000, 1, 100)
    timeline.push(b'\x01\x00' * 10, 0)
    timeline.push(b'\x02\x00' * 10, 10000)
    assert timeline.slice(5000, 15000, timeout=1) == b'\x01\x00' * 5 + b'\x02\x00' * 5
    # 0.13.1 실사용: 큰 공백은 녹화 중단 대신 새 연속 구간. 공백을 무음으로 채우지 않는다.
    timeline.push(b'\x00\x00', 25000)
    assert timeline.gaps == 1 and timeline.run_within(15000, 26000) == (15000, 20000)
    with pytest.raises(ValueError, match='overlap'):
        timeline.push(b'\x00\x00', 20000)  # 겹침은 계속 거부
    timeline.close()
    with pytest.raises(ValueError, match='incomplete'):
        timeline.slice(15000, 25000, timeout=1)


def test_loopback_jitter_within_tolerance_is_joined_sample_continuously():
    # 0.13.1 실사용: 루프백 QPC 지터(±1ms)로 'audio gap or overlap' 녹화 중단 → 0초 저장.
    timeline = PcmTimeline(48000, 1, 1 << 20)
    stamp = 1_000_000
    for n in range(50):  # 10ms 묶음, 시각은 ±1ms 흔들림
        timeline.push(b'\x01\x00' * 480, stamp + (1000 if n % 2 else -1000) * (n > 0))
        stamp += 10_000
    assert timeline.gaps == 0
    pcm = timeline.slice(1_000_000, 1_400_000, timeout=1)
    assert len(pcm) // 2 == 19200  # 400ms × 48kHz, 빈 샘플·중복 없음


def test_audio_budget_and_closed_timeline():
    timeline = PcmTimeline(1000, 1, 4)
    timeline.push(b'1234', 0)
    with pytest.raises(BufferError):
        timeline.push(b'12', 2000)
    timeline.close()
    with pytest.raises(RuntimeError):
        timeline.push(b'12', 2000)


def test_real_synthetic_video_audio_encoding_trim_and_decode(tmp_path):
    settings = CodecSettings(*codec_tools(),
        'libx264', 100000, 10, 30, 100000, audio_bitrate=64000, host=codec_host())  # 시한: 부하 시 여유
    audio = tmp_path / 'synthetic.wav'
    with wave.open(str(audio), 'wb') as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(48000)
        stream.writeframes(b'\x00\x00' * 48000)
    output = tmp_path / 'segment.mp4'
    encoder = FFmpegEncoder(settings, lambda key: output)
    with output.open('wb') as stream:
        encoder.encode_frames((b'\x00\x00\xff\xff' * 16,) * 10, 4, 4,
                              ByteSink(stream, 100000), audio_path=audio)
    segment = Segment('synthetic', 'one', 0, 1000000, output.stat().st_size, '4x4:10:audio')
    plan = SavePlan(800000, (Slice(segment, 200000, 600000),))
    clipped = tmp_path / 'clip.mp4'
    with clipped.open('wb') as stream:
        encoder.encode(plan, ByteSink(stream, 100000))
    encoder.validate(clipped, plan)
    bad = SavePlan(800000, (Slice(Segment('synthetic', 'one', 0, 1000000,
        output.stat().st_size, '4x4:10:video'), 200000, 600000),))
    with pytest.raises(ValueError, match='streams differ'):
        encoder.validate(clipped, bad)


def test_trimmed_bitrate_export_preserves_first_frame_and_fixed_fps(tmp_path):
    import subprocess
    settings = CodecSettings(*codec_tools(),
        'libx264', 100000, 60, 10, 25000, host=codec_host())
    source = tmp_path / "한글 clip's #1.mp4"
    codec = FFmpegEncoder(settings, lambda key: source)
    red, blue = b'\x00\x00\xff\xff' * 16, b'\xff\x00\x00\xff' * 16
    with source.open('wb') as output:
        codec.encode_frames([red] * 30 + [blue] * 30, 4, 4, ByteSink(output, 100000))
    first = Segment('s', 'one', 0, 1000000, source.stat().st_size, '4x4:60:video')
    second = Segment('s', 'two', 6000000, 7000000, source.stat().st_size, '4x4:60:video')
    plan = SavePlan(6500000, (Slice(first, 250000, 500000), Slice(second, 100000, 400000)))
    clip = tmp_path / 'trimmed.mp4'
    with clip.open('wb') as output:
        codec.encode(plan, ByteSink(output, 100000))
    codec.validate(clip, plan)
    raw = subprocess.check_output([str(settings.ffmpeg), '-v', 'error', '-i', str(clip),
        '-an', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'], timeout=10)
    colors = ['red' if raw[n] > raw[n+2] + 100 else 'blue' if raw[n+2] > raw[n] + 100
              else 'other' for n in range(0, len(raw), 48)]
    assert colors == ['red'] * 15 + ['blue'] * 15 + ['red'] * 24


@pytest.mark.parametrize('missing', [('ffmpeg',), ('ffprobe',), ('ffmpeg', 'ffprobe')])
def test_missing_synthetic_tools_report_required_dependencies(monkeypatch, missing):
    import test_support.blackbox_codec as support
    monkeypatch.setattr(support.shutil, 'which', lambda name: None if name in missing else '/tools/' + name)
    with pytest.raises(RuntimeError, match='synthetic tests require') as error:
        codec_tools()
    assert ', '.join(missing) + ' on PATH' in str(error.value)
    assert 'Ubuntu install the ffmpeg package' in str(error.value)


def test_synthetic_tools_preserve_resolved_paths(monkeypatch):
    import test_support.blackbox_codec as support
    monkeypatch.setattr(support.shutil, 'which', lambda name: '/tools with spaces/' + name)
    assert codec_tools() == (Path('/tools with spaces/ffmpeg'), Path('/tools with spaces/ffprobe'))


# --- 0.11.4: 하드웨어 인코더 후보 시험 선택 (가짜 ffmpeg) -----------------------------------------
import sys as _sys
import io as _io
import logging as _logging
import pytest as _pytest
from pathlib import Path as _Path


def _fake_ffmpeg(tmp_path, failing):
    """-c:v 값이 failing에 있으면 h264_mf 실패처럼 stderr를 쓰고 exit 1. 호출 인자를 기록한다."""
    log = tmp_path / 'calls.txt'
    script = tmp_path / 'ffmpeg'
    script.write_text(f'''#!{_sys.executable}
import sys
args = sys.argv[1:]
with open({str(log)!r}, 'a') as f: f.write(' '.join(args) + '\\n')
encoder = args[args.index('-c:v') + 1]
if encoder in {sorted(failing)!r}:
    if 'verbose' in args: sys.stderr.write('[h264_mf] MFT name: AMD H.264 Encoder MFT\\n')
    sys.stderr.write('[' + encoder + '] could not set output type (MF_E_UNSUPPORTED_D3D_TYPE)\\n')
    sys.exit(1)
sys.stdin.buffer.read(); sys.stdout.buffer.write(b'mp4')
''', encoding="utf-8")
    script.chmod(0o755)
    probe = tmp_path / 'ffprobe'; probe.write_text('#!/bin/sh\n', encoding="utf-8"); probe.chmod(0o755)
    return script, probe, log


def _encoder(tmp_path, failing, candidates=('h264_nvenc', 'h264_amf', 'h264_mf')):
    from mabinogi_addon.blackbox_codec import CodecSettings, FFmpegEncoder
    ffmpeg, ffprobe, log = _fake_ffmpeg(tmp_path, failing)
    settings = CodecSettings(ffmpeg, ffprobe, candidates[-1], 1_000_000, 60, 10, 50_000, candidates=candidates)
    return FFmpegEncoder(settings, lambda source: source), log


@_pytest.mark.skipif(_sys.platform == 'win32', reason='가짜 ffmpeg는 POSIX 스크립트')
def test_first_working_hardware_encoder_is_selected_and_cached(tmp_path, caplog):
    from mabinogi_addon.blackbox_export import ByteSink
    caplog.set_level(_logging.INFO)
    encoder, log = _encoder(tmp_path, {'h264_nvenc'})
    frames = (bytes(4 * 4 * 4),) * 2
    for _ in range(2):
        encoder.encode_frames(frames, 4, 4, ByteSink(_io.BytesIO(), 1 << 20))
    calls = log.read_text(encoding="utf-8").splitlines()
    assert [c.split('-c:v ')[1].split()[0] for c in calls] == ['h264_nvenc', 'h264_nvenc', 'h264_amf', 'h264_amf', 'h264_amf']
    assert sum('-v verbose' in c for c in calls) == 1  # 실패한 후보만 1회 진단 재실행
    assert encoder.selected == 'h264_amf' and 'h264_nvenc' in encoder.attempts
    assert '블랙박스 인코더 선택: h264_amf' in caplog.text and 'could not set output type' in caplog.text


@_pytest.mark.skipif(_sys.platform == 'win32', reason='가짜 ffmpeg는 POSIX 스크립트')
def test_all_hardware_encoders_failing_reports_each_without_software_fallback(tmp_path, caplog):
    from mabinogi_addon.blackbox_export import ByteSink
    caplog.set_level(_logging.WARNING)
    encoder, log = _encoder(tmp_path, {'h264_nvenc', 'h264_amf', 'h264_mf'})
    with _pytest.raises(OSError) as caught:
        encoder.encode_frames((bytes(64),), 4, 4, ByteSink(_io.BytesIO(), 1 << 20))
    message = str(caught.value)
    assert '소프트웨어 인코더로 대신하지 않아요' in message
    assert all(f'{name}: encoder exited 1: [{name}] could not set output type' in message for name in ('h264_nvenc', 'h264_amf', 'h264_mf'))
    assert 'libx264' not in log.read_text(encoding="utf-8") and encoder.selected is None
    assert 'MFT name: AMD H.264 Encoder MFT' in caplog.text  # verbose 진단이 app.log로


@_pytest.mark.parametrize('candidates', [('h264_mf', 'libx264'), ('h264_nvenc',), ('h264_mf', 'h264_mf')])
def test_candidates_must_be_hardware_and_end_with_encoder(tmp_path, candidates):
    from mabinogi_addon.blackbox_codec import CodecSettings
    ffmpeg = tmp_path / 'ffmpeg'; ffmpeg.write_text('', encoding="utf-8"); probe = tmp_path / 'ffprobe'; probe.write_text('', encoding="utf-8")
    with _pytest.raises(ValueError):
        CodecSettings(ffmpeg, probe, 'h264_mf', 1_000_000, 60, 10, 50_000, candidates=candidates)
