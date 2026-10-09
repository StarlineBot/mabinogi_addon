"""보스 HP% 판독 (기획서 12).

보스 체력바의 'XXX.XX %' 영역에서 정수 HP%를 읽는다. 바 배경색이 HP에 따라
변하고(초록/노랑/빨강/보라), 밝은 바에선 글자가 어둡고 어두운 바에선 밝아 명암
극성이 뒤집힌다. 그래서 밝기 임계 대신 **색거리**(바 배경색에서 색이 먼 픽셀 =
글자)로 이진화한다 — 흰/회/검 글자는 채도 높은 바 색과 항상 멀다.

숫자는 우측 정렬 monospace라 오른쪽 끝 기준 고정 칸으로 자른다. 다만 영역 박스의
오른쪽 끝이 바 끝과 몇 px만 어긋나도 칸이 밀려 깨지므로, **정렬 오프셋을 조금씩
옮겨 보며 가장 확신(매칭 점수) 높은 판독을 고르는 자동정렬**로 그 민감도를 없앴다.
(기획서 12.3)

입력 region 은 보스 HP바 박스(오른쪽 끝 ≈ 바 오른쪽 끝). 칸 위치·간격은 기준
해상도(2560×1440, 바 높이 36px) 기준이며 박스 높이로 스케일 보정한다.

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
_SEARCH = 8  # 정렬 오프셋 탐색 범위(±, 기준 해상도 px)
_ACCEPT = 0.45  # 최고 정렬의 최저 자리 점수가 이 이상이어야 채택


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
    return best, best_score


def _read_at(
    band: np.ndarray, w: int, first: float, pitch: float,
    templates: dict[str, list[np.ndarray]],
) -> tuple[int | None, float]:
    """한 정렬에서 오른쪽 끝 기준 고정 칸으로 최대 3자리 읽기. (값, 최저 자리 점수)."""
    digits: list[str] = []
    scores: list[float] = []
    for k in range(1, 4):
        right = round(w - first - pitch * (k - 1))
        left = round(right - pitch)
        if left < 0:
            break
        cell = band[:, max(left, 0):right]
        if cell.size == 0 or int((cell > 127).sum()) < _MIN_PX:
            break  # 빈 칸 → 정수부 끝
        ys = np.where((cell > 127).any(axis=1))[0]
        xs = np.where((cell > 127).any(axis=0))[0]
        d, sc = _classify(cell[ys.min():ys.max() + 1, xs.min():xs.max() + 1], templates)
        if d is None:
            return None, -2.0
        digits.append(d)
        scores.append(sc)
    if not digits:
        return None, -2.0
    try:
        value = int("".join(reversed(digits)))
    except ValueError:
        return None, -2.0
    if not 0 <= value <= 100:
        return None, -2.0
    return value, min(scores)


def read_percent(
    region_bgr: np.ndarray,
    templates: dict[str, list[np.ndarray]] | None = None,
) -> int | None:
    """보스 HP바 박스(BGR, 오른쪽 끝 ≈ 바 오른쪽 끝)에서 정수 HP%(0~100)를 읽는다.

    못 읽으면 None(틀린 값보다 안전). 정렬 오프셋을 ±탐색해 가장 확신 높은 판독을
    고르므로, 박스가 몇 px 어긋나도 알아서 맞춰 읽는다.
    """
    templates = _DIGITS if templates is None else templates
    if region_bgr is None or region_bgr.size == 0 or not templates:
        return None
    if region_bgr.ndim != 3:
        return None
    h, w = region_bgr.shape[:2]
    scale = h / _REF_H
    band = _color_mask(region_bgr)[int(h * _YBAND[0]):int(h * _YBAND[1])]
    pitch = _PITCH * scale
    span = max(1, round(_SEARCH * scale))

    best_val: int | None = None
    best_score = -2.0
    for shift in range(-span, span + 1):
        val, score = _read_at(band, w, _FIRST * scale + shift, pitch, templates)
        if val is not None and score > best_score:
            best_val, best_score = val, score
    return best_val if best_score >= _ACCEPT else None
