"""0.12.0 '조건별 정리' 재현: 같은 측정의 요약 파일 순서에 따라 결과가 달라지는지.

실행: uv run python -m scripts.qa_0120_condition_summary_order
수집 모드는 구간이 닫힐 때마다 파일을 하나씩 남기고(구간 1개 + 그 시점까지의 측정 전체 집계),
파일 이름은 `frames-<uuid4>.json`이라 읽는 순서가 무작위다. 측정 1회의 '측정 전체 1% low'는
가장 많이 진행된(마지막) 집계여야 한다. 순서에 따라 값이나 묶음이 달라지면 REPRODUCED, 종료 코드 1.
"""
import sys
from itertools import permutations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from mabinogi_addon.optimization.frame_summary import condition_summary  # noqa: E402


def _segment(index, low, condition):
    return dict(index=index, end_reason='window_complete', quality='observed', low_1pct_fps=low,
                relative_long_count=1, measured_seconds=60.0, relative_long_per_minute=1.0, condition=condition)


def _collect_files(conditions):
    """수집 모드 한 측정(session 'S')이 남기는 파일들: 파일마다 구간 1개 + 그 시점 측정 전체 집계."""
    lows = (100.0, 80.0, 90.0)
    files = []
    for index, condition in enumerate(conditions):
        files.append(dict(session='S', condition=condition, segments=[_segment(index, lows[index], condition)],
                          measurement=dict(low_1pct_fps=(100.0, 85.0, 86.0)[index], segments=index + 1)))
    return files


def _shape(groups):
    return tuple((g['condition'], g['segments'], g['measurements'],
                  g['measurement_low_1pct_fps'] and g['measurement_low_1pct_fps']['median']) for g in groups)


def check(label, files, expected_low):
    shapes = {_shape(condition_summary(list(order))) for order in permutations(files)}
    lows = {shape[-1][-1] for shape in shapes if shape}
    unstable = len(shapes) > 1 or lows != {expected_low}
    print(f'[{label}] 순서별 결과 {len(shapes)}가지 · 측정 전체 1% low 후보 {sorted(lows)} (기대 {expected_low})')
    return unstable


if __name__ == '__main__':
    same = check('같은 조건 3구간', _collect_files(('7+1',) * 3), 86.0)
    typed_late = check('첫 구간 뒤 조건 입력', _collect_files(('', '7+1', '7+1')), 86.0)
    reproduced = same or typed_late
    print('REPRODUCED: 파일 읽는 순서에 따라 측정 전체 값·묶음이 달라짐' if reproduced else 'not reproduced')
    sys.exit(1 if reproduced else 0)
