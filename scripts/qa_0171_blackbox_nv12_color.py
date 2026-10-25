"""0.17.1 블랙박스 NV12 입력(GPU 색 변환) 끝까지 재현: NV12 프레임 → 실제 CaptureProducer·상주 인코더 → 저장(concat 재인코딩)·검증 → 색 비교.

실행: uv run python -m scripts.qa_0171_blackbox_nv12_color
GPU(D3D11 비디오 프로세서) 대신 ffmpeg로 같은 규격(BT.709·제한 범위 16~235)의 NV12를 만들어 넣는다(캡처 DLL 출력 모형).
색 막대 8개(검정·흰색·빨강·초록·파랑·노랑·하늘·자주)를 저장 영상에서 다시 RGB로 풀어 원래 색과 비교한다.
- NV12 경로: 막대별 RGB 오차가 작아야 한다(색이 바래거나·진해지거나·색조가 틀어지지 않음).
- 대조: 이전 BGRA 경로(ffmpeg CPU 변환)도 같은 방식으로 잰다.
- 중간 전환: NV12로 녹화하다 BGRA로 내려온 경우(GPU NV12 불가) 인코더 재시작 뒤 저장 영상이 끝까지 이어지는지,
  전환 뒤 BGRA 구간 색도 맞는지(두 경로 색 기준 통일, 0.17.1 권장 수정 — 수정 전 오차 40).
시스템 ffmpeg(libx264)로 돈다(제품은 번들 8.1.3·NVENC). 실패하면 FAIL, 종료 코드 1.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from mabinogi_addon.blackbox import SavePlan, Slice  # noqa: E402
from mabinogi_addon.blackbox_codec import CodecSettings, FFmpegEncoder  # noqa: E402
from mabinogi_addon.blackbox_export import ByteSink  # noqa: E402
from mabinogi_addon.blackbox_producer import CaptureProducer, ProducerLimits  # noqa: E402

P = json.loads((Path(__file__).resolve().parents[1] / 'packaging' / 'blackbox-product.json').read_text(encoding='utf-8'))
W, H, FPS = 320, 64, 60
COLORS = [(0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255)]
FF = shutil.which('ffmpeg')


def bgra_frame():
    row = bytearray()
    for x in range(W):
        r, g, b = COLORS[x * len(COLORS) // W]
        row += bytes((b, g, r, 255))
    return bytes(row) * H


def to_nv12(bgra):
    """캡처 DLL의 GPU 변환 모형: BGRA(전체 범위) → NV12 BT.709 제한 범위."""
    return subprocess.run([FF, '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgra', '-s', f'{W}x{H}', '-i', 'pipe:0',
                           '-vf', 'scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int,format=nv12',
                           '-f', 'rawvideo', 'pipe:1'], input=bgra, capture_output=True, check=True).stdout


class Game:
    audio = (None, None)

    def __init__(self, frames_by_format, switch_at=None):
        self.frames, self.switch_at, self.n, self.t0 = frames_by_format, switch_at, 0, None

    def open(self, target):
        self.t0 = time.perf_counter()

    def read(self):
        due = self.t0 + self.n / FPS
        if time.perf_counter() < due:
            return None
        at = self.n / FPS
        self.n += 1
        fmt = 'nv12' if 'nv12' in self.frames and (self.switch_at is None or at < self.switch_at) else 'bgra'
        if fmt == 'nv12':
            return self.frames['nv12'], W, H, int(due * 1e6), 'nv12'
        return self.frames['bgra'], W, H, int(due * 1e6)

    def read_audio(self):
        return None

    def close(self):
        pass


class Spool:
    def __init__(self, folder):
        self.folder, self.n = Path(folder), 0

    def write(self, produce, max_bytes=None):
        self.n += 1
        path = self.folder / f'{self.n}.mp4'
        with path.open('wb') as stream:
            produce(stream)
        return str(path)

    def resolve(self, key):
        return Path(key)

    def discard(self, key):
        pass


def record(game, seconds):
    p, c = P['producer'], P['codec']
    limits = ProducerLimits(p['segment_frames'], p['queued_segments'], W * H * 4, W * H * 4 * 64,
                            p['max_segment_bytes'], p['frame_tolerance_us'])
    settings = CodecSettings(Path(FF), Path(shutil.which('ffprobe')), 'libx264', c['bitrate'], FPS, c['timeout'],
                             p['frame_tolerance_us'])
    enc = FFmpegEncoder(settings, lambda key: key)
    pr = CaptureProducer(SimpleNamespace(session='s'), game, enc, Spool(tempfile.mkdtemp()), limits,
                         allowed=lambda: True, cpu_meter=None)
    pr.start()
    segs, end = [], time.monotonic() + seconds
    while time.monotonic() < end and pr.error is None:
        while not pr.results.empty():
            kind, item = pr.results.get_nowait()
            if kind == 'segment':
                segs.append(item)
        time.sleep(0.01)
    error = pr.error
    pr.request_stop()
    while not pr.is_stopped():
        time.sleep(0.01)
    while not pr.results.empty():
        kind, item = pr.results.get_nowait()
        if kind == 'segment':
            segs.append(item)
    return enc, segs, pr, error


def export(enc, segs):
    slices = tuple(Slice(s, 0, s.end_us - s.start_us) for s in segs)
    plan = SavePlan(sum(s.end_us - s.start_us for s in segs), slices)
    clip = Path(tempfile.mkdtemp()) / 'clip.mp4'
    with clip.open('wb') as out:
        enc.encode(plan, ByteSink(out, 1 << 31))
    enc.validate(clip, plan)
    probe = json.loads(subprocess.check_output([shutil.which('ffprobe'), '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                                'stream=pix_fmt,color_range,color_space,color_primaries,color_transfer,nb_read_frames',
                                                '-count_frames', '-of', 'json', str(clip)]))['streams'][0]
    return clip, probe


def bar_colors(clip, frame_index):
    raw = subprocess.check_output([FF, '-v', 'error', '-i', str(clip), '-vf', f'select=eq(n\\,{frame_index})', '-frames:v', '1',
                                   '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'])
    y, out = H // 2, []
    for i in range(len(COLORS)):
        x = int((i + 0.5) * W / len(COLORS))
        at = (y * W + x) * 3
        out.append(tuple(raw[at:at + 3]))
    return out


def error_of(measured):
    return max(max(abs(a - b) for a, b in zip(m, c)) for m, c in zip(measured, COLORS))


if __name__ == '__main__':
    failures = []
    bgra = bgra_frame()
    nv12 = to_nv12(bgra)
    assert len(nv12) == W * H * 3 // 2
    for label, frames in (('NV12(GPU 색 변환 모형)', {'nv12': nv12}), ('BGRA(이전 방식, 대조)', {'bgra': bgra})):
        enc, segs, pr, error = record(Game(frames), 3.0)
        clip, probe = export(enc, segs)
        measured = bar_colors(clip, 30)
        worst = error_of(measured)
        print(f'[{label}] 구간 {len(segs)}개 · 오류 {error or "없음"} · 재시작 {pr.restarts} · 저장 영상 {probe}')
        print('  막대 RGB(원래 → 저장): ' + ' '.join(f'{c}→{m}' for c, m in zip(COLORS, measured)))
        print(f'  최대 채널 오차 {worst}')
        if error or not segs or worst > 12:  # 두 경로 모두 같은 색 기준(BT.709·제한 범위)
            failures.append(label)
    enc, segs, pr, error = record(Game({'nv12': nv12, 'bgra': bgra}, switch_at=1.5), 3.5)
    clip, probe = export(enc, segs)
    contiguous = all(b.start_us == a.end_us for a, b in zip(segs, segs[1:]))
    before, after = error_of(bar_colors(clip, 30)), error_of(bar_colors(clip, int(probe['nb_read_frames']) - 10))
    print(f'[NV12 → BGRA 중간 전환] 구간 {len(segs)}개 · 이어짐 {contiguous} · 재시작 {pr.restarts} · 오류 {error or "없음"} · '
          f'프레임 {probe["nb_read_frames"]} · 색 오차 전환 전 {before}/후 {after}')
    if error or pr.restarts != 1 or not contiguous or before > 12 or after > 12:
        failures.append('중간 전환')
    print('FAIL: ' + ', '.join(failures) if failures else 'PASS: NV12 입력 녹화·저장·검증과 색 정상')
    sys.exit(1 if failures else 0)
