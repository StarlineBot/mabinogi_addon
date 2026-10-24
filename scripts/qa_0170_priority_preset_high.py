"""0.17.0 게임 우선순위 높음(13.7) QA 재현: 세션 시작 때 이미 '높음'이면(작업 관리자로 미리 건 경우), 이후 게임이 맵 이동으로
'보통'으로 되돌려도 앱이 다시 걸지 않는지. 리서치 7.7(작업 관리자 높음 → 64분 '보통')과 같은 상황.

실행: uv run python -m scripts.qa_0170_priority_preset_high
실제 Engine·Recovery + 테스트용 가짜 백엔드(tests/test_optimization_priority.PriorityBackend). 2초 유지 확인 3번을 기다린다.
다시 걸지 않으면 REPRODUCED, 종료 코드 1. 대조군(시작 때 '보통')은 되돌림 뒤 다시 걸어야 한다.
"""
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]

from mabinogi_addon.optimization.engine import Engine  # noqa: E402
from mabinogi_addon.optimization.session import Recovery  # noqa: E402
from mabinogi_addon.system.process_priority import HIGH, NORMAL  # noqa: E402
from test_optimization_priority import KEY, OPTIONS, PriorityBackend  # noqa: E402


def run(label, start):
    backend = PriorityBackend()
    backend.values[KEY] = start
    recovery = Recovery(Path(tempfile.mkdtemp()) / 'journal.json', backend, lambda: True)
    engine = Engine(backend, recovery, lambda: True)
    engine.start(OPTIONS)
    time.sleep(1.0)
    backend.values[KEY] = NORMAL  # 게임이 맵 이동·재접속으로 '보통'으로 되돌림(diag --watch 실측)
    time.sleep(6.5)
    final = backend.values[KEY]
    engine.stop(); engine.thread.join(5)
    print(f'[{label}] 시작 {"높음" if start == HIGH else "보통"} → 게임이 보통으로 되돌린 뒤 6.5초: '
          f'{"높음" if final == HIGH else "보통"} · 쓰기 {len(backend.writes)}회 · 기록 {len(recovery.items)}건')
    return final


if __name__ == '__main__':
    control = run('대조군: 시작 때 보통', NORMAL)
    preset = run('작업 관리자로 미리 높음', HIGH)
    bad = preset != HIGH
    print('REPRODUCED: 미리 높음이면 이후 되돌림을 다시 걸지 않음(세션 내내 보통)' if bad else 'not reproduced')
    sys.exit(1 if bad or control != HIGH else 0)
