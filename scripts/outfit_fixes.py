"""착장 그림 후처리(QA 11-26, 사용자 '간단하면 Claude 안에서') — 이안 길드 정복 금줄, 이안 조끼 배지.
(맨팔 옷 손목·팔 선 옅게는 시도했지만 머리카락·얼굴 경계에 점선 자국이 남아 기획 다시 그리기로 넘김.)"""
from __future__ import annotations

import cv2
import numpy as np

# ---- 이안 길드 고위 정복: 코트 앞자락 세로 금줄은 한 줄(원본 전신) — 두 줄로 그려진 칸은 오른쪽 줄을 지움 ---------------------
COAT_BAND = (0.58, 0.86)     # 벨트 아래 ~ 밑단 위(키 비율)


def _gold(frame: np.ndarray, v_min: int = 90) -> np.ndarray:
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[..., :3]), cv2.COLOR_BGR2HSV)
    return ((hsv[..., 0] >= 10) & (hsv[..., 0] <= 35) & (hsv[..., 1] > 45) & (hsv[..., 2] > v_min)
            & (frame[..., 3] > 128))


def coat_lines(frame: np.ndarray, min_len: int = 22) -> list[tuple[int, np.ndarray]]:
    """코트 띠 안 세로 금줄(가는 세로 덩어리) — (가운데 x, 그 줄 마스크) 왼쪽부터."""
    h, w = frame.shape[:2]
    y0, y1 = round(h * COAT_BAND[0]), round(h * COAT_BAND[1])
    band = np.zeros((h, w), np.uint8)
    band[y0:y1] = _gold(frame)[y0:y1]
    vertical = cv2.morphologyEx(band, cv2.MORPH_OPEN, np.ones((7, 1), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(vertical)
    # 손목시계(손 옆 금색)는 줄이 아님 — 피부에서 6px 안에 닿는 금색 덩어리는 뺌
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[..., :3]), cv2.COLOR_BGR2HSV)
    skin = ((frame[..., 3] > 200) & ((hsv[..., 0] <= 22) | (hsv[..., 0] >= 172)) & (hsv[..., 1] >= 18)
            & (hsv[..., 1] <= 140) & (hsv[..., 2] >= 150)).astype(np.uint8)
    near_skin = cv2.dilate(skin, np.ones((13, 13), np.uint8)) > 0
    out = []
    for i in range(1, n):
        x, y, cw, ch, _area = stats[i]
        cx = x + cw / 2
        if ch >= min_len and cw <= 7 and w * 0.25 <= cx <= w * 0.8:
            piece = labels == i
            if ch < 30 and (piece & near_skin).any():
                continue   # 손목시계·소매 장식(손 바로 옆 짧은 금색)
            out.append((int(cx), piece))
    return sorted(out, key=lambda t: t[0])


def one_coat_line(frame: np.ndarray, min_len: int = 15) -> np.ndarray:
    """세로 금줄이 둘 이상이면 가장 왼쪽만 남기고 나머지를 코트 천 색으로 메움(inpaint TELEA, 반경 4). 끊긴 조각이 남으면 한 번 더."""
    for _ in range(3):
        fixed = _one_pass(frame, min_len)
        if fixed is frame:
            break
        frame = fixed
    return frame


def _one_pass(frame: np.ndarray, min_len: int) -> np.ndarray:
    lines = coat_lines(frame, min_len)
    if len(lines) < 2:
        return frame
    mask = np.zeros(frame.shape[:2], np.uint8)
    for _x, m in lines[1:]:
        mask |= m.astype(np.uint8)
    # 줄과 이어진 금색(위아래로 끊긴 조각 포함)까지 — 같은 열 근처 금색만
    gold = _gold(frame, 70).astype(np.uint8)
    grown = cv2.dilate(mask, np.ones((25, 3), np.uint8)) & gold
    mask = cv2.dilate(mask | grown, np.ones((3, 3), np.uint8))
    h = frame.shape[0]
    mask[: round(h * COAT_BAND[0])] = 0          # 벨트·단추 위는 안 건드림
    mask[round(h * 0.88):] = 0                   # 밑단 가로 금줄은 그대로
    out = frame.copy()
    out[..., :3] = cv2.inpaint(np.ascontiguousarray(frame[..., :3]), mask, 4, cv2.INPAINT_TELEA)
    return out


def apply_one_coat_line(frames: dict, _folder: str, _key: str) -> dict:
    """모든 칸(모션 포함) — 세로 금줄 한 줄로."""
    return {name: one_coat_line(image) for name, image in frames.items()}


# ---- 이안 넥타이 조끼: 가슴 금 방패 배지(원본 전신에 있음)가 서 있기·시계·끌기에만 있고 나머지 앞모습엔 빠짐 → stand_1 배지를 붙임 ---
TIE_BOX = (70, 134, 24, 30)      # stand_1 깃·넥타이 매듭(x, y, w, h) — 붙일 자리 정렬 기준
BADGE_BOX = (91, 152, 17, 18)    # stand_1 배지(테두리 포함)


def _navy(frame: np.ndarray) -> np.ndarray:
    """조끼 천(어두운 남색)·외곽선 — 배지를 얹어도 되는 곳."""
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[..., :3]), cv2.COLOR_BGR2HSV)
    return (frame[..., 3] > 200) & (hsv[..., 2] < 110) & ((hsv[..., 1] < 90) | ((hsv[..., 0] >= 95) & (hsv[..., 0] <= 145)))


def badge_parts(stand: np.ndarray):
    x, y, w, h = BADGE_BOX
    sprite = stand[y:y + h, x:x + w].copy()
    gold = _gold(sprite, 80).astype(np.uint8)
    mask = cv2.dilate(gold, np.ones((3, 3), np.uint8)) > 0       # 금 + 1px 테두리
    tx, ty, tw, th = TIE_BOX
    tie = cv2.cvtColor(np.ascontiguousarray(stand[ty:ty + th, tx:tx + tw, :3]), cv2.COLOR_BGR2GRAY)
    return sprite, mask, tie, (x - tx, y - ty)


def badge_present(frame: np.ndarray, at: tuple[int, int], size: tuple[int, int], ref_gold: int) -> bool:
    x, y = at
    w, h = size
    return int(_gold(frame[max(0, y):y + h, max(0, x):x + w], 80).sum()) >= ref_gold * 0.5


def add_badge(frame: np.ndarray, stand: np.ndarray, min_score: float = 0.68):
    """넥타이 매듭을 stand_1과 맞춰(배율 ±5%) 배지 자리를 정하고, 그 자리 조끼 천 위에만 배지를 얹음.
    → (그림, 상태) 상태 = 'added' / 'present' / 'no_tie' / 'covered'."""
    sprite, mask, tie, (ox, oy) = badge_parts(stand)
    ref_gold = int(_gold(sprite, 80).sum())
    gray = cv2.cvtColor(np.ascontiguousarray(frame[..., :3]), cv2.COLOR_BGR2GRAY)
    h = frame.shape[0]
    top, bottom = round(h * 0.3), round(h * 0.75)
    best = (-1.0, None)
    for s in (0.95, 0.975, 1.0, 1.025, 1.05):
        t = cv2.resize(tie, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        area = gray[top:bottom]
        if area.shape[0] < t.shape[0] or area.shape[1] < t.shape[1]:
            continue
        r = cv2.matchTemplate(area, t, cv2.TM_CCOEFF_NORMED)
        _, score, _, (x, y) = cv2.minMaxLoc(r)
        if score > best[0]:
            best = (score, (s, x, y + top))
    if best[1] is None or best[0] < min_score:
        return frame, "no_tie"
    s, tx, ty = best[1]
    sp = cv2.resize(sprite, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    mk = cv2.resize(mask.astype(np.uint8), (sp.shape[1], sp.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    bx, by = tx + round(ox * s), ty + round(oy * s)
    if badge_present(frame, (bx, by), (sp.shape[1], sp.shape[0]), ref_gold):
        return frame, "present"
    H, W = frame.shape[:2]
    if bx < 0 or by < 0 or bx + sp.shape[1] > W or by + sp.shape[0] > H:
        return frame, "covered"
    region = frame[by:by + sp.shape[0], bx:bx + sp.shape[1]]
    ok = mk & _navy(region)
    if ok.sum() < mk.sum() * 0.5:          # 팔·손·시계가 앞을 가림
        return frame, "covered"
    out = frame.copy()
    out[by:by + sp.shape[0], bx:bx + sp.shape[1]][ok] = sp[ok]
    return out, "added"


def apply_vest_badge(frames: dict, _folder: str, _key: str) -> dict:
    """앞모습 칸(걷기 빼고)에 배지 — 기준은 이 옷 stand_1."""
    stand = frames["stand_1"]
    out = dict(frames)
    for name, image in frames.items():
        if name.startswith("walk_") or name == "stand_1":
            continue
        out[name], _state = add_badge(image, stand)
    return out
