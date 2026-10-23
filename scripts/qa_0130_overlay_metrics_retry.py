"""0.13.0 오버레이 지표 재시도 재현: 조회기 생성이 계속 실패할 때 0.25초마다 다시 만들고 경고를 남기는지.

실행: uv run python -m scripts.qa_0130_overlay_metrics_retry
컨트롤러 `_frame_tick`은 게임이 앞에 있는 동안 0.25초마다 `PerfSampler.update`를 부른다. PDH 카운터 추가가
실패하는 PC(성능 카운터 손상·비활성 등)에서 생성 시도가 3초에 2회를 넘으면 REPRODUCED, 종료 코드 1.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from mabinogi_addon.system.perf_metrics import PerfSampler  # noqa: E402


def main():
    calls = []

    def failing(metrics):
        calls.append(time.monotonic())
        raise OSError('PDH 카운터 추가 실패(모형)')

    sampler = PerfSampler(reader_factory=failing, interval=1.0)
    start = time.monotonic()
    while time.monotonic() - start < 3.0:
        sampler.update(['cpu', 'gpu'], 1234)
        time.sleep(0.25)
    sampler.stop()
    reproduced = len(calls) > 2
    print(f'[지표] 3초 동안 조회기 생성 시도 {len(calls)}회(실패마다 경고 로그 1줄)')
    print('[지표]', 'REPRODUCED: 실패한 조회기를 0.25초마다 다시 만들고 경고를 반복' if reproduced else 'not reproduced')
    return reproduced


if __name__ == '__main__':
    sys.exit(1 if main() else 0)
