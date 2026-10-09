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

# 멀티스케일: 해상도가 높을수록 게임이 숫자를 크게 그려(4K>1440p) 1440p 템플릿과
# 안 맞는다. 템플릿을 여러 배율로 '확대'해 맞춰보고 가장 또렷이 맞는 배율을 쓴다.
# 축소(×<1)는 넣지 않는다: 작아진 '1'(세로 막대)이 다른 글자의 세로획에 완벽히
# 과매칭돼 오독을 만든다(예 '6'→'11'). 템플릿은 최저 해상도(1440p) 기준이라 실사용은
# 전부 확대로 충분하고, 과하게 확대되면 '템플릿>영역'이라 자동 제외된다. 1.0을 먼저
# 둬(동일 해상도 빠른 경로·동점 우선).
_SCALES = (1.0, 1.15, 1.3, 1.45, 1.6, 1.75)


def _load_templates() -> dict[str, np.ndarray]:
    if not _TEMPLATE_DIR.exists():
        return {}
    out: dict[str, np.ndarray] = {}
    for path in sorted(_TEMPLATE_DIR.glob("*.png")):
        img = imread(path, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            out[path.stem] = img
    return out


def _scale_binary(t: np.ndarray, scale: float) -> np.ndarray:
    """이진 템플릿을 배율로 리사이즈 후 다시 이진화(캡처도 이진이라 모양만 비교)."""
    h, w = t.shape[:2]
    nh, nw = max(2, round(h * scale)), max(2, round(w * scale))
    r = cv2.resize(t, (nw, nh), interpolation=cv2.INTER_LINEAR)
    _, b = cv2.threshold(r, 127, 255, cv2.THRESH_BINARY)
    return b


def _scaled_sets(tmpls: dict[str, np.ndarray]) -> dict[float, dict[str, np.ndarray]]:
    """배율별 템플릿 세트. scale 1.0은 원본 그대로."""
    out: dict[float, dict[str, np.ndarray]] = {}
    for s in _SCALES:
        out[s] = tmpls if s == 1.0 else {k: _scale_binary(v, s) for k, v in tmpls.items()}
    return out


_TEMPLATES = _load_templates()
_SCALED_DEFAULT = _scaled_sets(_TEMPLATES) if _TEMPLATES else {}


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


def _match_at(binary, tmpls, threshold) -> tuple[int, float] | None:
    """한 배율 세트로 읽기 시도. (값, peak점수) 또는 None.

    peak = 이 배율에서 가장 강한 숫자 매칭 점수. 정답 배율에서 글자가 가장 또렷이
    맞아 peak가 제일 높으므로, 여러 배율 중 peak가 최고인 배율의 읽기를 택한다.
    (평균/자릿수로 고르면 '1' 같은 단순 글자가 엉뚱한 배율에서 오독을 일으킴.)
    """
    hits: list = []
    for label, tmpl in tmpls.items():
        hits += _occurrences(binary, label, tmpl, threshold)
    if not hits:
        return None
    peak = max(s for _x, s, _l, _w in hits)
    kept = _nms(hits)[:2]  # 두 자리까지
    if not kept:
        return None
    digits = [label for _x, _s, label, _w in kept]
    try:
        value = int("".join(digits))
    except ValueError:
        return None
    return value, peak


def read_percent(
    region_bgr: np.ndarray,
    templates: dict[str, np.ndarray] | None = None,
    threshold: float = GLYPH_THRESHOLD,
) -> int | None:
    """리더 박스 영역에서 % 정수(0~99)를 읽는다. 못 읽으면 None.

    여러 배율로 시도해(해상도가 달라 숫자 크기가 템플릿과 다른 경우 대응) 글자가
    가장 또렷하게 맞는 배율의 결과를 쓴다. 동점이면 1.0(동일 해상도)이 먼저라 이긴다.
    """
    if region_bgr is None or region_bgr.size == 0:
        return None
    if templates is None:
        sets = _SCALED_DEFAULT
    elif not templates:
        return None
    else:
        sets = _scaled_sets(templates)
    if not sets:
        return None
    binary = binarize(region_bgr)
    best: tuple[float, int] | None = None  # (peak점수, 값)
    for scale in _SCALES:
        got = _match_at(binary, sets[scale], threshold)
        if got is None:
            continue
        value, peak = got
        if best is None or peak > best[0]:  # 엄격한 > → 동점이면 먼저 온 1.0 우선
            best = (peak, value)
    return best[1] if best else None
