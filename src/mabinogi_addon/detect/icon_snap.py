"""버프·디버프 아이콘 직접 지정 — 테두리 자동 맞춤과 '온전히 보일 때만 저장'(docs/icon-capture-spec.md 2.1·2.3).

내장 아이콘(assets/buff/icon·assets/debuff/icon)은 테두리(갈색 점선)까지 포함한 16×16이다. 그 테두리 2px 고리 평균을 틀로,
커서를 포함하는 16×16 후보를 마스크 비교(TM_SQDIFF)해 가장 잘 맞는 자리를 고른다. 거리(고리 픽셀당 RMS) 기준을 넘으면 '아이콘 아님'.
화면에 따라 아이콘이 더 크게 그려지면(배율 SIZES) 같은 틀을 최근접으로 키워 함께 본다. 저장은 화면에 보이는 원본 크기 그대로.
OS·Qt 없이 numpy 배열만 다룬다(맥 테스트 가능).
"""
from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np

ICON = 16
RING = 2
SIZES = (16,)             # 화면에 그려지는 아이콘 한 변 — 1080·1440·4K 모두 16(4K 010804 즐겨찾기 줄 실측)
DIM_GAIN = 0.5            # 꺼진(회색) 아이콘 고리 밝기(실측 0.46~0.54) — 이 밝기의 고리 틀도 함께 본다
DIM_SNAP_LIMIT = 12.0     # 꺼진 고리 틀 거리 — 꺼진 즐겨찾기 0.2~10.8(1440·2560·4K), 어두운 바탕 15.7 이상(실측)
SNAP_LIMIT = 30.0         # 켜진 고리 거리(픽셀당 RMS) — tests/data 실측: 켜진 아이콘 0~27.7(4K가 큼), 아이콘 아닌 곳 33.7 이상

# 2.3 온전함(tests/data 실측, 2026-10-30 창 모드 wireweb 1~3 즐겨찾기 줄)
# 꺼진(회색) 즐겨찾기는 채도가 아니라 밝기가 절반으로 고르게 어두워진다(쿨타임 '사용 불가'와 같은 현상):
# 테두리 고리 밝기 / 내장 테두리 밝기 = 꺼짐 0.46~0.51, 켜짐 0.92~1.17.
DIM_RATIO = 0.75          # 고리 밝기 비가 이보다 낮으면 꺼진(어두운) 아이콘
STABLE_DIFF = 12.0        # 연속 두 프레임 평균 절대차가 이보다 크면 깜빡이는 중


@lru_cache(maxsize=1)
def _ring_template() -> tuple[np.ndarray, np.ndarray] | None:
    """내장 16×16 아이콘들(BGR float32, 쌓은 배열)과 2px 고리 마스크. 아이콘마다 테두리 색이 조금씩 달라(평균 틀이면
    마법 공격력처럼 실제 아이콘도 거리 33까지 벌어짐) 각 아이콘의 고리 중 가장 가까운 것으로 본다."""
    from .. import image_io, paths
    icons = []
    for kind in ("buff", "debuff"):
        folder = paths.resource_dir() / kind / "icon"
        for p in sorted(folder.glob("*.png")):
            img = image_io.imread(p, cv2.IMREAD_COLOR)
            if img is not None and img.shape[:2] == (ICON, ICON):
                icons.append(img.astype(np.float32))
    if not icons:
        return None
    mask = np.zeros((ICON, ICON), np.float32)
    mask[:RING, :] = mask[-RING:, :] = mask[:, :RING] = mask[:, -RING:] = 1
    rings = np.stack(icons).astype(np.float32)
    keep = [0]  # 고리가 거의 같은 아이콘은 하나만(비교 횟수 줄이기)
    for i in range(1, len(rings)):
        if all(float(np.sqrt((((rings[i] - rings[j]) ** 2) * mask[:, :, None]).sum() / (mask.sum() * 3))) > 3 for j in keep):
            keep.append(i)
    return rings[keep], mask


@lru_cache(maxsize=4)
def _template(size: int, dim: bool = False):
    base = _ring_template()
    if base is None:
        return None
    rings, mask = base
    if dim:
        rings = rings * DIM_GAIN  # 꺼진(어두운) 아이콘 고리
    if size == ICON:
        return rings, mask
    return (np.stack([cv2.resize(r, (size, size), interpolation=cv2.INTER_NEAREST) for r in rings]),
            cv2.resize(mask, (size, size), interpolation=cv2.INTER_NEAREST))


def ring_distance(cell: np.ndarray, dim: bool = False) -> float | None:
    """칸(정사각형, 크기 SIZES 중 하나) 테두리 고리가 내장 틀과 얼마나 다른지(픽셀당 RMS). 크기가 안 맞으면 None."""
    if cell is None or cell.ndim != 3 or cell.shape[0] != cell.shape[1] or cell.shape[0] not in SIZES:
        return None
    tpl = _template(cell.shape[0], dim)
    if tpl is None:
        return None
    rings, mask = tpl
    diff = ((cell.astype(np.float32)[None] - rings) ** 2 * mask[None, :, :, None]).sum(axis=(1, 2, 3))
    return float(np.sqrt(diff.min() / (mask.sum() * 3)))


def _best(frame: np.ndarray, x: int, y: int, size: int, dim: bool):
    tpl = _template(size, dim)
    if tpl is None:
        return None
    rings, mask = tpl
    H, W = frame.shape[:2]
    x0, y0 = max(0, x - size + 1), max(0, y - size + 1)
    x1, y1 = min(W, x + size), min(H, y + size)
    if x1 - x0 < size or y1 - y0 < size:
        return None
    roi = np.ascontiguousarray(frame[y0:y1, x0:x1]).astype(np.float32)
    mask3 = cv2.merge([mask] * 3)
    res = np.min([cv2.matchTemplate(roi, ring, cv2.TM_SQDIFF, mask=mask3) for ring in rings], axis=0)
    res = np.where(np.isfinite(res), res, np.inf)
    iy, ix = np.unravel_index(int(np.argmin(res)), res.shape)
    dist = float(np.sqrt(max(0.0, float(res[iy, ix])) / (mask.sum() * 3)))
    return dist, (x0 + int(ix), y0 + int(iy), size, size)


def find_icon(frame: np.ndarray, x: int, y: int, limit: float = SNAP_LIMIT, dim_limit: float | None = None):
    """커서(프레임 좌표 x, y)를 포함하는 테두리 있는 아이콘 상자 (x, y, w, h). 없으면 None.
    켜진 고리 틀로 먼저 보고(거리 limit), 못 찾으면 꺼진(어두운) 고리 틀로(거리 dim_limit — 어두운 바탕이 맞지 않게 더 엄격)."""
    if frame is None or frame.ndim != 3:
        return None
    dim_limit = DIM_SNAP_LIMIT if dim_limit is None else dim_limit
    for size in SIZES:
        got = _best(frame, x, y, size, False)
        if got is not None and got[0] <= limit:
            return got[1]
        got = _best(frame, x, y, size, True)
        if got is not None and got[0] <= dim_limit:
            return got[1]
    return None


# ---- 2.3 온전히 보일 때만 저장 ----------------------------------------------------------------------
BLINK, GRAY, COVERED = "blink", "gray", "covered"
REASONS = {
    BLINK: "버프가 깜빡이는 중이에요 — 남은 시간이 넉넉할 때 다시 집어 주세요",
    GRAY: "꺼진(회색) 버프예요 — 켜진 상태에서 집어 주세요",
    COVERED: "아이콘이 가려졌어요",
}


def _inner(img: np.ndarray) -> np.ndarray:
    b = max(RING, img.shape[0] // 8)
    return img[b:-b, b:-b] if min(img.shape[:2]) > 2 * b + 2 else img


@lru_cache(maxsize=1)
def _ring_v() -> float | None:
    base = _ring_template()
    if base is None:
        return None
    rings, mask = base
    m = mask.astype(bool)  # 켜진 고리만(꺼진 틀 제외)
    return float(np.mean([cv2.cvtColor(np.clip(r, 0, 255).astype(np.uint8), cv2.COLOR_BGR2HSV)[:, :, 2][m].mean()
                          for r in rings]))


def ring_brightness(cell: np.ndarray) -> float | None:
    """16×16(또는 SIZES) 칸 테두리 고리 밝기 / 내장 테두리 밝기. 아이콘 칸을 못 정하면 None."""
    if cell is None or cell.ndim != 3 or cell.shape[0] != cell.shape[1] or cell.shape[0] not in SIZES:
        return None
    tv = _ring_v()
    if not tv:
        return None
    tpl = _template(cell.shape[0])
    m = tpl[1].astype(bool)
    return float(cv2.cvtColor(np.ascontiguousarray(cell), cv2.COLOR_BGR2HSV)[:, :, 2][m].mean()) / tv


def _icon_cell(frame: np.ndarray, aligned: bool):
    """판단할 아이콘 칸: 테두리 맞춤이면 프레임 그대로, 드래그면 가운데에서 찾은 칸(못 찾으면 None)."""
    if aligned:
        return frame
    h, w = frame.shape[:2]
    box = find_icon(frame, w // 2, h // 2)
    if box is None:
        return None
    x, y, bw, bh = box
    return frame[y:y + bh, x:x + bw]


def brightness(img: np.ndarray) -> float:
    return float(cv2.cvtColor(np.ascontiguousarray(_inner(img)), cv2.COLOR_BGR2HSV)[:, :, 2].mean())


def pick_whole(frames: list, *, check_ring: bool) -> tuple[np.ndarray | None, str | None]:
    """다시 찍은 프레임들(같은 자리) → (저장할 프레임, None) 또는 (None, 이유 키).
    온전함 = 어둡지 않음(테두리 고리 밝기) + 테두리 고리 맞음(check_ring일 때) + 바로 앞 프레임과 거의 같음. 그중 가장 밝은 것.
    못 고르면: 어두운 프레임과 밝은 프레임이 섞임 = 깜빡임, 모두 어두움 = 꺼짐(회색), 테두리가 안 맞음 = 가려짐."""
    frames = [f for f in frames if f is not None and f.ndim == 3 and f.size]
    if not frames:
        return None, COVERED
    cells = [_icon_cell(f, check_ring) for f in frames]
    ratio = [None if c is None else ring_brightness(c) for c in cells]
    dim = [r is not None and r < DIM_RATIO for r in ratio]
    ring_ok = [not check_ring or (ring_distance(f) is not None and ring_distance(f) <= SNAP_LIMIT) for f in frames]
    stable = [False] + [frames[i].shape == frames[i - 1].shape
                        and float(np.abs(frames[i].astype(np.int16) - frames[i - 1].astype(np.int16)).mean()) <= STABLE_DIFF
                        for i in range(1, len(frames))]
    whole = [i for i in range(len(frames)) if not dim[i] and ring_ok[i] and stable[i]]
    if whole:
        best = max(whole, key=lambda i: brightness(frames[i]))
        return frames[best], None
    if all(dim):
        return None, GRAY
    if any(dim):
        return None, BLINK  # 어두웠다 밝았다
    if not any(ring_ok):
        return None, COVERED
    return None, BLINK


SHOTS = 6
SHOT_INTERVAL = 0.1


def verify_pick(grab, rect, *, snapped: bool, shots: int = SHOTS, interval: float = SHOT_INTERVAL, sleep=None):
    """작업 스레드: 같은 자리(rect, 화면 물리 좌표)를 약 0.6초 동안 shots번 다시 찍어 온전한 프레임을 고른다(명세 2.3).
    grab(x, y, w, h) -> BGR 또는 None. 돌려줌: (저장할 프레임, None) 또는 (None, 이유 키)."""
    import time
    sleep = time.sleep if sleep is None else sleep
    frames = []
    for i in range(shots):
        if i:
            sleep(interval)
        try:
            frames.append(grab(*rect))
        except Exception:  # noqa: BLE001 — 한 장 실패는 그 장만 뺀다
            frames.append(None)
    return pick_whole(frames, check_ring=snapped)
