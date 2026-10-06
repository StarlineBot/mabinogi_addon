"""시간 글자 이진화 (기획서 4.3).

흰색 글자와 빨간색(임박) 글자를 모두 흰색으로 통일해야 한다. 그런데 빨강은
그레이스케일 밝기가 낮아(0.299R) 일반 밝기 임계로는 사라진다. 그래서 채널 최댓값
V=max(B,G,R)에 임계를 적용한다 → 흰색(모든 채널 높음)·빨강(R 높음) 모두 살아남고,
반투명 배경은 제거된다.
"""

from __future__ import annotations

import cv2
import numpy as np

DEFAULT_THRESHOLD = 170


def binarize(bgr: np.ndarray, threshold: int = DEFAULT_THRESHOLD) -> np.ndarray:
    """BGR → 0/255 이진 이미지. 글자=255, 배경=0."""
    value = bgr.max(axis=2)
    _, binary = cv2.threshold(value, threshold, 255, cv2.THRESH_BINARY)
    return binary
