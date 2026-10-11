"""모모(네잎클로버) 오탐 회귀 테스트.

모모 아이콘은 단순한 초록 네잎클로버라, 10px 축소 매칭에서 풀·바닥 등 '매끈한 배경'과
상관계수가 0.66~0.67까지 올라간다. 기존 감지 임계(0.68)와 거의 붙어 있어 라이브
캡처에선 모모가 '걸림'으로 오판돼 오버레이에서 사라지는 버그가 있었다.

실게임 풀캡처로 고정한다:
- 모모가 실제로 걸린 장면: 감지돼야 한다(점수 ≥ 감지 임계).
- 모모가 안 걸린(마을·전투 초) 장면: 감지되면 안 된다(점수 < 감지 임계).
둘 사이 간격이 넉넉해야(≥0.08) 라이브 요동에도 안 뒤집힌다.
"""

from pathlib import Path

import cv2
import pytest

from mabinogi_addon.catalog import available_debuff_catalog, build_templates
from mabinogi_addon.tracker.debuff_engine import (
    DEBUFF_DETECT_THRESHOLD,
    DebuffEngine,
)

_DATA = Path(__file__).parent / "data"
# 디버프 줄이 들어오는 하단 중앙 영역(실측). 보스 HP바 위 디버프 아이콘 행을 넉넉히 포함.
_STRIP = (1150, 1260, 980, 1600)  # y0, y1, x0, x1 (2560x1440 기준)

# (파일, 모모가 실제로 걸려 있는가)
_CASES = [
    ("스크린샷 2026-10-09 201512.png", True),   # 펠롬 전투, 모모 걸림(초록 클로버 존재)
    ("스크린샷 2026-10-09 193901.png", True),   # 엇갈린 운명 전투, 모모 걸림
    ("스크린샷 2026-10-06 224732.png", False),  # 모모 없음(풀·바닥 오탐 원인 장면)
]


def _momo_score(engine: DebuffEngine, path: Path) -> float:
    img = cv2.imread(str(path))
    assert img is not None, f"테스트 이미지 없음: {path}"
    y0, y1, x0, x1 = _STRIP
    return engine.best_scores(img[y0:y1, x0:x1])["모모"]


@pytest.fixture(scope="module")
def engine() -> DebuffEngine:
    templates = build_templates(available_debuff_catalog())
    assert "모모" in templates, "모모 템플릿이 카탈로그에 있어야 함"
    return DebuffEngine(templates, list(templates))


@pytest.mark.parametrize("fname,present", _CASES)
def test_momo_detection_matches_reality(engine: DebuffEngine, fname: str, present: bool) -> None:
    path = _DATA / fname
    if not path.exists():
        pytest.skip(f"샘플 없음: {fname}")
    score = _momo_score(engine, path)
    if present:
        assert score >= DEBUFF_DETECT_THRESHOLD, (
            f"{fname}: 모모가 실제 걸렸는데 미감지 (점수 {score:.3f} < {DEBUFF_DETECT_THRESHOLD})"
        )
    else:
        assert score < DEBUFF_DETECT_THRESHOLD, (
            f"{fname}: 모모 없는데 오탐 (점수 {score:.3f} ≥ {DEBUFF_DETECT_THRESHOLD})"
        )


def test_momo_separation_margin(engine: DebuffEngine) -> None:
    """모모 '걸림' 최저점과 '없음' 최고점 사이 간격이 임계를 여유 있게 감싸는지."""
    present = [
        _momo_score(engine, _DATA / f) for f, p in _CASES if p and (_DATA / f).exists()
    ]
    absent = [
        _momo_score(engine, _DATA / f) for f, p in _CASES if not p and (_DATA / f).exists()
    ]
    if not present or not absent:
        pytest.skip("샘플 부족")
    assert min(present) - max(absent) >= 0.08, (
        f"모모 걸림최저 {min(present):.3f} vs 없음최고 {max(absent):.3f} — 간격 부족"
    )
