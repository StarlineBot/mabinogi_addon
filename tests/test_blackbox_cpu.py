"""블랙박스 11.4: 녹화 CPU 절감(GPU NV12 색 변환·복사 1회·ffmpeg 변환 제거)과 앱+인코더 CPU 진단."""
from test_support.blackbox_codec import codec_host, codec_tools
import ctypes as C
import logging
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from mabinogi_addon.blackbox_codec import CodecSettings, FFmpegEncoder
from mabinogi_addon.system import process_threads
from mabinogi_addon.system.blackbox_capture import NativeCapture, frame_bytes

import test_blackbox_stream as stream_tests

ROOT = Path(__file__).resolve().parents[1]


# ---- 네이티브 DLL 소비자(ctypes) ----

def _capture(video, frame_format=None, limit=64):
    capture = NativeCapture(Path('unused.dll'), max_frame_bytes=limit, cursor=False, pixel_format='nv12')
    capture._dll = SimpleNamespace(bb_read=video)
    capture._video = C.c_void_p(1)
    capture._buffer = C.create_string_buffer(bytes(range(limit)), limit)
    capture._frame_format = frame_format
    return capture


def _video(width, height):
    def video(handle, output, capacity, w, h, stamp):
        w._obj.value, h._obj.value, stamp._obj.value = width, height, 1230
        return 0
    return video


def test_nv12_frame_is_w_h_3_2_bytes_and_marked():
    # 4×4 NV12 = Y 16 + UV 8 = 24바이트(BGRA면 64). 버퍼에서 필요한 만큼만 한 번 복사한다.
    capture = _capture(_video(4, 4), frame_format=lambda handle: 1)
    data, width, height, stamp, pixel_format = capture.read()
    assert (len(data), width, height, stamp, pixel_format) == (24, 4, 4, 123, 'nv12')
    assert data == bytes(range(24))


def test_old_dll_or_gpu_fallback_keeps_bgra_four_tuple():
    # 구버전 DLL(bb_frame_format 없음)·NV12 미지원 GPU(형식 0)는 이전과 같은 BGRA 4개 값
    assert _capture(_video(4, 4)).read() == (bytes(range(64)), 4, 4, 123)
    assert _capture(_video(4, 4), frame_format=lambda handle: 0).read() == (bytes(range(64)), 4, 4, 123)


@pytest.mark.parametrize('size, fmt', [((5, 4), 1), ((4, 4), 7)])
def test_nv12_odd_size_or_unknown_format_is_rejected(size, fmt):
    with pytest.raises(OSError, match='invalid native frame bounds'):
        _capture(_video(*size), frame_format=lambda handle: fmt).read()


def test_frame_bytes_and_format_argument():
    assert frame_bytes(1920, 1080) == 1920 * 1080 * 4
    assert frame_bytes(1920, 1080, 'nv12') == 1920 * 1080 * 3 // 2  # 파이프 양 62.5% 감소
    with pytest.raises(ValueError):
        NativeCapture(Path('x.dll'), max_frame_bytes=64, cursor=False, pixel_format='yuv420p')


def test_native_source_converts_on_gpu_and_reuses_staging():
    native = (ROOT / 'native/blackbox/capture.cpp').read_text(encoding='utf-8')
    assert 'BB HRESULT __cdecl bb_set_format' in native and 'BB int __cdecl bb_frame_format' in native
    assert 'DXGI_FORMAT_NV12' in native and 'CheckVideoProcessorFormat(out_format' in native
    assert 'YCbCr_Matrix = 1' in native and 'D3D11_VIDEO_PROCESSOR_NOMINAL_RANGE_16_235' in native
    assert 'VideoProcessorSetStreamAutoProcessingMode(s.processor.get(), 0, FALSE)' in native
    read = native[native.index('BB HRESULT __cdecl bb_read'):native.index('BB void __cdecl bb_close')]
    # 축소 없는 BGRA 경로도 프레임마다 스테이징 텍스처를 새로 만들지 않는다
    assert 'c.copy_staging' in read and 'com_ptr<ID3D11Texture2D> staging;' in read
    assert read.count('CreateTexture2D') == 1 and 'if (!c.copy_staging' in read
    # NV12 실패 시 CPU 축소가 아니라 BGRA(이전 방식)로 내려가고 형식으로 알린다
    assert 'c.nv12_failed = true;' in read and 'c.frame_format = format;' in read


# ---- 인코더 명령 ----

def _encoder(name='h264_nvenc'):
    encoder = FFmpegEncoder.__new__(FFmpegEncoder)
    encoder.settings = SimpleNamespace(ffmpeg=Path('ffmpeg.exe'), fps=60, bitrate=12_000_000, audio_bitrate=None)
    encoder.encoder = lambda: name
    return encoder


def test_nv12_stream_command_has_no_cpu_scale_or_conversion():
    command = _encoder().stream_command(1920, 1080, 15, pixel_format='nv12')
    assert command[command.index('-pix_fmt') + 1] == 'nv12'  # 입력
    assert command[len(command) - 1 - command[::-1].index('-pix_fmt') + 1] == 'nv12'  # 출력도 NV12 → 변환 없음
    assert '-vf' not in command
    assert command[command.index('-colorspace') + 1] == 'bt709' and command[command.index('-color_range') + 1] == 'tv'
    assert command.index('-colorspace') < command.index('-i')  # 입력 표시(캡처 DLL 변환과 같은 색 기준)
    legacy = _encoder().stream_command(1920, 1080, 15)
    assert '-vf' in legacy and legacy[legacy.index('-pix_fmt') + 1] == 'bgra'
    # 0.17.1 권장 수정: BGRA 경로도 BT.709·제한 범위로 변환하고 출력에 같은 색 표시(입력 표시는 없음 — 입력은 RGB)
    assert legacy[legacy.index('-vf') + 1].endswith(':out_color_matrix=bt709:out_range=tv')
    assert legacy.index('-i') < legacy.index('-colorspace') and legacy[legacy.index('-colorspace') + 1] == 'bt709'
    assert legacy[legacy.index('-color_range') + 1] == 'tv'
    with pytest.raises(ValueError):
        _encoder().stream_command(64, 48, 15, pixel_format='rgb24')


def test_real_ffmpeg_nv12_stream_keeps_colors_and_tags_bt709(tmp_path):
    settings = CodecSettings(*codec_tools(), 'libx264', 500000, 60, 30, 50000, host=codec_host())
    encoder = FFmpegEncoder(settings, lambda key: None)
    w, h = 64, 48
    # BT.709 제한 범위 NV12: 빨강(Y 63, U 102, V 240), 파랑(Y 32, U 240, V 118)
    def nv12(y, u, v):
        return bytes([y]) * (w * h) + bytes([u, v]) * (w * h // 4)
    red, blue = nv12(63, 102, 240), nv12(32, 240, 118)
    fragments = []
    stream = encoder.open_stream(w, h, 15, lambda data, frames: fragments.append((data, frames)), pixel_format='nv12')
    for frame in [red] * 15 + [blue] * 15:
        stream.write(frame)
    stream.finish(30)
    assert [frames for _, frames in fragments] == [15, 15]
    path = tmp_path / 'seg.mp4'
    path.write_bytes(fragments[1][0])
    probe = subprocess.check_output([str(settings.ffprobe), '-v', 'error', '-show_entries',
                                     'stream=width,height,color_space,color_range', '-of', 'csv=p=0', str(path)], text=True)
    assert probe.strip().split(',') == ['64', '48', 'tv', 'bt709']
    first = tmp_path / 'first.mp4'
    first.write_bytes(fragments[0][0])
    rgb = subprocess.check_output([str(settings.ffmpeg), '-v', 'error', '-i', str(first), '-frames:v', '1', '-f', 'rawvideo',
                                   '-pix_fmt', 'rgb24', 'pipe:1'], timeout=20)
    r, g, b = rgb[len(rgb) // 2:len(rgb) // 2 + 3]
    assert r > 200 and g < 60 and b < 60


# ---- 생산자: NV12 전달·형식 변경 ----

class FormatCodec(stream_tests.StreamCodec):
    def open_stream(self, width, height, gop, on_fragment, pixel_format='bgra'):
        self.formats = getattr(self, 'formats', []) + [pixel_format]
        return super().open_stream(width, height, gop, on_fragment)


def _nv12_frames(stamps, fmt='nv12'):
    size = frame_bytes(4, 4, fmt)
    return [(bytes([n]) * size, 4, 4, stamp, *(('nv12',) if fmt == 'nv12' else ())) for n, stamp in enumerate(stamps)]


def test_producer_sends_nv12_to_resident_encoder_and_restarts_on_bgra_fallback(caplog):
    caplog.set_level(logging.INFO)
    codec = FormatCodec()
    frames = _nv12_frames([100_000 * n for n in range(1, 7)]) + _nv12_frames([100_000 * n for n in range(7, 10)], 'bgra')
    producer = stream_tests._producer(frames, codec)
    results = []
    producer.start()
    stream_tests._drain(producer, results, lambda: len(codec.formats if hasattr(codec, 'formats') else ()) == 2, 2)
    producer.request_stop()
    stream_tests._drain(producer, results, producer.is_stopped)
    while not producer.results.empty():
        results.append(producer.results.get_nowait())
    assert producer.error is None
    assert codec.formats == ['nv12', 'bgra'] and producer.restarts == 1
    assert sum(kind == 'segment' for kind, _ in results) == 3
    messages = ' '.join(r.getMessage() for r in caplog.records)
    assert '캡처 형식 nv12 4×4(GPU 색 변환)' in messages and 'GPU 색 변환(NV12) 불가' in messages
    assert '캡처 형식 변경' in messages


def test_producer_rejects_nv12_frame_with_wrong_length():
    frames = [(bytes(23), 4, 4, 100_000, 'nv12')]
    producer = stream_tests._producer(frames, FormatCodec())
    producer.start()
    stream_tests._drain(producer, [], lambda: producer.error is not None)
    producer.request_stop()
    assert 'native frame exceeds bound' in producer.error


def test_service_requests_nv12_only_for_silent_resident_encoder():
    service = (ROOT / 'src/mabinogi_addon/blackbox_service.py').read_text(encoding='utf-8')
    block = service[service.index('# 블랙박스 11.4'):service.index('producer = self._producer_factory')]
    assert "if not self.settings.audio and hasattr(self.codec, 'open_stream'):" in block
    assert "bounds['pixel_format'] = 'nv12'" in block


# ---- CPU 진단(작업 관리자 기준: 전체 논리 코어 = 100%) ----

def _process_buffer(rows):
    """rows: [(pid, parent, user, kernel)] → SystemProcessInformation 모양 버퍼(스레드 없음)."""
    data = bytearray(256 * len(rows))
    for index, (pid, parent, user, kernel) in enumerate(rows):
        at = index * 256
        struct.pack_into('<II', data, at, 0 if index == len(rows) - 1 else 256, 0)
        struct.pack_into('<qq', data, at + 40, user, kernel)
        struct.pack_into('<QQ', data, at + 80, pid, parent)
    return bytes(data)


def test_process_tree_cpu_counts_app_children_and_encoder_grandchild():
    second = 10_000_000
    samples = iter([
        _process_buffer([(10, 1, 0, 0), (20, 10, 0, 0), (30, 20, 0, 0), (40, 1, 0, 0)]),
        # 1초 동안: 앱 0.1초, 인코더 호스트 0, ffmpeg(손자) 0.3초, 관계없는 프로세스 5초. 새 하위 프로세스 0.05초
        _process_buffer([(10, 1, second // 10, 0), (20, 10, 0, 0), (30, 20, second * 2 // 10, second // 10),
                         (40, 1, 5 * second, 0), (50, 10, second // 20, 0)]),
    ])
    clock = iter([0.0, 1.0])
    meter = process_threads.ProcessTreeCpu(source=lambda: next(samples), clock=lambda: next(clock), cores=16)
    assert meter.sample(10, 20) is None
    used = meter.sample(10, 20)
    assert used['encoder'] == pytest.approx(0.3 / 16 * 100)
    assert used['total'] == pytest.approx(0.45 / 16 * 100)  # 앱+인코더 합계(하위 포함), 관계없는 프로세스 제외
    # 0.17.2: 프로세스별 — 앱 본체 0.1초, 그 밖의 하위(FPS 수집기 등) 0.05초
    assert used['app'] == pytest.approx(0.1 / 16 * 100) and used['other'] == pytest.approx(0.05 / 16 * 100)


def test_tree_ignores_self_parent_and_missing_root():
    table = process_threads.process_times(_process_buffer([(0, 0, 0, 0), (4, 0, 0, 0), (8, 4, 0, 0)]))
    assert process_threads.tree(table, 4) == {4, 8}
    assert process_threads.tree(table, 99) == set() and process_threads.tree(table, None) == set()


class Meter:
    def __init__(self, values): self.values, self.calls = list(values), []
    def sample(self, app, encoder):
        self.calls.append(encoder)
        return self.values.pop(0) if self.values else None


@pytest.mark.parametrize('used, verdict', [((4.2, 1.5, 2.0, 0.7), '합격선 이내'), ((8.6, 2.0, 5.8, 0.8), '합격선 초과')])
def test_summary_reports_app_plus_encoder_against_pass_line(used, verdict):
    # 0.17.2: 합계와 함께 앱 본체·인코더·FPS 수집기 등으로 나눠 남긴다
    producer = stream_tests._producer([], FormatCodec())
    producer._cpu_meter = Meter([dict(zip(('total', 'app', 'encoder', 'other'), used))])
    text = producer._diagnostics()
    assert (f'앱+인코더 합계 {used[0]:.1f}%(앱 본체 {used[1]:.1f}% · 인코더 {used[2]:.1f}% · '
            f'FPS 수집기 등 {used[3]:.1f}%)') in text and f'{verdict}(최대 5%)' in text


def test_cpu_meter_failure_never_stops_recording():
    class Broken:
        def sample(self, app, encoder): raise OSError('NtQuerySystemInformation 실패')
    producer = stream_tests._producer([], FormatCodec())
    producer._cpu_meter = Broken()
    assert 'CPU' not in producer._diagnostics() and producer._cpu_meter is None


def test_real_ffmpeg_bgra_stream_uses_same_color_basis_as_nv12(tmp_path):
    # 0.17.1 QA(qa_0171 중간 전환 색 오차 40): NV12 구간 뒤 BGRA 구간이 붙은 저장 영상에서 BGRA 구간 색이 틀어지지 않게
    settings = CodecSettings(*codec_tools(), 'libx264', 500000, 60, 30, 50000, host=codec_host())
    encoder = FFmpegEncoder(settings, lambda key: None)
    red = bytes((0, 0, 255, 255)) * (64 * 48)
    fragments = []
    stream = encoder.open_stream(64, 48, 15, lambda data, frames: fragments.append(data))
    for _ in range(15):
        stream.write(red)
    stream.finish(30)
    path = tmp_path / 'bgra.mp4'
    path.write_bytes(fragments[0])
    probe = subprocess.check_output([str(settings.ffprobe), '-v', 'error', '-show_entries', 'stream=color_space,color_range',
                                     '-of', 'csv=p=0', str(path)], text=True)
    assert probe.strip().split(',') == ['tv', 'bt709']
    yuv = subprocess.check_output([str(settings.ffmpeg), '-v', 'error', '-i', str(path), '-frames:v', '1', '-f', 'rawvideo',
                                   '-pix_fmt', 'yuv420p', 'pipe:1'], timeout=20)
    y = yuv[64 * 24 + 32]
    assert abs(y - 63) <= 2  # BT.709 빨강 Y=63 (BT.601이면 81)
