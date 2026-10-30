"""개발용: 4K 보스 이름 글자 변형(0.31.0, 사용자 제보: 4K에서 보스 패턴·1분 헤일로가 안 뜸).

4K에서는 이름 글자가 굵게 그려져 기존 이름 템플릿과 회한 0.40·레넨 0.46(< 0.6)로만 맞았다.
214648(회한 100%) 바 왼쪽 이름을 이진화해 두 변형을 만든다(load_name_variants가 읽는 name_*.png).
- lenen_miir_hoehan/name_uhd_20261030.png: '레넨의 미이르 : 회한' 전체
- lenen_miir/name_uhd_20261030.png: 같은 자리의 '레넨의 미이르'까지만(접두어 함정: 회한 변형만 있으면 4K 일반 레넨이
  회한으로 잡힐 수 있어, 일반 레넨도 4K 변형을 두고 동점이면 긴 이름을 고르는 기존 규칙으로 나눈다)
0055251(회한 86.15%)은 쓰지 않고 따로 검증한다(tests/test_boss_name_4k.py).

    uv run python scripts/build_boss_name_uhd.py
"""

from pathlib import Path

import numpy as np

from mabinogi_addon import image_io, paths
from mabinogi_addon.detect.boss_name_matcher import _binary

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "tests/data/mabinogi_2026_10_30_214648.png"
BAR = (1658, 1968, 521, 37)
PREFIX_END = 116  # '레넨의 미이르' 마지막 글자 다음 열(그 뒤 빈 열 115~124, ':' 124)


def trim(binary):
    ys, xs = np.nonzero(binary)
    if not len(xs):
        raise ValueError("empty sample")
    return binary[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def build():
    frame = image_io.imread(ROOT / SOURCE)
    x, y, w, h = BAR
    name = _binary(frame[y:y + h, x:x + w][:, :312])
    samples = {
        "boss/lenen_miir_hoehan/name_uhd_20261030.png": trim(name),
        "boss/lenen_miir/name_uhd_20261030.png": trim(name[:, :PREFIX_END]),
    }
    for relative, sample in samples.items():
        target = paths.resource_dir() / relative
        if not image_io.imwrite(target, sample):
            raise OSError(f"cannot save {target}")
        print(relative, sample.shape, int(np.count_nonzero(sample)))


if __name__ == "__main__":
    build()
