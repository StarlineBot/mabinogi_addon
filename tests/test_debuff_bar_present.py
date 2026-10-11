"""보스 HP바 감지(_bar_present) 회귀 테스트 — 실제 게임 캡처 기반.

디버프 트래커는 '영역에 보스 HP바가 보일 때만' 탐지하도록 게이팅한다. 바닥(흙·풀)을
바로 오인하면, 보스가 없는데도(마을·필드) 디버프가 뜨거나 모모 등이 오탐된다.
실제 캡처(tests/data/debuff_bar/*.png)로:
- 바닥(풀)은 바로 오인하지 않고(False)
- 보스 HP바(보라·노랑·빨강, 저HP·디버프 아이콘 포함)는 모두 바로 인식(True)
하는지 고정한다. (단색으로 길게 이어진 '채움 + 테두리' 특성으로 바닥 텍스처와 구분)
"""

from pathlib import Path

import cv2
import pytest

from mabinogi_addon.tracker.debuff_engine import DebuffEngine

_DATA = Path(__file__).parent / "data" / "debuff_bar"

# (파일, 바가 보이는가)
_CASES = [
    ("bg_grass_dark.png", False),  # 과거 오탐: 어두운 풀밭을 바로 오인하던 샘플
    ("bg_grass.png", False),
    ("bar_purple.png", True),
    ("bar_yellow_low.png", True),
    ("bar_with_debuffs.png", True),
    ("bar_red_low.png", True),
]


@pytest.mark.parametrize(("name", "expected"), _CASES)
def test_bar_present(name: str, expected: bool) -> None:
    path = _DATA / name
    if not path.exists():
        pytest.skip(f"샘플 없음: {name}")
    region = cv2.imread(str(path))
    assert region is not None, f"읽기 실패: {name}"
    assert DebuffEngine._bar_present(region) is expected
