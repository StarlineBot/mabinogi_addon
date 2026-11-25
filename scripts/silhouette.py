"""실루엣 맞춤 배율(QA 11-25 '기본 동작 4종 크기 튐' — 머리 폭·얼굴 창은 머리카락·귀·뿔에 끌려 틀림).

같은 자세인 두 그림(예: 기지개 0번 ↔ 서 있기)을 발 밑 가운데 맞춰 겹쳤을 때 알파(>128) IoU가 가장 큰 배율 =
other를 ref와 같은 크기로 보이게 하는 배율. 빌드(시트 배율 보정)와 테스트(회귀 방지)가 같이 쓴다.
"""
from __future__ import annotations

import cv2
import numpy as np


def _place(mask: np.ndarray, h: int, w: int) -> np.ndarray:
    out = np.zeros((h, w), bool)
    mh, mw = mask.shape
    x = (w - mw) // 2
    out[h - mh:, x:x + mw] = mask
    return out


def iou_at(ref: np.ndarray, other: np.ndarray, scale: float) -> float:
    a = ref[..., 3] > 128
    o = cv2.resize(other[..., 3], None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) > 128
    h, w = max(a.shape[0], o.shape[0]), max(a.shape[1], o.shape[1]) + 2
    pa, po = _place(a, h, w), _place(o, h, w)
    return float((pa & po).sum() / max(1, (pa | po).sum()))


def best_scale(ref: np.ndarray, other: np.ndarray, lo: float = 0.8, hi: float = 1.25, steps: int = 91) -> float:
    """other에 곱하면 ref와 실루엣이 가장 잘 겹치는 배율."""
    scales = np.linspace(lo, hi, steps)
    return float(scales[int(np.argmax([iou_at(ref, other, s) for s in scales]))])
