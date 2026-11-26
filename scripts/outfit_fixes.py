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


# 아리아 여름 드레스 말하기 리본(사용자 11-26, QA 전달): 몇 장은 가슴 아래 주황 리본이 빠져 그려짐 → 같은 자세의 리본 있는 장에서
# 리본(매듭·꼬리 + 외곽선)을 잘라 얼굴로 맞춘 자리에, 드레스 천 위에만 얹음. 팔·손이 앞을 가린 곳(피부·외곽선)은 그대로 둠.
# 팔짱 장(talk_a_base·blink·m1·m2)은 매듭이 팔 뒤에 있고 꼬리는 팔 아래로 이미 그려져 있어(주황 ≈ 기준의 37%) 덧붙이면
# 꼬리가 두 겹이 됨(렌더 확인 11-26) → 그대로 둠. talk_happy_0도 손 사이·아래로 매듭이 이미 보여(주황 ≈ happy_1의 72%) 덧붙이면
# 손 사이가 얼룩짐 → 그대로. 리본 자리(팔 위 가슴 아래)가 보이는데 비어 있는 talk_a_mid만 붙임.
RIBBON_FROM = {"talk_a_mid_0": "talk_a_emph_0"}
RIBBON_BAND = (0.55, 0.75)       # 리본 높이(키 비율)
RIBBON_X = (0.48, 0.72)          # 리본 가운데 가로 범위(폭 비율) — 왼쪽 머리 리본은 빠짐
FIT_BAND = (0.62, 0.92)          # 자리 맞춤 기준(리본 꼬리 아래 치마·다리 — 몸통과 같이 움직임)


def _hsv(frame: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(np.ascontiguousarray(frame[..., :3]), cv2.COLOR_BGR2HSV)


def ribbon_mask(frame: np.ndarray) -> np.ndarray:
    """가슴 아래 주황 리본(채움 + 2px 안 외곽선)."""
    hsv = _hsv(frame)
    h, w = frame.shape[:2]
    orange = ((hsv[..., 0] >= 3) & (hsv[..., 0] <= 22) & (hsv[..., 1] > 130) & (hsv[..., 2] > 140)
              & (frame[..., 3] > 200)).astype(np.uint8)
    k, lab, st, cen = cv2.connectedComponentsWithStats(orange, 8)
    keep = np.zeros((h, w), bool)
    for i in range(1, k):
        cx, cy = cen[i]
        if st[i][4] > 15 and RIBBON_X[0] * w <= cx <= RIBBON_X[1] * w and RIBBON_BAND[0] * h <= cy <= RIBBON_BAND[1] * h:
            keep |= lab == i
    grown = cv2.dilate(keep.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    shade = (hsv[..., 0] <= 22) & (hsv[..., 1] > 90)          # 리본 그늘
    dark = hsv[..., 2] < 140                                    # 외곽선
    return keep | (grown & (shade | dark) & (frame[..., 3] > 200))


def ribbon_orange(frame: np.ndarray) -> int:
    """리본 띠(높이·가로 범위) 안 주황 픽셀 수 — 테스트용."""
    hsv = _hsv(frame)
    h, w = frame.shape[:2]
    band = np.zeros((h, w), bool)
    band[round(h * RIBBON_BAND[0]):round(h * RIBBON_BAND[1]), round(w * 0.45):round(w * 0.75)] = True
    return int((band & (hsv[..., 0] >= 3) & (hsv[..., 0] <= 22) & (hsv[..., 1] > 130) & (hsv[..., 2] > 140)
                & (frame[..., 3] > 200)).sum())


def _skin(frame: np.ndarray) -> np.ndarray:
    """팔·손 피부(고르게 밝은 분홍, 덩어리) — 드레스 천(크림·꽃무늬)은 b가 더 노랗고 얼룩짐."""
    lab = cv2.cvtColor(np.ascontiguousarray(frame[..., :3]), cv2.COLOR_BGR2LAB).astype(int)
    m = ((lab[..., 0] > 212) & (np.abs(lab[..., 1] - 136) <= 5) & (lab[..., 2] <= 139)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    k, lab_, st, _ = cv2.connectedComponentsWithStats(m, 8)
    big = np.isin(lab_, [i for i in range(1, k) if st[i][4] >= 40])
    return cv2.dilate(big.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0


def _align(frame: np.ndarray, source: np.ndarray) -> tuple[float, int, int]:
    """source 치마·다리(키 62~92%)를 frame에서 찾음 → (배율, source 원점이 frame에서 놓일 x, y)."""
    g = lambda im: cv2.cvtColor(np.ascontiguousarray(im[..., :3]), cv2.COLOR_BGR2GRAY)
    hs = source.shape[0]
    y0, y1 = round(hs * FIT_BAND[0]), round(hs * FIT_BAND[1])
    face = g(source)[y0:y1]
    best = (-1.0, (1.0, 0, 0))
    for s in np.arange(0.95, 1.0501, 0.0125):
        t = cv2.resize(face, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        img = g(frame)
        if img.shape[0] < t.shape[0] or img.shape[1] < t.shape[1]:
            continue
        r = cv2.matchTemplate(img, t, cv2.TM_CCOEFF_NORMED)
        _, score, _, (x, y) = cv2.minMaxLoc(r)
        if score > best[0]:
            best = (score, (float(s), round(x), round(y - y0 * s)))
    return best[1]


def add_ribbon(frame: np.ndarray, source: np.ndarray) -> np.ndarray:
    s, ox, oy = _align(frame, source)
    src = cv2.resize(source, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    mask = cv2.resize(ribbon_mask(source).astype(np.uint8), (src.shape[1], src.shape[0]),
                      interpolation=cv2.INTER_NEAREST) > 0
    H, W = frame.shape[:2]
    out = frame.copy()
    big = np.zeros((H, W), bool)
    sprite = np.zeros_like(frame)
    ys, xs = np.nonzero(mask)
    ty, tx = ys + oy, xs + ox
    inside = (ty >= 0) & (ty < H) & (tx >= 0) & (tx < W)
    big[ty[inside], tx[inside]] = True
    sprite[ty[inside], tx[inside]] = src[ys[inside], xs[inside]]
    hsv = _hsv(frame)
    cover = _skin(frame) | (hsv[..., 2] < 120)                  # 앞을 가린 팔·손과 그 외곽선
    ok = big & ~cover & (frame[..., 3] > 200)
    out[ok] = sprite[ok]
    return out


def apply_summer_ribbon(frames: dict, _folder: str, _key: str) -> dict:
    out = dict(frames)
    for name, src in RIBBON_FROM.items():
        out[name] = add_ribbon(frames[name], frames[src])
    return out


# 아리아 여름 드레스 머리 리본(사용자 11-26, QA 전달): 서 있기·머리 쓰다듬기 대기·기지개 몇 장에 땋은 머리 왼쪽 큰 주황 리본이 빠짐
# → 같은 자세에 옷만 다른 티셔츠 같은 장의 리본(그 장의 가림 그대로)을 얼굴로 자리 맞춰 옮기고, 색은 여름 드레스 리본(talk_b_base_0)에 맞춤.
HAIRBOW_FRAMES = ("stand_0", "stand_1", "hair_0", "hair_1", "hair_2", "hair_3", "stretch_0", "stretch_1")
# 티셔츠 stand_1·stretch_1은 리본 일부가 팔에 가려 그려져(잘린 조각만 옮겨짐, 렌더 11-26) → 머리 자세가 같은 옆 장 리본을 씀
HAIRBOW_DONOR = {"stand_1": "stand_0", "stretch_1": "stretch_0"}
HAIRBOW_BAND = (0.38, 0.80)      # 리본 높이(키 비율), 왼쪽 절반
HAIRBOW_FACE = (0.30, 0.50)      # 자리 맞춤 기준(눈~입)


def _orange(frame: np.ndarray, s_min: int = 130) -> np.ndarray:
    hsv = _hsv(frame)
    return (hsv[..., 0] >= 3) & (hsv[..., 0] <= 22) & (hsv[..., 1] > s_min) & (hsv[..., 2] > 140) & (frame[..., 3] > 200)


def hairbow_blob(frame: np.ndarray) -> np.ndarray:
    """땋은 머리 리본 = 키 38~80%, 왼쪽 절반에서 가장 큰 주황 덩어리."""
    h, w = frame.shape[:2]
    m = _orange(frame).astype(np.uint8)
    m[:round(h * HAIRBOW_BAND[0])] = 0
    m[round(h * HAIRBOW_BAND[1]):] = 0
    m[:, w // 2:] = 0
    k, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    if k < 2:
        return np.zeros((h, w), bool)
    return lab == 1 + int(np.argmax(st[1:, 4]))


def hairbow_size(frame: np.ndarray) -> int:
    return int(hairbow_blob(frame).sum())


def _hairbow_sprite(frame: np.ndarray) -> np.ndarray:
    """리본 덩어리 + 붙은 매듭·그늘(주황 계열) + 외곽선(어두운 곳) — 리본 둘레 3px 안."""
    blob = hairbow_blob(frame)
    grown = cv2.dilate(blob.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    hsv = _hsv(frame)
    warm = (hsv[..., 0] <= 22) & (hsv[..., 1] > 110)
    dark = hsv[..., 2] < 140
    return blob | (grown & (warm | dark) & (frame[..., 3] > 200))


def _face_align(frame: np.ndarray, source: np.ndarray) -> tuple[float, int, int]:
    g = lambda im: cv2.cvtColor(np.ascontiguousarray(im[..., :3]), cv2.COLOR_BGR2GRAY)
    hs, ws = source.shape[:2]
    y0, y1 = round(hs * HAIRBOW_FACE[0]), round(hs * HAIRBOW_FACE[1])
    x0, x1 = round(ws * 0.2), round(ws * 0.85)
    face = g(source)[y0:y1, x0:x1]
    img = g(frame)
    best = (-1.0, (1.0, 0, 0))
    for s in np.arange(0.9, 1.1001, 0.0125):
        t = cv2.resize(face, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        if img.shape[0] < t.shape[0] or img.shape[1] < t.shape[1]:
            continue
        _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(img, t, cv2.TM_CCOEFF_NORMED))
        if score > best[0]:
            best = (score, (float(s), round(x - x0 * s), round(y - y0 * s)))
    return best[1]


def _match_orange(sprite: np.ndarray, mask: np.ndarray, target_ref: np.ndarray) -> np.ndarray:
    """옮긴 리본 색을 여름 드레스 리본 색(Lab 평균)에 맞춤 — 외곽선 포함 전체를 같은 만큼 이동."""
    lab = cv2.cvtColor(np.ascontiguousarray(sprite[..., :3]), cv2.COLOR_BGR2LAB).astype(np.float64)
    ref = cv2.cvtColor(np.ascontiguousarray(target_ref[..., :3]), cv2.COLOR_BGR2LAB).astype(np.float64)
    src_o = _orange(sprite) & mask
    ref_o = hairbow_blob(target_ref)
    if src_o.sum() == 0 or ref_o.sum() == 0:
        return sprite
    lab[mask] += ref[ref_o].mean(0) - lab[src_o].mean(0)
    out = sprite.copy()
    out[..., :3] = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)
    return out


def add_hairbow(frame: np.ndarray, donor: np.ndarray, color_ref: np.ndarray) -> np.ndarray:
    s, ox, oy = _face_align(frame, donor)
    src = cv2.resize(donor, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    mask = cv2.resize(_hairbow_sprite(donor).astype(np.uint8), (src.shape[1], src.shape[0]),
                      interpolation=cv2.INTER_NEAREST) > 0
    src = _match_orange(src, mask, color_ref)
    H, W = frame.shape[:2]
    ys, xs = np.nonzero(mask)
    ty, tx = ys + oy, xs + ox
    inside = (ty >= 0) & (ty < H) & (tx >= 0) & (tx < W)
    big = np.zeros((H, W), bool)
    sprite = np.zeros_like(frame)
    big[ty[inside], tx[inside]] = True
    sprite[ty[inside], tx[inside]] = src[ys[inside], xs[inside]]
    ok = big & ~_skin(frame)                                    # 머리카락은 덮고, 앞을 지나는 팔·손은 그대로
    out = frame.copy()
    out[ok] = sprite[ok]
    out[ok, 3] = np.maximum(frame[ok, 3], sprite[ok, 3])
    return out


def apply_summer_hairbow(frames: dict, folder: str, _key: str) -> dict:
    """티셔츠(같은 캐릭터 폴더의 tshirt, 앱 결과물)에서 리본을 옮김 — tshirt가 먼저 빌드됨(OUTFITS 순서)."""
    from pathlib import Path

    from mabinogi_addon import image_io
    donor_dir = Path(__file__).resolve().parents[1] / "src/mabinogi_addon/assets/characters" / folder / "outfits" / "tshirt"
    out = dict(frames)
    for name in HAIRBOW_FRAMES:
        donor = image_io.imread(donor_dir / f"{HAIRBOW_DONOR.get(name, name)}.png", cv2.IMREAD_UNCHANGED)
        out[name] = add_hairbow(frames[name], donor, frames["talk_b_base_0"])
    return out
