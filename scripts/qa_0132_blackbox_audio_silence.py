"""0.13.2 블랙박스 소리 처리 재현: 지터는 이어 가는지, 게임이 잠깐 소리를 안 낼 때 녹화가 멈추는지.

실행: uv run python -m scripts.qa_0132_blackbox_audio_silence
제품 설정(60FPS, 구간 15프레임, 대기 구간 1개, codec timeout 그대로)으로 실제 CaptureProducer·PcmTimeline을 돌린다.
가짜 게임 창은 60FPS, 가짜 소리는 10ms 묶음(48kHz 스테레오)이고, 가짜 인코더는 구간마다 0.05초 걸린다.
- 지터 ±1.5ms: 계속 녹화돼야 한다(0.13.2 수정 대상).
- 2초 무음(묶음이 오지 않음) 뒤 재개: 재개 뒤 구간이 다시 쌓여야 한다. 인코딩 스레드는 소리를 기다리고, 소리는 캡처 스레드만
  읽는데 캡처 스레드가 대기열(1구간)에서 막혀 있으면 재개 뒤에도 소리를 못 읽어 멈춘다(codec timeout까지 오류도 없음).
재개 뒤 구간이 하나도 없으면 REPRODUCED, 종료 코드 1.

(94c54ef 후속) 시각 기준점 문제도 본다. 0.13.2는 허용 범위 안의 묶음을 직전 끝(샘플 수)에 붙이므로 기준은 첫 묶음(또는 공백
뒤 첫 묶음)의 실제 시각이다.
- 지터 ±2.9ms: 첫 묶음이 +2.9ms였다면 이후 -2.9ms 묶음은 차이 -5.8ms → 겹침으로 녹화 중단(실효 허용 범위가 절반).
- 소리 장치 시계와 QPC 차이(드리프트): 샘플 수로 쌓은 끝과 QPC 시각이 ppm×시간만큼 벌어진다. 장치 시계가 빠르면 음수 쪽이라
  100ppm이면 약 30초, 20ppm이면 약 150초 연속 소리 뒤 3ms를 넘어 겹침 중단. 재현은 2000ppm(1.5초에 3ms)으로 가속.
녹화가 겹침으로 멈추면 REPRODUCED.
"""
import json
import random
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from mabinogi_addon.blackbox_producer import CaptureProducer, ProducerLimits  # noqa: E402

PRODUCT = json.loads((Path(__file__).resolve().parents[1] / 'packaging' / 'blackbox-product.json').read_text(encoding='utf-8'))
W, H = 64, 36
RATE, CHANNELS, PACKET_MS = 48000, 2, 10
PACKET = bytes(RATE * PACKET_MS // 1000 * CHANNELS * 2)


class Game:
    """60FPS 게임 창 + 프로세스 루프백 소리. silence=(시작초, 끝초) 동안 소리 묶음이 오지 않는다."""

    def __init__(self, jitter_us=0, silence=None, drift_ppm=0):
        self.audio = (RATE, CHANNELS)
        self.audio_buffer_bytes = PRODUCT.get('audio_settings', {}).get('audio_buffer_bytes', 8_388_608)  # 0.13.7부터 제품은 영상만(소리 코드 단독 검증)
        self.jitter_us, self.silence, self.drift = jitter_us, silence, drift_ppm / 1_000_000
        self.start = None
        self.sent = self.packets = 0
        self.random = random.Random(7)

    def open(self, target):
        self.start = time.perf_counter()

    def _us(self, seconds):
        return int((self.start + seconds) * 1_000_000)

    def read(self):
        now = time.perf_counter()
        if now < self.start + self.sent / 60:
            return None
        self.sent = int((now - self.start) * 60) + 1
        return bytes(W * H * 4), W, H, self._us((self.sent - 1) / 60)

    def read_audio(self):
        while True:
            at = self.packets * PACKET_MS / 1000
            if time.perf_counter() < self.start + at + PACKET_MS / 1000:
                return None
            self.packets += 1
            if self.silence and self.silence[0] <= at < self.silence[1]:
                continue  # 게임이 소리를 내지 않는 동안 루프백 묶음이 오지 않음
            jitter = self.random.randint(-self.jitter_us, self.jitter_us) if self.jitter_us else 0
            return PACKET, self._us(at * (1 - self.drift)) + jitter  # 장치 시계가 빠르면 QPC 시각이 샘플 수보다 덜 감

    def close(self):
        pass


class Encoder:
    def __init__(self):
        self.settings = SimpleNamespace(fps=PRODUCT['codec']['fps'], timeout=PRODUCT['codec']['timeout'])

    def encode_frames(self, frames, width, height, sink, audio_path=None):
        time.sleep(0.05)
        sink.write(b'x')


class Spool:
    def __init__(self, folder):
        self.folder, self.n = Path(folder), 0

    def write(self, produce, max_bytes=None):
        self.n += 1
        with (self.folder / f'{self.n}.bin').open('wb') as stream:
            produce(stream)
        return f'{self.n}.bin'

    def resolve(self, key):
        return self.folder / key

    def discard(self, key):
        pass


def run(label, game, duration, after=None):
    p = PRODUCT['producer']
    limits = ProducerLimits(p['segment_frames'], p['queued_segments'], W * H * 4, W * H * 4 * 64,
                            p['max_segment_bytes'], p['frame_tolerance_us'])
    starts = []
    with tempfile.TemporaryDirectory() as folder:
        producer = CaptureProducer(SimpleNamespace(session='s'), game, Encoder(), Spool(folder), limits, allowed=lambda: True)
        producer.start()
        end = time.monotonic() + duration
        while time.monotonic() < end and producer.error is None:
            while not producer.results.empty():
                kind, item = producer.results.get_nowait()
                if kind == 'segment':
                    starts.append((item.start_us - game._us(0)) / 1_000_000)
            time.sleep(0.01)
        error = producer.error
        producer.request_stop()
        producer.audio.close()  # 막힌 소리 대기를 풀어 스레드를 정리한다(제품에는 없는 정리)
        stop_deadline = time.monotonic() + 5
        while not producer.is_stopped() and time.monotonic() < stop_deadline:
            while not producer.results.empty():
                producer.results.get_nowait()
            time.sleep(0.01)
    resumed = [s for s in starts if after is not None and s >= after]
    print(f'[{label}] {duration:.0f}초 동안 구간 {len(starts)}개'
          + (f' · 재개({after:.1f}초) 뒤 구간 {len(resumed)}개' if after is not None else '')
          + f' · 마지막 구간 시작 {max(starts, default=0):.2f}초 · 소리 공백 {producer.audio.gaps}회 · 오류: {error or "없음"}')
    return starts, resumed, error


if __name__ == '__main__':
    jitter_starts, _, jitter_error = run('지터 ±1.5ms', Game(jitter_us=1500), 4)
    _, resumed, silence_error = run('2초 무음 뒤 재개', Game(silence=(1.5, 3.5)), 7, after=3.5)
    *_, anchor_error = run('지터 ±2.9ms(첫 묶음 기준점)', Game(jitter_us=2900), 4)
    *_, drift_error = run('드리프트 2000ppm(100ppm 30초 상당)', Game(drift_ppm=2000), 4)
    jitter_ok = jitter_error is None and len(jitter_starts) >= 8
    stalled = not resumed and silence_error is None
    print('지터:', '정상(계속 녹화)' if jitter_ok else '실패')
    print('REPRODUCED: 소리가 끊겼다 재개되면 녹화가 오류 없이 멈춤(인코딩은 소리 대기, 캡처는 대기열에서 막혀 소리를 못 읽음)'
          if stalled else '무음 뒤 재개: not reproduced')
    overlap = [e for e in (anchor_error, drift_error) if e and 'overlap' in e]
    print('REPRODUCED: 허용 범위 안 지터·장치 시계 드리프트가 기준점에서 쌓여 audio overlap으로 녹화 중단'
          if overlap else '기준점·드리프트: not reproduced')
    sys.exit(1 if stalled or not jitter_ok or overlap else 0)
