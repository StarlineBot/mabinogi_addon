"""쿨타임 오버레이 판정(쿨타임 명세 10절) — 단축바 칸 하나가 '사용 중'인지, 페이지 번호가 같은지.

- 사용 중 = **가운데 숫자(흰 글자 + 검은 테두리)**가 있는 칸(초·% 구분 없음, 몇 초인지 읽지 않음). 그 밖은 사용 가능.
  게임 쿨타임은 '아래부터 차오르는 밝은 게이지 + 가운데 숫자'라 칸 평균 밝기로 먼저 거르면 쿨이 진행될수록 오판했다
  (제작자 실게임 11-05: 31·17·2·6·4·5초 칸이 사용 가능으로). 그래서 밝기 게이트를 없애고 숫자를 주 신호로 본다.
  귀퉁이 수량(99)·단축키 글자(F1·1)는 가운데 줄(높이 30~75%)이 아니라 보지 않는다.
- 페이지 = 그 줄의 `◀N▶` 숫자 상자. 숫자 템플릿 대신 **등록 때 상자 안 흰 글자 모양**을 저장해 두고 같은지만 본다
  (1~8 숫자를 읽을 필요 없음 — 다르면 '가려짐'과 같이 줄에서 뺀다).
픽셀 반복문 없이 numpy·OpenCV만 쓴다(칸당 1ms 미만).
"""
from __future__ import annotations

import cv2
import numpy as np

COOLING, READY, UNKNOWN = "cooling", "ready", "unknown"
# 흰 글자 조각(밝고 무채색, 8방향 연결). 칸 40px 기준 크기 — 큰 칸이면 비례.
WHITE_V, WHITE_S = 180, 80
GLYPH_H = (0.20, 0.60)      # 조각 높이(칸 높이 비율)
GLYPH_CY = (0.30, 0.75)     # 조각 세로 중심(칸 높이 비율) — 가운데 줄만
GLYPH_W_MAX = 0.45
# 강한 신호: 조각을 1px 둘러싼 띠가 거의 검은색(중앙값 ≤ 50, 글자와 차이 ≥ 150) = 게임 숫자의 검은 테두리.
#           밝은 게이지·0.x초 하얀 번쩍임 위에서도 테두리는 남아 숫자가 보이는 동안 사용 중이다.
STRONG_RING, STRONG_GAP = 50, 150
# 가는 '1': 2px 획이라 1px 띠에 경계 흐림이 섞인다 → 획 좌우 2px 안이 어두운(< 60) 줄이 90% 이상이면 강한 신호.
THIN_DARK, THIN_ROWS = 60, 0.9
# 약한 신호: 테두리가 어두운 회색(중앙값 ≤ 85, 차이 ≥ 120 — 예전 화면·4K) — 이때는 보조로 위쪽 띠(아직 안 찬 쪽)가 어두울 때만(≤ 100).
WEAK_RING, WEAK_GAP, TOP_DARK = 85, 120, 100
GLYPH_MIN = 10              # 신호 조각 넓이 합(px, 40px 칸 기준)
# tests/data 실측(칸 5136개): 라벨 화면 6장 오판 0, 예전 판정(평균 밝기)의 오탐(흑백 날개 아이콘·칸 위 브라우저 글자)은 사라지고
# 게이지가 찬 칸 124개를 새로 잡음. 남은 놓침: 회색 원 안 '90' 한 칸, 흐린 금색 '1' 한 칸.
_RING = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))


def _glyph_area(cell: np.ndarray) -> tuple[float, float]:
    """(강한 신호 넓이, 약한 신호 넓이) — 40px 칸 기준으로 맞춘 값."""
    h, w = cell.shape[:2]
    hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
    v = hsv[:, :, 2]
    white = ((v > WHITE_V) & (hsv[:, :, 1] < WHITE_S)).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(white, connectivity=8)
    scale = (w / 40.0) ** 2
    strong = weak = 0
    for i in range(1, n):
        x, y, cw, ch, area = (int(t) for t in stats[i])
        if area < 4 * scale or not GLYPH_H[0] * h <= ch <= GLYPH_H[1] * h or cw > GLYPH_W_MAX * w:
            continue
        if not GLYPH_CY[0] * h <= y + ch / 2 <= GLYPH_CY[1] * h:
            continue
        y0, x0 = max(0, y - 1), max(0, x - 1)
        comp = (labels[y0:y + ch + 1, x0:x + cw + 1] == i).astype(np.uint8)
        patch = v[y0:y + ch + 1, x0:x + cw + 1]
        ring = (cv2.dilate(comp, _RING) > 0) & (comp == 0)
        if not ring.any():
            continue
        ring_v = float(np.median(patch[ring]))
        core_v = float(patch[comp > 0].mean())
        if ring_v <= STRONG_RING and core_v - ring_v >= STRONG_GAP:
            strong += area
            continue
        if cw <= 0.15 * w and ch >= 0.25 * h and x >= 2 and x + cw + 2 <= w and core_v >= 240:
            rows = (labels[y:y + ch, x:x + cw] == i).any(axis=1)
            left = v[y:y + ch, x - 2:x].min(axis=1)
            right = v[y:y + ch, x + cw:x + cw + 2].min(axis=1)
            both = ((left < THIN_DARK) & (right < THIN_DARK))[rows]
            if both.size and float(both.mean()) >= THIN_ROWS:
                strong += area
                continue
        if ring_v <= WEAK_RING and core_v - ring_v >= WEAK_GAP:
            weak += area
    return strong / scale, weak / scale


def classify(cell: np.ndarray | None) -> str:
    """단축바 칸(BGR, 정사각형 가까움) → cooling | ready | unknown(너무 작음·빈 값)."""
    if cell is None or cell.ndim != 3 or min(cell.shape[:2]) < 16:
        return UNKNOWN
    strong, weak = _glyph_area(cell)
    if strong >= GLYPH_MIN:
        return COOLING
    if strong + weak >= GLYPH_MIN:
        h, w = cell.shape[:2]
        v = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)[: int(h * 0.3), int(w * 0.35):, 2]  # 왼쪽 위 단축키 글자 칸 제외
        if float(v.mean()) <= TOP_DARK:  # 보조: 위쪽(아직 안 찬 쪽)이 어둡다
            return COOLING
    return READY


# ---- 페이지 번호 상자(◀N▶) ---------------------------------------------------------------------
PAGE_OFFSETS = (540, 1160)       # 단축바 소스(1168×89) 기준 선택기 왼쪽 x 후보 — 블록 사이 / 오른쪽 끝
PAGE_BOX = (34, 12, 15, 16)      # 선택기 기준 숫자 상자(x, y, w, h), 줄마다 y + ROW_Y
ROW_Y = (0, 49)


def page_rect(frame: np.ndarray, source_box, row: int) -> tuple[int, int, int, int] | None:
    """그 줄의 페이지 숫자 상자(프레임 좌표). 어두운 상자 + 흰 글자가 있는 후보 위치. 없으면 None.
    한 줄에 선택기는 하나(그 줄 전체 페이지) — 배치에 따라 블록 사이(540) 또는 오른쪽 끝(1160)에 있다(tests/data 실측: 둘이 함께 보이는 화면 없음)."""
    x, y, w, _h = source_box
    s = w / 1168.0
    bx, by, bw, bh = PAGE_BOX
    for offset in PAGE_OFFSETS:
        rect = (round(x + (offset + bx) * s), round(y + (ROW_Y[row] + by) * s), max(1, round(bw * s)), max(1, round(bh * s)))
        mask = _box_mask(frame, rect)
        if mask is not None:
            return rect
    return None


def _box_mask(frame, rect):
    x, y, w, h = rect
    if x < 0 or y < 0 or y + h > frame.shape[0] or x + w > frame.shape[1]:
        return None
    gray = cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)
    dark = float((gray < 45).mean())
    white = gray > 150
    if dark < 0.35 or white.sum() < 6:  # 숫자 상자가 아님(바탕·아이콘)
        return None
    return _drop_corners(white)


def _drop_corners(mask: np.ndarray) -> np.ndarray:
    """상자 네 모서리 픽셀은 뒤 배경 밝기에 따라 흰색이 되었다 안 되었다 한다 — '1'(글자 9px)은 모서리 4개 차이로
    겹침 9/13 = 0.69 < 0.7이 돼 '페이지 다름'으로 숨겨졌다(던전 등, 758a01e). 비교에서 늘 뺀다."""
    mask = mask.copy()
    mask[0, 0] = mask[0, -1] = mask[-1, 0] = mask[-1, -1] = False
    return mask


def page_signature(frame: np.ndarray, rect) -> str | None:
    """숫자 상자 흰 글자 모양을 문자열로(등록 때 저장). 상자가 아니면 None."""
    mask = _box_mask(frame, rect)
    if mask is None:
        return None
    h, w = mask.shape
    bits = np.packbits(mask.astype(np.uint8).ravel())
    return f"{w}x{h}:{bits.tobytes().hex()}"


def _decode(signature: str) -> np.ndarray | None:
    try:
        size, data = signature.split(":")
        w, h = (int(v) for v in size.split("x"))
        bits = np.unpackbits(np.frombuffer(bytes.fromhex(data), np.uint8))[: w * h]
        return bits.reshape(h, w).astype(bool)
    except (ValueError, TypeError):
        return None


def same_page(frame: np.ndarray, rect, signature: str | None) -> bool | None:
    """지금 상자가 저장한 모양과 같은 숫자면 True, 다르면 False, 상자를 못 읽으면(가려짐) None.
    1px 밀림은 허용(겹침 비율 0.7 이상)."""
    if not signature:
        return True  # 페이지를 저장하지 못한 칸은 확인하지 않는다
    want = _decode(signature)
    mask = _box_mask(frame, rect)
    if want is None or mask is None:
        return None
    want = _drop_corners(want)  # 예전에 저장한 서명(모서리 포함)도 다시 등록 없이 맞게
    if mask.shape != want.shape:
        mask = cv2.resize(mask.astype(np.uint8), (want.shape[1], want.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)
    best = 0.0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            shifted = np.roll(np.roll(mask, dy, axis=0), dx, axis=1)
            union = int((shifted | want).sum())
            if union:
                best = max(best, int((shifted & want).sum()) / union)
    return best >= 0.7
