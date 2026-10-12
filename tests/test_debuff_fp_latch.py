"""모모·방해 카드 '이력 임계 래치' 오탐 회귀 테스트.

실게임(3차) 프레임에서 관측된 오탐: 스킬 이펙트가 순간 detect 임계(0.68)를 넘겨
'걸림'으로 래치되면, 이후 점수가 0.58~0.60으로 내려와도 옛 release(0.58)보다 높아
풀리지 않아 '안 걸렸는데 걸린 것처럼' 남았다. 아이콘별 임계(detect 0.80/release 0.70)로
그 잔류 점수(~0.58~0.60)가 release 아래로 떨어져 정상 해제된다.

실게임 풀캡처(사용자 제보, 디버프 영역 = config 1016,1209 525×79)로 고정한다:
- 안 걸린 아이콘은 '이펙트로 한 번 래치된 뒤에도' 해제돼야 한다(score < per-icon release).
"""

from pathlib import Path

import cv2
import pytest

from mabinogi_addon.catalog import available_debuff_catalog, build_templates
from mabinogi_addon.tracker.debuff_engine import DebuffEngine

_DATA = Path(__file__).parent / "data"
# 사용자 디버프 영역(config): x,y,w,h
_REGION = (1016, 1209, 525, 79)

# (파일, 안 걸렸는데 래치로 FP 나던 아이콘)
_CASES = [
    ("스크린샷 2026-10-12 200511.png", "모모"),
    ("스크린샷 2026-10-12 200625.png", "방해 카드"),
]


@pytest.fixture(scope="module")
def templates():
    return build_templates(available_debuff_catalog())


@pytest.mark.parametrize("fname,icon", _CASES)
def test_latched_false_positive_releases(templates, fname: str, icon: str) -> None:
    path = _DATA / fname
    if not path.exists():
        pytest.skip(f"샘플 없음: {fname}")
    img = cv2.imread(str(path))
    assert img is not None, f"로드 실패: {fname}"
    x, y, w, h = _REGION
    region = img[y:y + h, x:x + w]

    eng = DebuffEngine(templates, [icon])
    small = eng._scale(region)
    score = eng._best(small, icon)
    # 직전 틱에 이펙트 번쩍으로 '걸림' 래치됐다고 가정.
    eng._matched[icon] = True
    matched = eng._detect(small, icon)
    assert not matched, (
        f"{fname}: '{icon}' 안 걸렸는데 래치 후에도 '걸림'으로 남음 "
        f"(점수 {score:.3f} ≥ release {eng.release_threshold_for(icon)})"
    )
