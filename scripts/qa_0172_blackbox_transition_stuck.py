"""QA 재현(0.17.2 블랙박스 저장 실패·종료 불가): 게임 재실행(대상 교체) 직후 NV12 생산자가 멈추는지.

12:52:18 실게임 로그 순서를 흉내 낸다: NV12 녹화 → 프레임 공백 2회 → 'capture target changed' →
남은 묶음으로 인코더 다시 시작. A) 네이티브 close가 정상이면 생산자가 끝나는지(파이썬 경로 판정),
B) 네이티브 close가 돌아오지 않으면 화면·저장·종료가 실게임과 같은 모양이 되는지 본다.
실행: uv run python scripts/qa_0172_blackbox_transition_stuck.py
"""
import sys, threading, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests'), str(ROOT)]
import test_blackbox_stream as st
from test_blackbox_cpu import FormatCodec, _nv12_frames
from mabinogi_addon.system.blackbox_capture import NativeTransition

class Device(st.Device):
    def __init__(self, frames, block_close):
        super().__init__(frames); self.block = block_close; self.release = threading.Event()
    def read(self):
        if self.frames:
            return self.frames.pop(0)
        raise NativeTransition('capture target changed: 0x80070005')
    def close(self):
        if self.block:
            self.release.wait()  # 네이티브 정리가 안 돌아오는 경우

def run(block_close):
    frames = (_nv12_frames([100_000 * n for n in range(1, 8)])            # 연속 녹화
              + _nv12_frames([1_500_000 + 100_000 * n for n in range(4)])  # 공백 1
              + _nv12_frames([3_000_000 + 100_000 * n for n in range(2)]))  # 공백 2 → 남은 묶음
    producer = st._producer(frames, FormatCodec())
    producer.native = Device(frames, block_close)
    results = []
    producer.start()
    st._drain(producer, results, producer.is_stopped, 3)
    # 서비스는 대상이 바뀌면 매 틱 request_stop만 한다(blackbox_service.tick)
    producer.request_stop()
    st._drain(producer, results, producer.is_stopped, 3)
    try:
        producer.request_flush('t', 0); flush = '접수'
    except RuntimeError as exc:
        flush = f'거부({exc})'
    print(f"[{'B 네이티브 close 멈춤' if block_close else 'A 네이티브 close 정상'}] "
          f"is_stopped={producer.is_stopped()} captured={producer._captured.is_set()} "
          f"encoded={producer._encoded.is_set()} transition={producer.transition} "
          f"restarts={producer.restarts} 저장요청={flush} error={producer.error}")
    producer.native.release.set()
    st._drain(producer, results, producer.is_stopped, 3)
    return producer

a, b = run(False), run(True)
ok = a.is_stopped() and a.transition
print('판정: 파이썬 생산자 경로는 대상 교체 뒤 정상 종료' if ok else '판정: 파이썬 경로에서도 멈춤(개발 원인 확정)')
