"""보스 이름 식별 (기획서 12.2, Phase 2).

보스 HP바 왼쪽의 이름 텍스트를 읽어 '지금 어느 보스(페이즈)인지' 식별한다. 글자는
흰색이라 밝기 임계로 배경색 변화와 무관하게 남기고, 번들 이름 템플릿과 매칭한다.

0.31.0: 픽셀 그대로 비교가 실패하면 글자 높이를 맞춰 다시 비교한다(identify_by_shape, 해상도·굵기 차이).

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


def load_name_variants() -> dict[str, list[np.ndarray]]:
    """Additional observed glyph renderings, retaining the original primary samples."""
    out = {}
    if _BOSS_DIR.exists():
        for sub in sorted(p for p in _BOSS_DIR.iterdir() if p.is_dir()):
            samples = []
            for path in sorted(sub.glob("name_*.png")):
                image = imread(path, cv2.IMREAD_GRAYSCALE)
                if image is not None:
                    samples.append(cv2.threshold(image, 127, 255, cv2.THRESH_BINARY)[1])
            if samples:
                out[sub.name] = samples
    return out


_VARIANTS = load_name_variants()


def identify(
    region_bgr: np.ndarray,
    templates: dict[str, np.ndarray] | None = None,
    threshold: float = MATCH_THRESHOLD,
    *, variants: dict[str, list[np.ndarray]] | None = None,
) -> str | None:
    """이름 영역(BGR)에서 보스 id를 식별. 못 찾으면 None.

    임계 이상 후보 중 (점수, 템플릿 폭)이 가장 큰 것 — 즉 점수가 비슷하면 더 긴 이름을
    택해 접두어 혼동(레넨의 미이르 vs 레넨의 미이르:회한)을 막는다.
    """
    if templates is None:
        templates = _TEMPLATES
        variants = _VARIANTS if variants is None else variants
    variants = {} if variants is None else variants
    if region_bgr is None or region_bgr.size == 0 or not templates:
        return None
    binary = _binary(region_bgr)
    best: str | None = None
    best_key = (-2.0, -1)
    for bid, t in templates.items():
        for sample in (t, *variants.get(bid, ())):
            if sample.shape[0] > binary.shape[0] or sample.shape[1] > binary.shape[1]:
                continue
            score = float(cv2.matchTemplate(binary, sample, cv2.TM_CCOEFF_NORMED).max())
            if score >= threshold:
                key = (round(score, 2), sample.shape[1])
                if key > best_key:
                    best_key, best = key, bid
    if best is not None:
        return best
    # 2단계(0.31.0): 픽셀 그대로 비교가 실패할 때만 — 글자 높이를 맞춰 비교(해상도·굵기가 달라도)
    return identify_by_shape(binary, templates, variants)[0]


# ---- 2단계: 글자 높이 맞춤 비교(0.31.0, QA 시제품·tests/data 보스 바 보정) ----
# 4K처럼 이름 글자가 1~2px 크거나 굵으면 픽셀 그대로 비교(위)는 실패한다. 이름 글자 묶음만 잘라 높이를 맞추고
# 살짝 흐려 모양을 비교한다. 이름 길이가 다르면(접두어 '레넨의 미이르' vs '… : 회한') 폭 비율을 곱해 긴 쪽과 구분.
SHAPE_HEIGHT = 24
# 보정(tests/data 보스 바 64장 + 펠롬 보조 바): 기존 식별 47장 1위 모두 일치. 맞는 보스는 4K 변형 없이도 0.72 이상
# (페타크 0.72·회한 0.72·레넨 0.74). 틀린 쪽 최고는 '○○의 ○○○' 모양이 닮은 이름 — 펠롬 보조 바 '어둠의 에르그' 0.53,
# 망집의 키리아 0.37(둘 다 → 페타크), 작은 글자 페타크(10-11 123333) 0.39, 기브넨 0.23.
# 그 사이 0.6으로(시제품 기준 0.35는 키리아·에르그를 페타크로 오인). 123333은 None(그 화면은 HP 판독도 확정 안 됨).
SHAPE_MIN_SCORE = 0.6
SHAPE_MIN_MARGIN = 0.08  # 1위와 2위 차
_GLYPH_MIN_H = 3
_GLYPH_MAX_H = 0.8  # 영역 높이 대비(위아래 테두리선 제외)
_GLYPH_MAX_W = 0.5  # 영역 폭 대비(가로로 긴 선 제외)


def _shape(binary: np.ndarray, *, filter_lines: bool = True) -> np.ndarray | None:
    """이진 이름 영역 → 이름 글자 묶음을 높이 SHAPE_HEIGHT로 맞추고 3×3 흐림(float32). 글자가 없으면 None."""
    if binary is None or binary.size == 0:
        return None
    count, _labels, stats, _ = cv2.connectedComponentsWithStats((binary > 0).astype(np.uint8))
    H, W = binary.shape[:2]
    keep = [s for s in stats[1:count]
            if s[3] >= _GLYPH_MIN_H and (not filter_lines or (s[3] <= _GLYPH_MAX_H * H and s[2] < _GLYPH_MAX_W * W))]
    if not keep:
        return None
    x0 = min(s[0] for s in keep)
    y0 = min(s[1] for s in keep)
    x1 = max(s[0] + s[2] for s in keep)
    y1 = max(s[1] + s[3] for s in keep)
    crop = (binary[y0:y1, x0:x1] > 0).astype(np.float32)
    if crop.shape[0] < _GLYPH_MIN_H or crop.shape[1] < 2:
        return None
    width = max(2, round(crop.shape[1] * SHAPE_HEIGHT / crop.shape[0]))
    resized = cv2.resize(crop, (width, SHAPE_HEIGHT), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(resized, (3, 3), 0)


_SHAPE_CACHE: dict[int, dict[str, list[np.ndarray]]] = {}


def _reference_shapes(templates, variants) -> dict[str, list[np.ndarray]]:
    key = id(templates) ^ (id(variants) << 1)
    cached = _SHAPE_CACHE.get(key)
    if cached is None:
        cached = {}
        for bid, t in templates.items():
            shapes = [_shape(sample, filter_lines=False) for sample in (t, *variants.get(bid, ()))]
            cached[bid] = [shape for shape in shapes if shape is not None]
        _SHAPE_CACHE.clear()  # 기준 묶음은 보통 하나 — 오래된 것은 버린다
        _SHAPE_CACHE[key] = cached
    return cached


def shape_scores(binary: np.ndarray, templates, variants) -> dict[str, float]:
    """보스별 글자 높이 맞춤 점수(TM_CCOEFF_NORMED × 폭 비율), 샘플 중 최고."""
    observed = _shape(binary)
    if observed is None:
        return {}
    out = {}
    for bid, refs in _reference_shapes(templates, variants).items():
        best = -1.0
        for ref in refs:
            wo, wr = observed.shape[1], ref.shape[1]
            resized = cv2.resize(observed, (wr, SHAPE_HEIGHT), interpolation=cv2.INTER_AREA)
            score = float(cv2.matchTemplate(resized, ref, cv2.TM_CCOEFF_NORMED)[0, 0])
            if not np.isfinite(score):
                continue
            best = max(best, score * min(wo, wr) / max(wo, wr))
        out[bid] = best
    return out


def identify_by_shape(binary: np.ndarray, templates, variants) -> tuple[str | None, dict[str, float]]:
    """(보스 id 또는 None, 점수들). 1위 ≥ SHAPE_MIN_SCORE 그리고 2위와 SHAPE_MIN_MARGIN 이상 차이일 때만."""
    scores = shape_scores(binary, templates, variants)
    if not scores:
        return None, scores
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_id, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else -1.0
    if top < SHAPE_MIN_SCORE or top - second < SHAPE_MIN_MARGIN:
        return None, scores
    return top_id, scores
