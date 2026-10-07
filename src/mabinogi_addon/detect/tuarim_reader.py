"""투아림 % 숫자 판독.

투아림 리더 박스 영역(BGR)을 이진화한 뒤, 0~9 숫자 템플릿을 matchTemplate으로 찾아
x 순서로 정렬 → 두 자리까지 이어 % 정수로 돌려준다. '%' 기호는 무시(숫자만 인식).

숫자 템플릿은 detect/templates/tuarim/{0..9}.png. 폰트가 버프 타이머와 달라 별도로
뜬다(집 스크린샷에서 추출 예정). 템플릿이 없으면 None(판독 불가).
"""

from __future__ import annotations

import cv2
import numpy as np

from .. import paths
from ..image_io import imread
from .binarize import binarize

_TEMPLATE_DIR = paths.detect_templates_dir() / "tuarim"
GLYPH_THRESHOLD = 0.7


def _load_templates() -> dict[str, np.ndarray]:
    if not _TEMPLATE_DIR.exists():
        return {}
    out: dict[str, np.ndarray] = {}
    for path in sorted(_TEMPLATE_DIR.glob("*.png")):
        img = imread(path, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            out[path.stem] = img
    return out


_TEMPLATES = _load_templates()


def _occurrences(strip, label, template, threshold):
    if template.shape[0] > strip.shape[0] or template.shape[1] > strip.shape[1]:
        return []
    result = cv2.matchTemplate(strip, template, cv2.TM_CCOEFF_NORMED)
    h, w = template.shape[:2]
    found = []
    while True:
        _mn, max_v, _ml, max_l = cv2.minMaxLoc(result)
        if max_v < threshold:
            break
        x, y = max_l
        found.append((x, float(max_v), label, w))
        x0, y0 = max(0, x - w // 2), max(0, y - h // 2)
        result[y0 : y + h // 2 + 1, x0 : x + w // 2 + 1] = -1.0
    return found


def _nms(hits):
    """x가 겹치는 서로 다른 숫자 후보 중 점수 높은 것만 남긴다."""
    hits.sort(key=lambda o: -o[1])
    kept: list = []
    for x, score, label, w in hits:
        if all(abs(x - kx) >= max(4, w // 2) for kx, _, _, _ in kept):
            kept.append((x, score, label, w))
    kept.sort(key=lambda o: o[0])  # x 순서(왼→오른쪽)
    return kept


def read_percent(
    region_bgr: np.ndarray,
    templates: dict[str, np.ndarray] | None = None,
    threshold: float = GLYPH_THRESHOLD,
) -> int | None:
    """리더 박스 영역에서 % 정수(0~99)를 읽는다. 못 읽으면 None."""
    tmpls = _TEMPLATES if templates is None else templates
    if not tmpls or region_bgr is None or region_bgr.size == 0:
        return None
    binary = binarize(region_bgr)
    hits: list = []
    for label, tmpl in tmpls.items():
        hits += _occurrences(binary, label, tmpl, threshold)
    if not hits:
        return None
    digits = [label for _x, _s, label, _w in _nms(hits)]
    if not digits:
        return None
    try:
        return int("".join(digits[:2]))  # 두 자리까지
    except ValueError:
        return None
