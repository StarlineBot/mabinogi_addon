"""쿨타임 오버레이 판정(쿨타임 명세 10절) — 단축바 칸 하나가 '사용 중'인지, 페이지 번호가 같은지.

- 사용 중 = **회색(어두운) 바탕 + 가운데 숫자**(초·% 구분 없음, 몇 초인지 읽지 않음). 그 밖은 사용 가능.
  귀퉁이 수량(99)·단축키 글자(F1·1)는 가운데가 아니라 보지 않는다.
- 페이지 = 그 줄의 `◀N▶` 숫자 상자. 숫자 템플릿 대신 **등록 때 상자 안 흰 글자 모양**을 저장해 두고 같은지만 본다
  (1~8 숫자를 읽을 필요 없음 — 다르면 '가려짐'과 같이 줄에서 뺀다).
픽셀 반복문 없이 numpy·OpenCV만 쓴다(칸당 1ms 미만).
"""
from __future__ import annotations

import cv2
import numpy as np

COOLING, READY, UNKNOWN = "cooling", "ready", "unknown"
# tests/data 실측(1080·창 모드·4K): 사용 중 칸 밝기 59~108·채도 37~109, 가운데 흰 글자 22~88px.
# 어두운 아이콘(검은 날개 등)은 가운데 흰 글자가 0~8px라 사용 가능으로 남는다.
# 알려진 한계: 흑백 날개 아이콘 한 종류(나눔고딕 1080 화면)는 흰 곡선 조각이 숫자처럼 보여 사용 중으로 잡힌다 — 정지 화면 한 장으론
# 구별되지 않아 제작자 실게임 테스트에서 확인한다.
VAL_MAX = 112
SAT_MAX = 120
WHITE_MIN = 18


def classify(cell: np.ndarray | None) -> str:
    """단축바 칸(BGR, 정사각형 가까움) → cooling | ready | unknown(너무 작음·빈 값)."""
    if cell is None or cell.ndim != 3 or min(cell.shape[:2]) < 16:
        return UNKNOWN
    h, w = cell.shape[:2]
    hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
    inner = hsv[4:h - 4, 4:w - 4]
    sat = float(inner[:, :, 1].mean())
    val = float(inner[:, :, 2].mean())
    if val > VAL_MAX or sat > SAT_MAX:
        return READY
    # 흰 글자 = 밝고 무채색. 칸 전체에서 덩어리를 나눠, 아이콘의 큰 흰 곡선·띠(폭 40%·높이 60% 넘는 덩어리)는 뺀다.
    # 숫자 획은 작은 조각으로 끊겨 있어도 그대로 센다(실측 '56'·'6'은 높이 2~10px 조각들).
    white = ((hsv[:, :, 2] > 190) & (hsv[:, :, 1] < 50)).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(white, connectivity=8)
    big = [i for i in range(1, n) if stats[i][2] > 0.4 * w or stats[i][3] > 0.6 * h]
    if big:
        white[np.isin(labels, big)] = 0
    glyphs = int(white[int(h * 0.25):int(h * 0.75), int(w * 0.1):int(w * 0.9)].sum())
    scale = (w / 40.0) ** 2  # 40px 기준 → 큰 칸이면 비례
    return COOLING if glyphs >= WHITE_MIN * scale else READY


# ---- 페이지 번호 상자(◀N▶) ---------------------------------------------------------------------
PAGE_OFFSETS = (540, 1160)       # 단축바 소스(1168×89) 기준 선택기 왼쪽 x 후보 — 블록 사이 / 오른쪽 끝
PAGE_BOX = (34, 12, 15, 16)      # 선택기 기준 숫자 상자(x, y, w, h), 줄마다 y + ROW_Y
ROW_Y = (0, 49)


def page_rect(frame: np.ndarray, source_box, row: int) -> tuple[int, int, int, int] | None:
    """그 줄의 페이지 숫자 상자(프레임 좌표). 어두운 상자 + 흰 글자가 있는 후보 위치. 없으면 None."""
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
    return white


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
