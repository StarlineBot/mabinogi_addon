"""0.15.1 실측 '반복 채움 +~720칸/240구간(20%) · 서로 다른 화면 ~48FPS' 모형: 60Hz 화면 도착 시각 흔들림이 반복 채움+버림 쌍을 만드는지.

실행: uv run python -m scripts.qa_0151_blackbox_fill_jitter (실제 CaptureProducer + qa_0140 상주 인코더 모형)
격자 원점이 첫 프레임(흔들린) 시각이라 허용 폭(반 칸 8.3ms)이 실효로 줄어 ±7ms 흔들림에서 채움+버림이 생긴다.
"""
import sys, time, random, tempfile, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src')); sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from types import SimpleNamespace
from pathlib import Path
from mabinogi_addon.blackbox_producer import CaptureProducer, ProducerLimits
from scripts.qa_0140_blackbox_encode_jumps import StreamEnc, Spool, P
W,H=32,18
class Game:
    audio=(None,None)
    def __init__(s,hz,jit): s.hz,s.jit,s.n,s.r=hz,jit,0,random.Random(1)
    def open(s,t): s.t0=time.perf_counter()
    def read(s):
        due=s.t0+s.n/s.hz
        if time.perf_counter()<due: return None
        s.n+=1; st=due+s.r.uniform(-s.jit,s.jit)
        return bytes([s.n%256])*(W*H*4),W,H,int(st*1e6)
    def read_audio(s): return None
    def close(s): pass
def run(hz,jit,sec=4):
    p=P['producer']; lim=ProducerLimits(p['segment_frames'],p['queued_segments'],W*H*4,W*H*4*64,p['max_segment_bytes'],p['frame_tolerance_us'])
    with tempfile.TemporaryDirectory() as d:
        pr=CaptureProducer(SimpleNamespace(session='s'),Game(hz,jit),StreamEnc(0.0),Spool(d),lim,allowed=lambda:True)
        pr.start(); end=time.monotonic()+sec
        while time.monotonic()<end:
            while not pr.results.empty(): pr.results.get_nowait()
            time.sleep(0.01)
        pr.request_stop()
        while not pr.is_stopped():
            while not pr.results.empty(): pr.results.get_nowait()
            time.sleep(0.01)
    slots=pr._slots or 1
    print(f'게임 화면 {hz}Hz · 도착 시각 흔들림 ±{jit*1000:.0f}ms → 반복 채움 {pr.filled}칸/{slots}칸({pr.filled/slots:.0%}) · 서로 다른 화면 {pr._distinct/(slots/60):.1f}FPS · 공백 {pr.gaps}')
for hz,j in ((60,0),(60,0.004),(60,0.007),(144,0),(144,0.002)): run(hz,j)
