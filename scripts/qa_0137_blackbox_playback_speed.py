"""0.13.7 블랙박스 재생 배속 재현: 게임 FPS가 60보다 낮으면 저장 영상이 실제보다 빨리 재생되는지.

실행: uv run python -m scripts.qa_0137_blackbox_playback_speed
제품 설정(60FPS, 허용 오차 33,334µs)으로 실제 CaptureProducer를 돌린다. 가짜 게임은 정해진 FPS로 끊김 없이 프레임을 내고,
생산자가 만든 구간의 '저장 영상 길이 합'과 '실제 경과 시간'을 비교한다. 생산자는 받은 프레임을 60FPS 격자 칸에 하나씩 놓으므로
게임이 45FPS면 1초 분량이 0.75초 영상이 된다(밀림이 허용 오차를 넘으면 새 구간). 60FPS 미만에서 배속이 1.1배를 넘으면 REPRODUCED, 종료 코드 1.
"""
import json, sys, tempfile, time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mabinogi_addon.blackbox_producer import CaptureProducer, ProducerLimits
P = json.loads((Path(__file__).resolve().parents[1] / 'packaging' / 'blackbox-product.json').read_text(encoding='utf-8'))
W, H = 32, 18
class Game:
    audio = (None, None)
    def __init__(self, fps): self.fps, self.n = fps, 0
    def open(self, t): self.t0 = time.perf_counter()
    def read(self):
        due = self.t0 + self.n / self.fps
        if time.perf_counter() < due: return None
        self.n += 1
        return bytes(W*H*4), W, H, int(due * 1e6)
    def read_audio(self): return None
    def close(self): pass
class Enc:
    settings = SimpleNamespace(fps=60, timeout=30)
    def encode_frames(self, f, w, h, sink, audio_path=None): sink.write(b'x')
class Spool:
    def __init__(s, d): s.d, s.n = Path(d), 0
    def write(s, fn, max_bytes=None):
        s.n += 1; p = s.d / f'{s.n}'
        with p.open('wb') as f: fn(f)
        return p.name
    def resolve(s, k): return s.d / k
    def discard(s, k): pass
def run(fps, seconds=3.0):
    p = P['producer']
    lim = ProducerLimits(p['segment_frames'], p['queued_segments'], W*H*4, W*H*4*64, p['max_segment_bytes'], p['frame_tolerance_us'])
    with tempfile.TemporaryDirectory() as d:
        pr = CaptureProducer(SimpleNamespace(session='s'), Game(fps), Enc(), Spool(d), lim, allowed=lambda: True)
        pr.start(); end = time.monotonic() + seconds; segs = []
        while time.monotonic() < end:
            while not pr.results.empty():
                k, it = pr.results.get_nowait()
                if k == 'segment': segs.append(it)
            time.sleep(0.01)
        pr.request_stop()
        while not pr.is_stopped():
            while not pr.results.empty():
                k, it = pr.results.get_nowait()
                if k == 'segment': segs.append(it)
            time.sleep(0.01)
    saved = sum(s.duration_us for s in segs) / 1e6
    span = (segs[-1].end_us - segs[0].start_us) / 1e6 if segs else 0
    print(f'게임 {fps}FPS: 실제 경과 {span:.2f}초 → 저장 영상 길이 {saved:.2f}초 (재생 배속 약 {span/saved:.2f}x) · 구간 {len(segs)}개 · 프레임 공백 {pr.gaps}회')
    return span / saved if saved else 0


if __name__ == '__main__':
    speeds = {fps: run(fps) for fps in (60, 50, 45, 30)}
    reproduced = speeds[60] < 1.05 and any(speeds[f] > 1.1 for f in (50, 45, 30))
    print('REPRODUCED: 게임 FPS가 60 미만이면 저장 영상이 실제보다 빨리 재생됨(60/FPS 배)' if reproduced else 'not reproduced')
    sys.exit(1 if reproduced else 0)
