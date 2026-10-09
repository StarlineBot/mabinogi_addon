"""보스 HP% 판독 (기획서 12).

보스 체력바의 'XXX.XX %' 영역에서 정수 HP%를 읽는다. 바 배경색이 HP에 따라
변하고(초록/노랑/빨강/보라), 바가 **밝을 때는 글자가 어둡고** 어두울 때는 밝아
명암 극성이 뒤집힌다. 그래서 밝기 임계 대신 **색거리**(바 배경색에서 색이 먼
픽셀 = 글자)로 이진화한다 — 흰/회/검 글자는 채도 높은 바 색과 항상 멀다.

숫자는 우측 정렬 monospace라, **바 오른쪽 끝에서 각 정수 자리 위치가 고정**이다.
분절(글자 사이 빈틈 찾기)은 밝은 바에서 글자가 붙어 실패하므로 쓰지 않고,
오른쪽 끝 기준 **고정 칸**을 잘라 각 칸을 숫자 템플릿과 매칭한다(기획서 12.3).

입력 region 은 **보스 HP바 전체 박스**(오른쪽 끝 = 바 오른쪽 끝). 칸 위치·간격은
기준 해상도(2560×1440, 바 높이 36px) 기준이며, 박스 높이로 스케일 보정한다.

숫자 템플릿: assets/boss_hp_digits/d{0..9}_{i}.png (색거리 이진화, 자리당 다중 샘플).
"""

from __future__ import annotations

import cv2
import numpy as np

from .. import paths
from ..image_io import imread

_DIGIT_DIR = paths.resource_dir() / "boss_hp_digits"
_COLOR_DIST = 70  # 바 배경색에서 이 거리 이상이면 글자
_REF_H = 36.0  # 기준 바 높이(px) — 스케일 기준
_FIRST = 62.0  # 바 오른쪽 끝 → 최우측 정수자리 right edge (기준 해상도)
_PITCH = 11.0  # 정수 자리 간격(기준 해상도)
_YBAND = (0.28, 0.82)  # 숫자 세로 밴드(바 테두리 제외)
_MIN_PX = 8  # 칸에 이 미만이면 빈 칸(자리 없음)
_MIN_SCORE = 0.4


def _load_digits() -> dict[str, list[np.ndarray]]:
    out: dict[str, list[np.ndarray]] = {}
    if not _DIGIT_DIR.exists():
        return out
    for p in sorted(_DIGIT_DIR.glob("d*_*.png")):
        img = imread(p, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        _, b = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
        out.setdefault(p.name[1], []).append(b)
    return out


_DIGITS = _load_digits()


def _color_mask(region_bgr: np.ndarray) -> np.ndarray:
    """바 배경색(중앙값)에서 색이 먼 픽셀 = 글자. 극성·색 무관."""
    r = region_bgr.astype(np.int16)
    med = np.median(r.reshape(-1, 3), axis=0)
    dist = np.sqrt(((r - med) ** 2).sum(axis=2))
    return (dist > _COLOR_DIST).astype(np.uint8) * 255


def _classify(
    glyph: np.ndarray, templates: dict[str, list[np.ndarray]]
) -> tuple[str | None, float]:
    best, best_score = None, -2.0
    for d, samples in templates.items():
        for t in samples:
            g = cv2.resize(glyph, (t.shape[1], t.shape[0]), interpolation=cv2.INTER_NEAREST)
            _, g = cv2.threshold(g, 127, 255, cv2.THRESH_BINARY)
            score = float(cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED).max())
            if score > best_score:
                best, best_score = d, score
    return (best, best_score) if best_score >= _MIN_SCORE else (None, best_score)


def read_percent(
    region_bgr: np.ndarray,
    templates: dict[str, list[np.ndarray]] | None = None,
) -> int | None:
    """보스 HP바 박스(BGR, 오른쪽 끝 = 바 오른쪽 끝)에서 정수 HP%(0~100)를 읽는다.

    못 읽으면 None(틀린 값보다 안전). 우측 정렬이라 오른쪽 끝에서 고정 칸을 잘라
    왼쪽으로 최대 3자리까지 읽고, 빈 칸을 만나면 멈춘다.
    """
    templates = _DIGITS if templates is None else templates
    if region_bgr is None or region_bgr.size == 0 or not templates:
        return None
    if region_bgr.ndim != 3:
        return None
    h, w = region_bgr.shape[:2]
    scale = h / _REF_H
    first = _FIRST * scale
    pitch = _PITCH * scale
    mask = _color_mask(region_bgr)[int(h * _YBAND[0]):int(h * _YBAND[1])]

    digits: list[str] = []  # 오른쪽 → 왼쪽
    for k in range(1, 4):  # 정수부 최대 3자리(0~100)
        right = round(w - first - pitch * (k - 1))
        left = round(right - pitch)
        if left < 0:
            break
        cell = mask[:, max(left, 0):right]
        if cell.size == 0 or int((cell > 127).sum()) < _MIN_PX:
            break  # 빈 칸 → 정수부 끝
        ys = np.where((cell > 127).any(axis=1))[0]
        xs = np.where((cell > 127).any(axis=0))[0]
        glyph = cell[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        d, _ = _classify(glyph, templates)
        if d is None:
            return None
        digits.append(d)

    if not digits:
        return None
    try:
        value = int("".join(reversed(digits)))
    except ValueError:
        return None
    return value if 0 <= value <= 100 else None
