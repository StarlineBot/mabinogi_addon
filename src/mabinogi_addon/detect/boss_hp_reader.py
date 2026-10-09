"""보스 HP% 판독 (기획서 12).

보스 체력바의 'XX.XX %' 영역에서 정수 HP%를 읽는다. 바 배경색이 HP에 따라 변하므로
(길이로는 % 표시 안 함), **밝기 임계**로 흰 글씨만 남기고(배경색 무관) 0~9 숫자 템플릿으로
글자를 분류한다. 소수점 앞 **정수부만** 쓴다(패턴 임계는 정수 %).

숫자 템플릿: assets/boss_hp_digits/{0..9}.png (이 HP바 폰트 전용, 실게임 스샷에서 추출).
"""

from __future__ import annotations

import cv2
import numpy as np

from .. import paths
from ..image_io import imread

_DIGIT_DIR = paths.resource_dir() / "boss_hp_digits"
_BRIGHT_THR = 200  # 흰 글씨만 남기는 밝기 임계(배경색 보라/파랑 무관)
_DOT_MAX_H = 6  # 이 높이 이하면 소수점(.) — 정수부 끝
_PCT_MIN_W = 12  # 이 폭 이상이면 % 기호 — 끝


def _load_digits() -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for d in "0123456789":
        img = imread(_DIGIT_DIR / f"{d}.png", cv2.IMREAD_GRAYSCALE)
        if img is not None:
            _, b = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
            out[d] = b
    return out


_DIGITS = _load_digits()


def _binary(region_bgr: np.ndarray) -> np.ndarray:
    gray = (
        cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)
        if region_bgr.ndim == 3
        else region_bgr
    )
    _, b = cv2.threshold(gray, _BRIGHT_THR, 255, cv2.THRESH_BINARY)
    return b


def _glyphs(binary: np.ndarray) -> list[tuple[int, int, int, int]]:
    """열 간격으로 글자 덩어리 분절 → (x0, x1, y0, y1) 목록(왼→오른쪽)."""
    col = (binary > 127).any(axis=0)
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for x, v in enumerate(col):
        if v and start is None:
            start = x
        elif not v and start is not None:
            spans.append((start, x))
            start = None
    if start is not None:
        spans.append((start, len(col)))
    out = []
    for x0, x1 in spans:
        rows = np.where((binary[:, x0:x1] > 127).any(axis=1))[0]
        if len(rows):
            out.append((x0, x1, int(rows.min()), int(rows.max()) + 1))
    return out


def _classify(glyph: np.ndarray, templates: dict[str, np.ndarray]) -> tuple[str, float]:
    best, best_score = "", -2.0
    for d, t in templates.items():
        th, tw = t.shape[:2]
        g = cv2.resize(glyph, (tw, th), interpolation=cv2.INTER_NEAREST)
        _, g = cv2.threshold(g, 127, 255, cv2.THRESH_BINARY)
        score = float(cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED).max())
        if score > best_score:
            best, best_score = d, score
    return best, best_score


def read_percent(
    region_bgr: np.ndarray,
    templates: dict[str, np.ndarray] | None = None,
    min_score: float = 0.3,
) -> int | None:
    """HP바의 % 영역(BGR)에서 정수 HP%(0~100)를 읽는다. 못 읽으면 None.

    소수점(.) 전까지의 숫자만 모아 정수부로 쓴다. 한 글자라도 신뢰도 미달이면 None.
    """
    templates = _DIGITS if templates is None else templates
    if region_bgr is None or region_bgr.size == 0 or not templates:
        return None
    binary = _binary(region_bgr)
    digits: list[str] = []
    for x0, x1, y0, y1 in _glyphs(binary):
        h, w = y1 - y0, x1 - x0
        if h <= _DOT_MAX_H:  # 소수점 → 정수부 끝
            break
        if w >= _PCT_MIN_W:  # % 기호 → 끝
            break
        d, score = _classify(binary[y0:y1, x0:x1], templates)
        if score < min_score:
            return None
        digits.append(d)
    if not digits:
        return None
    try:
        value = int("".join(digits))
    except ValueError:
        return None
    return value if 0 <= value <= 100 else None
