"""0.15.0 상주 인코더 끝까지 재현: 실제 CaptureProducer + 실제 ffmpeg 상주 인코더 → 구간 → 저장(concat)·검증 → 프레임 단위 대조.

실행: uv run python -m scripts.qa_0150_blackbox_stream_e2e
가짜 게임 창(60FPS)이 프레임마다 번호를 막대 10개(흑백 비트)로 그린다. 저장 영상을 다시 풀어 번호를 읽으면
반복(멈칫)·건너뜀이 프레임 단위로 보인다. 시스템 ffmpeg(libx264, 제품은 번들 8.1.3·NVENC)로 돈다.
- 연속 6초: 구간이 모두 15프레임·빈틈 없이 이어지고, 저장 영상 번호가 1씩 늘어야 한다(건너뜀·반복 0).
- 화면 멈춤 1.5초 중 저장 요청: 1초(FLUSH_WAIT_S) 안에 저장 결과(flush)가 나오고, 다시 움직이면 이어서 녹화돼야 한다.
- 1.5초 공백(최소화 상당) 뒤 재개: 인코더 재시작 1회, 공백 뒤 구간도 정상.
실패하면 FAIL, 종료 코드 1.
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
W, H, BITS = 320, 180, 10
FPS = 60


def frame_for(n):
    """번호 n을 막대 BITS개(왼쪽이 최상위 비트, 흰=1)로 그린 BGRA 프레임."""
    row = bytearray()
    bar = W // BITS
    for x in range(W):
        bit = (n >> (BITS - 1 - min(x // bar, BITS - 1))) & 1
        row += b'\xff\xff\xff\xff' if bit else b'\x00\x00\x00\xff'
    return bytes(row) * H


class Game:
    """schedule: [(시작초, 끝초, 'stop'|'freeze')] 동안 프레임을 안 냄(stop=공백) 또는 같은 화면(freeze=프레임 없음)."""
    audio = (None, None)

    def __init__(self, schedule=()):
        self.schedule, self.n, self.t0 = schedule, 0, None
        self.cache = {}

    def open(self, target):
        self.t0 = time.perf_counter()

    def read(self):
        due = self.t0 + self.n / FPS
        if time.perf_counter() < due:
            return None
        at = self.n / FPS
        self.n += 1
        if any(a <= at < b for a, b, _ in self.schedule):
            return None  # 이 칸은 프레임이 오지 않음(멈춤·최소화)
        number = self.n - 1
        if number not in self.cache:
            self.cache[number] = frame_for(number % (1 << BITS))
        return self.cache.pop(number), W, H, int(due * 1e6)

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


def codec():
    c = P['codec']
    settings = CodecSettings(Path(shutil.which('ffmpeg')), Path(shutil.which('ffprobe')), 'libx264', c['bitrate'], FPS,
                             c['timeout'], P['producer']['frame_tolerance_us'])
    return FFmpegEncoder(settings, lambda key: key)


def record(label, seconds, schedule=(), flush_at=None):
    p = P['producer']
    limits = ProducerLimits(p['segment_frames'], p['queued_segments'], W * H * 4, W * H * 4 * 64,
                            p['max_segment_bytes'], p['frame_tolerance_us'])
    folder = tempfile.mkdtemp()
    enc = codec()
    game = Game(schedule)
    pr = CaptureProducer(SimpleNamespace(session='s'), game, enc, Spool(folder), limits, allowed=lambda: True)
    pr.start()
    segs, flushes, flush_sent = [], [], None
    end = time.monotonic() + seconds

    def drain():
        while not pr.results.empty():
            kind, item = pr.results.get_nowait()
            if kind == 'segment':
                segs.append(item)
            elif kind == 'flush':
                flushes.append((item, time.monotonic()))
    while time.monotonic() < end and pr.error is None:
        drain()
        if flush_at is not None and flush_sent is None and game.t0 and time.perf_counter() - game.t0 >= flush_at:
            flush_sent = time.monotonic()
            pr.request_flush('save', int(time.perf_counter() * 1e6))
        time.sleep(0.01)
    error = pr.error
    pr.request_stop()
    while not pr.is_stopped():
        drain()
        time.sleep(0.01)
    drain()
    waits = pr._timing
    print(f'[{label}] 구간 {len(segs)}개 · 프레임 수 {sorted({round((s.end_us - s.start_us) * FPS / 1e6) for s in segs})} · '
          f'인코더 입력 대기 평균 {sum(waits) / max(1, len(waits)) * 1000:.1f}ms·최대 {max(waits, default=0) * 1000:.1f}ms · '
          f'반복 채움 {pr.filled}칸 · 공백 {pr.gaps}회 · 재시작 {pr.restarts}회 · 오류 {error or "없음"}')
    flush_delay = (flushes[0][1] - flush_sent) if flushes and flush_sent else None
    if flush_at is not None:
        print(f'  저장 요청 → 결과(flush) {flush_delay if flush_delay is None else round(flush_delay, 2)}초')
    return enc, segs, pr, error, flush_delay


def export(enc, segs, folder):
    slices = tuple(Slice(s, 0, s.end_us - s.start_us) for s in segs)
    plan = SavePlan(sum(s.end_us - s.start_us for s in segs), slices)
    clip = Path(folder) / 'clip.mp4'
    with clip.open('wb') as out:
        enc.encode(plan, ByteSink(out, 1 << 31))
    enc.validate(clip, plan)
    raw = subprocess.check_output([shutil.which('ffmpeg'), '-v', 'error', '-i', str(clip), '-vf', f'scale={BITS}:1:flags=area',
                                   '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1'], timeout=120)
    numbers = []
    for i in range(0, len(raw), BITS):
        bits = raw[i:i + BITS]
        numbers.append(int(''.join('1' if b > 127 else '0' for b in bits), 2))
    return numbers


def continuity(numbers):
    steps = [b - a for a, b in zip(numbers, numbers[1:])]
    return sum(s == 0 for s in steps), sum(s > 1 for s in steps), [s for s in steps if s not in (0, 1)][:5]


if __name__ == '__main__':
    failures = []
    enc, segs, pr, error, _ = record('연속 6초', 6.0)
    repeats, jumps, odd = continuity(export(enc, segs, tempfile.mkdtemp()))
    contiguous = all(b.start_us == a.end_us for a, b in zip(segs, segs[1:]))
    print(f'  저장 영상: 반복 {repeats} · 건너뜀 {jumps} {odd} · 구간 이어짐 {contiguous}')
    if error or repeats or jumps or not contiguous or pr.restarts:
        failures.append('연속 녹화')

    enc, segs, pr, error, delay = record('화면 멈춤 중 저장 요청', 5.0, schedule=[(2.0, 3.5, 'freeze')], flush_at=2.3)
    if error or delay is None or delay > 1.6 or not segs or segs[-1].end_us / 1e6 - pr.native.t0 < 4.0:
        failures.append('멈춤 중 저장')

    enc, segs, pr, error, _ = record('1.5초 공백 뒤 재개', 5.0, schedule=[(2.0, 3.5, 'stop')])
    after = [s for s in segs if s.start_us / 1e6 - pr.native.t0 >= 3.5]
    print(f'  공백 뒤 구간 {len(after)}개')
    if error or pr.restarts != 1 or not after:
        failures.append('공백 뒤 재개')
    numbers = export(enc, segs, tempfile.mkdtemp())
    repeats, jumps, odd = continuity(numbers)
    print(f'  저장 영상: 반복 {repeats} · 건너뜀 {jumps} {odd}(공백 1곳은 정상)')
    if jumps != 1:
        failures.append('공백 뒤 이어 붙이기')

    print('FAIL: ' + ', '.join(failures) if failures else 'PASS: 상주 인코더 녹화·저장·검증 프레임 단위 정상')
    sys.exit(1 if failures else 0)
