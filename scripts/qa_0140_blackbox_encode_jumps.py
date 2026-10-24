"""0.14.0 블랙박스 '알트탭 안 한 구간도 중간에 잘린 것처럼' 재현: 구간 인코딩이 0.25초를 넘을 때.

실행: uv run python -m scripts.qa_0140_blackbox_encode_jumps
제품 설정(60FPS, 구간 15프레임=0.25초, 대기 구간 1개)으로 실제 CaptureProducer를 돌린다. 가짜 게임은 60FPS로 그리고,
늦게 읽으면 중간 프레임은 풀(2장)에서 밀려난다(WGC 동작 모형). 인코딩이 구간 길이보다 오래 걸리면 캡처 스레드가 대기열에서 막혀
프레임을 놓치고, 250ms 이하 공백은 직전 프레임 반복(멈칫), 초과는 구간을 잘라 영상이 건너뛴다.
0.33초/구간(0.13.1 실측 수준)에서 건너뛴 지점이 생기면 REPRODUCED, 종료 코드 1.

0.15.0 상주 인코더: 제품 경로는 ffmpeg 1개를 녹화 동안 유지한다(시작 비용은 처음 한 번). 판정은 제품 경로(StreamEnc)로 하고,
예전 구간마다 실행 방식(SlowEnc)은 비교용으로만 출력한다. 0.14.1 실측(app.log): 구간 평균 0.34초 → 저장 74%·공백 126회/81초.
"""
import runpy, time, tempfile, sys
from types import SimpleNamespace
from pathlib import Path
m = runpy.run_path(str(Path(__file__).resolve().parent / 'qa_0137_blackbox_playback_speed.py'), run_name='lib')
CaptureProducer, ProducerLimits, P = m['CaptureProducer'], m['ProducerLimits'], m['P']
Spool, W, H = m['Spool'], m['W'], m['H']
class Game:
    audio = (None, None)
    def __init__(self, fps): self.fps, self.sent = fps, 0
    def open(self, t): self.t0 = time.perf_counter()
    def read(self):
        now = time.perf_counter()
        if now < self.t0 + self.sent / self.fps: return None
        self.sent = int((now - self.t0) * self.fps) + 1   # 늦게 읽으면 중간 프레임은 풀에서 밀려남(WGC 2장)
        return bytes(W*H*4), W, H, int((self.t0 + (self.sent - 1) / self.fps) * 1e6)
    def read_audio(self): return None
    def close(self): pass
class SlowEnc:
    def __init__(s, sec): s.sec = sec; s.settings = SimpleNamespace(fps=60, timeout=30)
    def encode_frames(s, f, w, h, sink, audio_path=None): time.sleep(s.sec); sink.write(b'x')
class StreamEnc:
    """상주 인코더 모형: 여는 데 sec(0.14.1 구간당 비용과 같은 시작 비용) 한 번, 조각은 다음 키프레임이 올 때 나온다."""
    def __init__(s, sec): s.sec = sec; s.settings = SimpleNamespace(fps=60, timeout=30); s.opened = 0
    def encode_frames(s, f, w, h, sink, audio_path=None): raise AssertionError('상주 인코더 경로가 아님')
    def open_stream(s, w, h, gop, on_fragment):
        time.sleep(s.sec); s.opened += 1
        class Stream:
            held = 0
            def write(self, data):
                if self.held == gop: on_fragment(b'x', gop); self.held = 0
                self.held += 1
                return 0.0
            def finish(self, timeout):
                if self.held: on_fragment(b'x', self.held); self.held = 0
            def abort(self): pass
        return Stream()


def run(fps, enc, seconds=4.0):
    p = P['producer']
    lim = ProducerLimits(p['segment_frames'], p['queued_segments'], W*H*4, W*H*4*64, p['max_segment_bytes'], p['frame_tolerance_us'])
    with tempfile.TemporaryDirectory() as d:
        pr = CaptureProducer(SimpleNamespace(session='s'), Game(fps), enc, Spool(d), lim, allowed=lambda: True)
        pr.start(); end = time.monotonic() + seconds; segs = []
        def drain():
            while not pr.results.empty():
                k, it = pr.results.get_nowait()
                if k == 'segment': segs.append(it)
        while time.monotonic() < end: drain(); time.sleep(0.01)
        pr.request_stop()
        while not pr.is_stopped(): drain(); time.sleep(0.01)
        drain()
    saved = sum(s.duration_us for s in segs)/1e6; span = (segs[-1].end_us - segs[0].start_us)/1e6
    jumps = sum(1 for a, b in zip(segs, segs[1:]) if b.start_us - a.end_us > 1000)
    result = (jumps, pr.filled, saved, span)
    kind = '상주 인코더(시작' if isinstance(enc, StreamEnc) else '구간마다 실행(구간'
    print(f'게임 {fps}FPS · {kind} {enc.sec:.2f}초): 경과 {span:.2f}초 중 저장 {saved:.2f}초 · 건너뛴 지점 {jumps}개 · 반복 채움 {pr.filled}칸 · 프레임 공백 {pr.gaps}회')
    return result


if __name__ == '__main__':
    run(60, SlowEnc(0.33))  # 비교: 0.14.1까지(구간마다 ffmpeg 실행)
    jumps, filled, saved, span = run(60, StreamEnc(0.33))
    reproduced = jumps > 0 or filled > 0 or saved < span - 0.02
    print('REPRODUCED: 인코딩이 실시간보다 느려 캡처가 막혀 영상이 멈칫·건너뜀' if reproduced
          else 'not reproduced: 상주 인코더는 경과 시간 전부 저장·건너뜀 0')
    sys.exit(1 if reproduced else 0)
