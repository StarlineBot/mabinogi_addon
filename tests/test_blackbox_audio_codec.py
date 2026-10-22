from test_support.blackbox_codec import codec_host
import io
from pathlib import Path
import shutil
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
    with pytest.raises(ValueError, match='gap'):
        timeline.push(b'\x00\x00', 25000)
    timeline.close()
    with pytest.raises(ValueError, match='incomplete'):
        timeline.slice(15000, 25000, timeout=1)


def test_audio_budget_and_closed_timeline():
    timeline = PcmTimeline(1000, 1, 4)
    timeline.push(b'1234', 0)
    with pytest.raises(BufferError):
        timeline.push(b'12', 2000)
    timeline.close()
    with pytest.raises(RuntimeError):
        timeline.push(b'12', 2000)


def test_real_synthetic_video_audio_encoding_trim_and_decode(tmp_path):
    settings = CodecSettings(Path(shutil.which('ffmpeg')), Path(shutil.which('ffprobe')),
        'libx264', 100000, 10, 10, 100000, audio_bitrate=64000, host=codec_host())
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
    settings = CodecSettings(Path(shutil.which('ffmpeg')), Path(shutil.which('ffprobe')),
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
