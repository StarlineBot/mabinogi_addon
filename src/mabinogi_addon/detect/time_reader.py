"""시간 판독 (기획서 4.3).

시간 글자 영역을 이진화한 뒤, 숫자(0~9)·단위(일/시간/분/초) 템플릿을 matchTemplate으로
찾아 x 순서로 정렬 → 토큰 파싱 → 총 초로 환산한다. 한글 음절 자모 간격 때문에 열 분할
대신 글자별 템플릿 매칭을 쓴다(간격 무관).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .binarize import binarize

_TEMPLATE_DIR = Path(__file__).parent / "templates" / "time"

# 단위 라벨 → 초. 숫자 라벨은 "0".."9".
_UNIT_SECONDS = {"day": 86400, "hour": 3600, "bun": 60, "cho": 1}

# 글자 매칭 임계. 이진 템플릿이라 정답은 ~1.0, 오답은 낮다.
GLYPH_THRESHOLD = 0.7


def _load_templates() -> dict[str, np.ndarray]:
    return {
        path.stem: cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        for path in sorted(_TEMPLATE_DIR.glob("*.png"))
    }


_TEMPLATES = _load_templates()


def _occurrences(strip: np.ndarray, label: str, template: np.ndarray, threshold: float):
    """strip에서 template이 threshold 이상인 위치들을 (x, score, label, width)로.

    같은 글자가 여러 번(예: '22') 나오므로, 찾을 때마다 주변을 눌러 반복 검출.
    """
    if template.shape[0] > strip.shape[0] or template.shape[1] > strip.shape[1]:
        return []
    result = cv2.matchTemplate(strip, template, cv2.TM_CCOEFF_NORMED)
    h, w = template.shape[:2]
    found = []
    while True:
        _min_v, max_v, _min_l, max_l = cv2.minMaxLoc(result)
        if max_v < threshold:
            break
        x, y = max_l
        found.append((x, float(max_v), label, w))
        x0, y0 = max(0, x - w // 2), max(0, y - h // 2)
        result[y0 : y + h // 2 + 1, x0 : x + w // 2 + 1] = -1.0  # 주변 억제
    return found


def _nms(hits):
    """같은 위치에 겹친 서로 다른 글자 후보 중 점수 높은 것만 남긴다."""
    hits.sort(key=lambda o: -o[1])
    kept: list[tuple[int, float, str, int]] = []
    for x, score, label, w in hits:
        center = x + w / 2
        if any(abs(center - (kx + kw / 2)) < max(w, kw) * 0.5 for kx, _, _, kw in kept):
            continue
        kept.append((x, score, label, w))
    kept.sort(key=lambda o: o[0])  # x 오름차순
    return kept


def _parse(labels: list[str]) -> int:
    """['3','day','2','2','hour','1','bun'] → 초. 단위 앞의 숫자들을 모아 곱한다."""
    total = 0
    number: int | None = None
    for label in labels:
        if label.isdigit():
            number = (number or 0) * 10 + int(label)
        elif label in _UNIT_SECONDS:
            total += (number or 0) * _UNIT_SECONDS[label]
            number = None
    return total


def read_time(time_bgr: np.ndarray, threshold: float = GLYPH_THRESHOLD) -> int | None:
    """시간 영역(BGR)에서 남은 시간을 초로. 글자를 못 찾으면 None."""
    strip = binarize(time_bgr)
    hits: list = []
    for label, template in _TEMPLATES.items():
        hits.extend(_occurrences(strip, label, template, threshold))
    if not hits:
        return None
    labels = [label for _x, _s, label, _w in _nms(hits)]
    if not any(lab in _UNIT_SECONDS for lab in labels):
        return None  # 단위가 하나도 없으면 시간 아님
    return _parse(labels)
