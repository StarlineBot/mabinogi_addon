"""불러온 이미지를 256×96 4색 그림으로(그림대화 명세 4절).

자르기 → 밝기·대비 → 4색 정하기(흑백/자동/선명) → 점묘(선택) 순서다. 전부 numpy·OpenCV 벡터 연산.
점묘는 오차 확산을 벡터화하기 어려워 **격자(Bayer 4×4) 점묘**를 쓴다(명세 5절이 허용한 대체).
팔레트는 어두운 색부터 밝은 색 순서로 1~4번 칸에 놓는다(4번 칸 = 가장 밝은 색 = 지우개 색).
"""

from __future__ import annotations

import cv2
import numpy as np

from .canvas import GRAY_PALETTE
from .pngfile import HEIGHT, WIDTH

MODES = ("gray", "auto", "vivid")
_BAYER4 = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) + 0.5) / 16 - 0.5


def fit_box(img_w: int, img_h: int) -> tuple[int, int, int, int]:
    """이미지 안에 들어가는 가장 큰 256:96(8:3) 상자(가운데). (x, y, w, h)."""
    w = min(img_w, img_h * WIDTH / HEIGHT)
    h = w * HEIGHT / WIDTH
    return int(round((img_w - w) / 2)), int(round((img_h - h) / 2)), max(1, int(round(w))), max(1, int(round(h)))


def crop_resize(rgb: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """(H,W,3) RGB에서 상자를 잘라 256×96로 줄인다(float32 0~255)."""
    x, y, w, h = (int(v) for v in box)
    H, W = rgb.shape[:2]
    x, y = max(0, min(x, W - 1)), max(0, min(y, H - 1))
    w, h = max(1, min(w, W - x)), max(1, min(h, H - y))
    part = rgb[y:y + h, x:x + w]
    interp = cv2.INTER_AREA if w >= WIDTH else cv2.INTER_LINEAR
    return cv2.resize(part, (WIDTH, HEIGHT), interpolation=interp).astype(np.float32)


def adjust(img: np.ndarray, brightness: int = 0, contrast: int = 0) -> np.ndarray:
    """밝기 -100~100(더하기), 대비 -100~100(가운데 128 기준 배율 0~2)."""
    factor = 1.0 + max(-100, min(100, contrast)) / 100.0
    out = (img.astype(np.float32) - 128.0) * factor + 128.0 + max(-100, min(100, brightness)) * 1.28
    return np.clip(out, 0, 255)


def _luma(c) -> np.ndarray:
    c = np.asarray(c, np.float32)
    return c[..., 0] * 0.299 + c[..., 1] * 0.587 + c[..., 2] * 0.114


def _sorted(colors) -> list[tuple[int, int, int]]:
    cols = [tuple(int(round(v)) for v in np.clip(c, 0, 255)) for c in colors]
    return sorted(cols, key=lambda c: float(_luma(c)))


def _kmeans(img: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    data = img.reshape(-1, 3).astype(np.float32)
    cv2.setRNGSeed(7)  # 같은 그림은 늘 같은 결과
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5)
    _, labels, centers = cv2.kmeans(data, k, None, crit, 2, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.ravel(), minlength=k)
    return centers, counts


def palette_auto(img: np.ndarray) -> list[tuple[int, int, int]]:
    """많이 쓰인 색 4개(k-평균)."""
    centers, _ = _kmeans(img, 4)
    return _sorted(centers)


def palette_vivid(img: np.ndarray) -> list[tuple[int, int, int]]:
    """서로 다른 색 우선: 색 무리 12개 중 가장 많은 색에서 시작해 서로 먼 색을 고른다(아주 적은 색은 덜 친다)."""
    centers, counts = _kmeans(img, 12)
    share = counts / max(1, counts.sum())
    chosen = [int(np.argmax(counts))]
    for _ in range(3):
        d = np.linalg.norm(centers[:, None, :] - centers[chosen][None, :, :], axis=2).min(axis=1)
        score = d * np.power(share, 0.25)
        score[chosen] = -1
        chosen.append(int(np.argmax(score)))
    return _sorted(centers[chosen])


def palette_for(mode: str, img: np.ndarray) -> list[tuple[int, int, int]]:
    if mode == "auto":
        return palette_auto(img)
    if mode == "vivid":
        return palette_vivid(img)
    return list(GRAY_PALETTE)


def quantize(img: np.ndarray, palette: list[tuple[int, int, int]], dither: bool = False,
             gray: bool = False) -> np.ndarray:
    """가장 가까운 팔레트 칸 번호(96,256). gray=True면 밝기만 비교(흑백 칸에 맞춤)."""
    pal = np.asarray(palette, np.float32)
    src = img.astype(np.float32)
    if gray:
        src = np.repeat(_luma(src)[..., None], 3, axis=2)
    if dither:
        lum = np.sort(_luma(pal))
        spread = float(np.mean(np.diff(lum))) if lum.size > 1 else 64.0
        tile = np.tile(_BAYER4, (HEIGHT // 4 + 1, WIDTH // 4 + 1))[:src.shape[0], :src.shape[1]]
        src = src + tile[..., None] * max(16.0, spread)
    if gray:
        d = np.abs(_luma(src)[..., None] - _luma(pal)[None, None, :])
    else:
        d = ((src[:, :, None, :] - pal[None, None, :, :]) ** 2).sum(axis=3)
    return np.argmin(d, axis=2).astype(np.uint8)


def convert(img: np.ndarray, mode: str, dither: bool) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """256×96 float 이미지 → (칸 번호, 팔레트)."""
    palette = palette_for(mode, img)
    return quantize(img, palette, dither, gray=(mode == "gray")), palette
