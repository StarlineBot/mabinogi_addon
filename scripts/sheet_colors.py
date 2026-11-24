"""시트 색 맞추기(사용자 11-24 Windows '동작마다 머리색·피부 톤이 다름' — docs/character-pet-spec.md '시트 색 맞추기').

그림 생성 도구가 시트마다 색을 조금씩 다르게 그려, 빌드 때 프레임마다 머리·피부를 서 있기 색에 따로 맞춘다.
- 부위(Part): 캐릭터별 HSV 범위(잴 픽셀 고르기) + 잴 곳(프레임 키 비율 구간) → 그 프레임의 부위 색(Lab 중앙값).
- 바꿀 픽셀(마스크): 그 프레임 부위 색과 Lab 거리 tol 안 + 다른 부위 색보다 이 부위 색에 더 가까움 + 허용 구간(band) 안
  (아리아 피부와 크림 드레스는 색이 같아 피부는 얼굴 높이 구간만). 서 있기 부위 색과의 차이를 마스크(1.2px 흐림)만큼
  Lab에 더하고 마스크가 닿은 픽셀만 덮어씀(옷·눈은 그대로).
- 부분 합성(입만·얼굴만·바뀐 부분만) 그림은 같은 무리의 기준 그림 차이를 그대로 씀 → 합성 밖 픽셀이 기준과 같게 남음.
- 차이가 ΔE 1 미만이면 손대지 않음(같은 색을 Lab 왕복 반올림으로 흔들지 않게).
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Part:
    name: str
    h: tuple[int, int]            # 잴 픽셀 OpenCV H(0~179) 범위 — lo > hi면 0을 넘어 감는 범위(빨강)
    s: tuple[int, int]
    v: tuple[int, int]
    region: tuple[float, float]   # 잴 곳: 프레임 키 비율(위, 아래)
    tol: float = 30.0             # 바꿀 픽셀: 그 프레임 부위 색과의 Lab 거리(8비트) 한도
    band: tuple[float, float] = (0.0, 1.0)   # 바꿀 수 있는 키 비율 구간
    min_pixels: int = 40          # 잴 픽셀이 이보다 적으면 그 프레임은 건너뜀(안 보이는 부위)
    max_delta: float = 10.0       # 서 있기와 이보다 다르면 다른 것을 잰 것(엎드린 자세의 손 등) — 건너뜀
    avoid: tuple = ()             # 이 색(Lab 8비트)들보다 부위 색에 더 가까운 픽셀만(아리아 치마 단 무늬 등 비슷한 옷 색 빼기)
    big: float = 0.0              # 잴 픽셀과 안 이어져도 이만큼(그림 픽셀 비율) 큰 덩어리는 같은 부위(리본에 끊긴 아래 머리)


def _hsv(frame: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(np.ascontiguousarray(frame[..., :3]), cv2.COLOR_BGR2HSV)


def _lab(frame: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(np.ascontiguousarray(frame[..., :3]), cv2.COLOR_BGR2LAB).astype(np.float32)


def seed(frame: np.ndarray, part: Part) -> np.ndarray:
    """잴 픽셀: HSV 범위 ∧ 잴 곳 ∧ 알파>220."""
    hsv = _hsv(frame)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    lo, hi = part.h
    in_h = (h >= lo) & (h <= hi) if lo <= hi else (h >= lo) | (h <= hi)
    out = in_h & (s >= part.s[0]) & (s <= part.s[1]) & (v >= part.v[0]) & (v <= part.v[1]) & (frame[..., 3] > 220)
    rows = np.zeros(frame.shape[0], bool)
    rows[int(frame.shape[0] * part.region[0]):max(int(frame.shape[0] * part.region[0]) + 1,
                                                  int(frame.shape[0] * part.region[1]))] = True
    return out & rows[:, None]


def colors(frame: np.ndarray, parts) -> list[np.ndarray | None]:
    """부위별 그 프레임 색(잴 픽셀 Lab 중앙값, 8비트). 잴 픽셀이 적으면 None."""
    lab = _lab(frame)
    out = []
    for part in parts:
        sel = seed(frame, part)
        out.append(np.median(lab[sel], axis=0) if sel.sum() >= part.min_pixels else None)
    return out


def masks(frame: np.ndarray, parts, cols=None) -> list[np.ndarray]:
    """부위별 바꿀 픽셀 — 부위 색 거리 tol 안 ∧ 가장 가까운 부위 ∧ 허용 구간."""
    cols = colors(frame, parts) if cols is None else cols
    lab = _lab(frame)
    dist = [np.linalg.norm(lab - c, axis=-1) if c is not None else np.full(frame.shape[:2], np.inf) for c in cols]
    h = frame.shape[0]
    out = []
    for i, part in enumerate(parts):
        m = (dist[i] < part.tol) & (frame[..., 3] > 0)
        for j in range(len(parts)):
            if j != i:
                m &= dist[i] <= dist[j]
        for color in part.avoid:
            m &= dist[i] < np.linalg.norm(lab - np.float32(color), axis=-1)
        rows = np.zeros(h, bool)
        rows[int(h * part.band[0]):int(h * part.band[1])] = True
        m &= rows[:, None]
        # 잴 픽셀과 이어진 덩어리만(머리는 위에서 옆으로 내려옴 — 옷 무늬·손·볼 터치 같은 떨어진 점은 뺌)
        count, labels = cv2.connectedComponents(m.astype(np.uint8), connectivity=8)
        if count > 1:
            keep = set(np.unique(labels[seed(frame, part) & m]).tolist()) - {0}
            if part.big > 0:
                sizes = np.bincount(labels.ravel())
                limit = part.big * (frame[..., 3] > 0).sum()
                keep |= {i for i in range(1, count) if sizes[i] >= limit}
            m = np.isin(labels, list(keep))
        out.append(m)
    return out


def measure(frame: np.ndarray, part_mask, part: Part) -> np.ndarray | None:
    sel = seed(frame, part)
    return np.median(_lab(frame)[sel], axis=0) if sel.sum() >= part.min_pixels else None


def delta_e(a: np.ndarray, b: np.ndarray) -> float:
    """OpenCV 8비트 Lab 차이 → ΔE(L을 0~100으로 환산, a·b는 그대로)."""
    return float(np.linalg.norm((np.asarray(a) - np.asarray(b)) * np.array([100 / 255, 1, 1])))


def diffs(frame: np.ndarray, parts, targets) -> list[np.ndarray | None]:
    out = []
    for part, got, target in zip(parts, colors(frame, parts), targets):
        far = got is None or target is None or not 1 <= delta_e(got, target) <= part.max_delta
        out.append(None if far else target - got)
    return out


def apply(frame: np.ndarray, parts, shifts, base: np.ndarray | None = None) -> np.ndarray:
    """부위 마스크(1.2px 흐림)만큼 Lab에 차이를 더함 — 마스크가 닿은 픽셀만 덮어씀.
    base(부분 합성의 기준 그림)를 주면 부위 색도 base에서 잼(합성 밖 픽셀이 기준과 똑같이 바뀌게)."""
    if all(d is None for d in shifts):
        return frame
    lab = _lab(frame)
    add = np.zeros_like(lab)
    touched = np.zeros(frame.shape[:2], bool)
    cols = colors(base if base is not None else frame, parts)
    for part, c, m, d in zip(parts, cols, masks(frame, parts, cols), shifts):
        if d is None:
            continue
        w = cv2.GaussianBlur(m.astype(np.float32), (0, 0), 1.2)
        # 흐림은 경계를 부드럽게만 — 부위 색과 먼 픽셀(외곽선·옷·눈)엔 번지지 않게
        w[(frame[..., 3] == 0) | (np.linalg.norm(lab - c, axis=-1) >= part.tol * 1.5)] = 0
        add += w[..., None] * d
        touched |= w >= 1 / 255
    fixed = cv2.cvtColor(np.clip(lab + add, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)
    out = frame.copy()
    out[touched, :3] = fixed[touched]
    return out


def harmonize(frames: dict, stand: np.ndarray, parts, groups: dict | None = None, skip=()) -> dict:
    """frames(키 → 프레임 목록)를 서 있기(stand) 머리·피부 색에 맞춤. groups: 합성 그림 키 → (기준 키, 번호)."""
    groups = groups or {}
    targets = colors(stand, parts)
    out = {}
    for key, items in frames.items():
        if key in skip:
            out[key] = items
            continue
        fixed = []
        for i, frame in enumerate(items):
            base = groups.get((key, i))
            source = frames[base[0]][base[1]] if base else frame
            fixed.append(apply(frame, parts, diffs(source, parts, targets), source))
        out[key] = fixed
    return out


def report(frames: dict, stand: np.ndarray, parts) -> dict[str, list[float | None]]:
    """프레임별 부위 ΔE(서 있기 대비) — 결과 표·테스트용."""
    targets = colors(stand, parts)
    out = {}
    for name, frame in frames.items():
        row = []
        for part, got, target in zip(parts, colors(frame, parts), targets):
            d = None if got is None or target is None else round(delta_e(got, target), 1)
            row.append(None if d is not None and d > part.max_delta else d)
        out[name] = row
    return out
