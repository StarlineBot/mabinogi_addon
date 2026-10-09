"""보스 이름 식별 (기획서 12.2, Phase 2).

보스 HP바 왼쪽의 이름 텍스트를 읽어 '지금 어느 보스(페이즈)인지' 식별한다. 글자는
흰색이라 밝기 임계로 배경색 변화와 무관하게 남기고, 번들 이름 템플릿과 매칭한다.

접두어 함정: "레넨의 미이르"는 "레넨의 미이르 : 회한"의 접두어라 둘 다 높게 맞는다.
→ 점수가 임계 이상인 후보 중 **더 긴(구체적인) 템플릿**을 택해 구분한다.

번들: assets/boss/<id>/name.png (이진 템플릿). 임계·표시이름은 patterns.json(별도).
"""

from __future__ import annotations

import cv2
import numpy as np

from .. import paths
from ..image_io import imread

_BOSS_DIR = paths.resource_dir() / "boss"
_BRIGHT_THR = 200
MATCH_THRESHOLD = 0.6  # 이 점수 미만이면 '미식별'


def _binary(region_bgr: np.ndarray) -> np.ndarray:
    gray = (
        cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)
        if region_bgr.ndim == 3
        else region_bgr
    )
    _, b = cv2.threshold(gray, _BRIGHT_THR, 255, cv2.THRESH_BINARY)
    return b


def load_name_templates() -> dict[str, np.ndarray]:
    """assets/boss/<id>/name.png → {boss_id: 이진 템플릿}."""
    out: dict[str, np.ndarray] = {}
    if not _BOSS_DIR.exists():
        return out
    for sub in sorted(p for p in _BOSS_DIR.iterdir() if p.is_dir()):
        img = imread(sub / "name.png", cv2.IMREAD_GRAYSCALE)
        if img is not None:
            _, b = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
            out[sub.name] = b
    return out


_TEMPLATES = load_name_templates()


def identify(
    region_bgr: np.ndarray,
    templates: dict[str, np.ndarray] | None = None,
    threshold: float = MATCH_THRESHOLD,
) -> str | None:
    """이름 영역(BGR)에서 보스 id를 식별. 못 찾으면 None.

    임계 이상 후보 중 (점수, 템플릿 폭)이 가장 큰 것 — 즉 점수가 비슷하면 더 긴 이름을
    택해 접두어 혼동(레넨의 미이르 vs 레넨의 미이르:회한)을 막는다.
    """
    templates = _TEMPLATES if templates is None else templates
    if region_bgr is None or region_bgr.size == 0 or not templates:
        return None
    binary = _binary(region_bgr)
    best: str | None = None
    best_key = (-2.0, -1)
    for bid, t in templates.items():
        if t.shape[0] > binary.shape[0] or t.shape[1] > binary.shape[1]:
            continue
        score = float(cv2.matchTemplate(binary, t, cv2.TM_CCOEFF_NORMED).max())
        if score >= threshold:
            key = (round(score, 2), t.shape[1])  # 점수 → 폭(더 긴 이름 우선)
            if key > best_key:
                best_key, best = key, bid
    return best
