"""시간 판독 (기획서 4.3).

시간 글자 영역을 이진화한 뒤, 숫자(0~9)·단위(일/시간/분/초) 템플릿을 matchTemplate으로
찾아 x 순서로 정렬 → 토큰 파싱 → 총 초로 환산한다. 한글 음절 자모 간격 때문에 열 분할
대신 글자별 템플릿 매칭을 쓴다(간격 무관).
"""

from __future__ import annotations

import itertools

import cv2
import numpy as np

from .. import paths
from ..image_io import imread
from .binarize import binarize

_TEMPLATE_DIR = paths.detect_templates_dir() / "time"

# 단위 라벨 → 초. 숫자 라벨은 "0".."9".
_UNIT_SECONDS = {"day": 86400, "hour": 3600, "bun": 60, "cho": 1}

# 글자 매칭 임계. 이진 템플릿이라 정답은 ~1.0, 오답은 낮다.
GLYPH_THRESHOLD = 0.7


def _load_templates() -> dict[str, np.ndarray]:
    return {
        path.stem: imread(path, cv2.IMREAD_GRAYSCALE)
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


# 이 이상 x가 벌어지면 '다른 덩어리'로 본다(버프 이름과 시간 사이의 공백).
_CLUSTER_GAP = 14


def _time_labels(kept: list) -> list[str]:
    """글자들을 x간격으로 덩어리로 묶고, '단위(분/초/시간/일)를 포함한 덩어리'만 남긴다.

    시간은 오른쪽 정렬이라 숫자+단위가 한 덩어리로 뭉쳐 있다. 반면 버프 이름이 길어
    시간 영역(time_x0 오른쪽)까지 넘어오면, 이름 끝 획이 '1' 등으로 오인돼 실제 분
    앞에 붙는다(예: 2분 → 12분, +10분). 단위가 없는 고립 덩어리(=이름 획)를 버려
    이를 막는다. kept는 (x, score, label, w)의 x오름차순 리스트.
    """
    if not kept:
        return []
    clusters: list[list] = [[kept[0]]]
    for prev, cur in itertools.pairwise(kept):
        if cur[0] - (prev[0] + prev[3]) > _CLUSTER_GAP:
            clusters.append([cur])
        else:
            clusters[-1].append(cur)
    labels: list[str] = []
    for c in clusters:
        if any(lab in _UNIT_SECONDS for _x, _s, lab, _w in c):
            labels.extend(lab for _x, _s, lab, _w in c)
    return labels


def read_time(time_bgr: np.ndarray, threshold: float = GLYPH_THRESHOLD) -> int | None:
    """시간 영역(BGR)에서 남은 시간을 초로. 글자를 못 찾으면 None."""
    strip = binarize(time_bgr)
    hits: list = []
    for label, template in _TEMPLATES.items():
        hits.extend(_occurrences(strip, label, template, threshold))
    if not hits:
        return None
    labels = _time_labels(_nms(hits))
    if not labels:
        return None  # 단위가 하나도 없으면 시간 아님
    return _parse(labels)
