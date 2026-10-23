"""0.13.0 실사용 'frame clock drift exceeds bound' 재현: 구간 인코딩이 0.25초보다 오래 걸릴 때.

실행: uv run python -m scripts.qa_0130_blackbox_encode_backpressure
제품 설정(60FPS, 구간 15프레임=0.25초, 대기 구간 1개, 허용 오차 33,334µs)으로 실제 CaptureProducer를 돌린다.
가짜 게임 창은 60FPS로 끊김 없이 프레임을 내고, 가짜 인코더는 구간마다 정해진 시간만 걸린다.
인코딩이 0.25초 안이면 계속 녹화되고, 넘으면 캡처 스레드가 대기열에서 막혀 다음 프레임 시각이 밀리며 중단된다.
인코딩 0.4초(새 ffmpeg 실행 + 하드웨어 인코더 초기화 수준)에서 중단되면 REPRODUCED, 종료 코드 1.
"""
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from mabinogi_addon.blackbox_producer import CaptureProducer, ProducerLimits  # noqa: E402

PRODUCT = json.loads((Path(__file__).resolve().parents[1] / 'packaging' / 'blackbox-product.json').read_text(encoding='utf-8'))
W, H = 64, 36  # 프레임 크기는 결과와 무관(시각 규칙만 본다)


class SteadyGame:
    """60FPS로 끊김 없이 프레임을 내는 게임 창. 시각은 실제 시계(µs*10 = 100ns 아님, 이미 µs)."""
    audio = (None, None)

    def __init__(self):
        self.start = None
        self.sent = 0

    def open(self, target):
        self.start = time.perf_counter()

    def read(self):
        due = self.start + self.sent / 60
        now = time.perf_counter()
        if now < due:
            return None
        # 늦게 읽으면 그 사이 프레임은 풀(2장)에서 밀려나고 가장 최근 프레임만 남는다.
        self.sent = int((now - self.start) * 60) + 1
        stamp = int((self.start + (self.sent - 1) / 60) * 1_000_000)
        return bytes(W * H * 4), W, H, stamp

    def read_audio(self):
        return None

    def close(self):
        pass


class SlowEncoder:
    def __init__(self, seconds):
        self.settings = SimpleNamespace(fps=PRODUCT['codec']['fps'], timeout=30)
        self.seconds = seconds

    def encode_frames(self, frames, width, height, sink, audio_path=None):
        time.sleep(self.seconds)
        sink.write(b'x')


class Spool:
    def __init__(self, folder):
        self.folder, self.n = Path(folder), 0

    def write(self, produce, max_bytes=None):
        self.n += 1
        path = self.folder / f'{self.n}.bin'
        with path.open('wb') as stream:
            produce(stream)
        return path.name

    def resolve(self, key):
        return self.folder / key

    def discard(self, key):
        pass


def run(encode_seconds, duration=3.0):
    p = PRODUCT['producer']
    limits = ProducerLimits(p['segment_frames'], p['queued_segments'], W * H * 4, W * H * 4 * 64,
                            p['max_segment_bytes'], p['frame_tolerance_us'])
    with tempfile.TemporaryDirectory() as folder:
        producer = CaptureProducer(SimpleNamespace(session='s'), SteadyGame(), SlowEncoder(encode_seconds),
                                   Spool(folder), limits, allowed=lambda: True)
        producer.start()
        end = time.monotonic() + duration
        segments = 0
        while time.monotonic() < end and producer.error is None:
            while not producer.results.empty():
                producer.results.get_nowait()
                segments += 1
            time.sleep(0.01)
        producer.request_stop()
        while not producer.is_stopped():
            while not producer.results.empty():
                producer.results.get_nowait()
            time.sleep(0.01)
        print(f'[인코딩 {encode_seconds:.2f}초/구간] {duration:.0f}초 동안 구간 {segments}개 · 오류: {producer.error or "없음"}')
        return producer.error


if __name__ == '__main__':
    fast = run(0.10)
    slow = run(0.40)
    reproduced = fast is None and slow is not None and 'drift' in slow
    print('REPRODUCED: 구간 인코딩이 0.25초를 넘으면 캡처가 막혀 frame clock drift로 녹화 중단'
          if reproduced else 'not reproduced')
    sys.exit(1 if reproduced else 0)
