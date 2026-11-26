"""착장 걷기 얼굴 옆선 고치기(QA 11-26 — 레나 연구실 차림 걷기: 볼·코·턱 외곽선이 흐려 없고 안경이 얼굴 밖으로 뜸).

옷 걷기 칸이 기본 걷기와 거의 같은 자세(머리 실루엣 IoU 0.96~0.98)라, 칸마다 기본 walk_i를 정렬(배율·이동)해서
얼굴(피부·눈·볼 옆선 외곽선 — 머리카락(파랑) 빼고, 머리 높이 안)만 옷 그림 위에 옮겨 붙이고, 옷의 안경(금색 테)만 다시 얹는다.
경계는 2px 페더, 피부색은 그 옷 stand_0 피부 평균에 맞춤.
"""
from __future__ import annotations

import cv2
import numpy as np

HEAD = 0.45          # 얼굴을 찾는 높이(위에서 키의 45%)


def _canvas(img, h, w, dx=0, dy=0, s=1.0):
    """발 밑 가운데 맞춤으로 (h, w) 캔버스에 놓음(+이동·배율)."""
    if s != 1.0:
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    out = np.zeros((h, w, 4), np.uint8)
    ih, iw = img.shape[:2]
    x0, y0 = (w - iw) // 2 + dx, h - ih + dy
    xs, ys = max(0, x0), max(0, y0)
    xe, ye = min(w, x0 + iw), min(h, y0 + ih)
    if xe > xs and ye > ys:
        out[ys:ye, xs:xe] = img[ys - y0:ye - y0, xs - x0:xe - x0]
    return out


def _skin(img):
    hsv = cv2.cvtColor(np.ascontiguousarray(img[..., :3]), cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0].astype(int), hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    return (img[..., 3] > 200) & ((h <= 20) | (h >= 170)) & (s >= 15) & (s <= 120) & (v >= 170)


def _hair(img):
    hsv = cv2.cvtColor(np.ascontiguousarray(img[..., :3]), cv2.COLOR_BGR2HSV)
    return (img[..., 3] > 0) & (hsv[..., 0] >= 100) & (hsv[..., 0] <= 140) & (hsv[..., 1] >= 50)


def _gold(img):
    hsv = cv2.cvtColor(np.ascontiguousarray(img[..., :3]), cv2.COLOR_BGR2HSV)
    return (img[..., 3] > 60) & (hsv[..., 0] >= 10) & (hsv[..., 0] <= 35) & (hsv[..., 1] >= 50) & (hsv[..., 2] >= 90)


def align(base, dressed):
    """기본 칸을 옷 칸에 맞추는 (배율, dx, dy) — 머리 높이 안 피부(얼굴·귀) IoU 최대(머리카락 모양은 옷마다 달라 안 씀)."""
    h = max(base.shape[0], dressed.shape[0]) + 20
    w = max(base.shape[1], dressed.shape[1]) + 40
    d = _canvas(dressed, h, w)
    rows = slice(h - dressed.shape[0], h - dressed.shape[0] + round(dressed.shape[0] * HEAD))
    target = _skin(d)[rows]
    best = (-1.0, (1.0, 0, 0))
    for s in np.arange(0.96, 1.041, 0.01):
        b0 = _canvas(base, h, w, 0, 0, float(s))
        skin0 = _skin(b0)
        for dy in range(-12, 13):
            for dx in range(-20, 21):
                m = np.roll(np.roll(skin0, dy, axis=0), dx, axis=1)[rows]
                iou = (m & target).sum() / max(1, (m | target).sum())
                if iou > best[0]:
                    best = (iou, (float(s), dx, dy))
    return best[1], best[0]


def fix_face(dressed, base, stand):
    """dressed(옷 걷기 칸)에 base(기본 걷기 같은 칸)의 얼굴을 옮겨 붙임 → 새 그림(크기 같음)."""
    (s, dx, dy), _iou = align(base, dressed)
    h = max(base.shape[0], dressed.shape[0]) + 20
    w = max(base.shape[1], dressed.shape[1]) + 40
    d = _canvas(dressed, h, w)
    b = _canvas(base, h, w, dx, dy, s)
    top = h - dressed.shape[0]
    rows = np.zeros((h, w), bool)
    rows[top:top + round(dressed.shape[0] * HEAD)] = True
    skin = _skin(b) & rows
    # 피부에서 6px 안(볼 옆선 외곽선·눈 포함), 머리카락(파랑)은 빼고 — 옷 그림의 앞머리·땋은 머리는 그대로
    face = cv2.dilate(skin.astype(np.uint8), np.ones((13, 13), np.uint8)) > 0
    face &= rows & (b[..., 3] > 0) & ~_hair(b)
    # 귀(머리카락 뒤쪽)는 옷 그림 것 그대로 — 얼굴 앞쪽(눈보다 앞)만
    eye_x = np.where(skin.any(axis=0))[0]
    if eye_x.size:
        face[:, : int(np.percentile(eye_x, 45))] = False
    glasses = cv2.dilate(_gold(d).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    weight = cv2.GaussianBlur(face.astype(np.float32), (5, 5), 1.0)[..., None]   # 2px 페더
    weight[glasses] = 0.0
    # 피부 톤을 이 옷 stand_0 피부 평균에(Lab)
    src = b.copy()
    ref_skin = _skin(stand)
    if ref_skin.sum() > 50 and skin.sum() > 50:
        lab = cv2.cvtColor(np.ascontiguousarray(src[..., :3]), cv2.COLOR_BGR2LAB).astype(np.float32)
        ref = cv2.cvtColor(np.ascontiguousarray(stand[..., :3]), cv2.COLOR_BGR2LAB).astype(np.float32)
        lab[skin] += ref[ref_skin].mean(0) - lab[skin].mean(0)
        src[..., :3] = np.where(skin[..., None], cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR),
                                src[..., :3])
    out = d.astype(np.float32)
    alpha_b = src[..., 3:].astype(np.float32)
    out[..., :3] = out[..., :3] * (1 - weight) + src[..., :3].astype(np.float32) * weight
    out[..., 3:] = np.maximum(out[..., 3:] * (1 - weight), alpha_b * weight + out[..., 3:] * (1 - weight))
    out = np.clip(out, 0, 255).astype(np.uint8)
    out[glasses] = d[glasses]
    # 원래 옷 칸 자리로 잘라 냄(크기 그대로)
    x0 = (w - dressed.shape[1]) // 2
    return out[top:top + dressed.shape[0], x0:x0 + dressed.shape[1]]


# ---- 걷기 머리 하나로(QA 11-26 '레나 lab 걷기 머리가 자글자글' — 사용자 '머리는 움직이는 구간이 아니라 한 장으로') ----------------
CUT = 0.47          # 머리 경계(키 비율) — 턱 아래 초커 높이. 이 위는 기준 장 머리, 아래(등 뒤로 늘어진 머리·몸)는 장마다 그대로
FEATHER = 6         # 경계 페더(px)


def _place(img, h, w, x0, y0, s=1.0):
    if s != 1.0:
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    out = np.zeros((h, w, 4), np.uint8)
    ih, iw = img.shape[:2]
    xs, ys, xe, ye = max(0, x0), max(0, y0), min(w, x0 + iw), min(h, y0 + ih)
    if xe > xs and ye > ys:
        out[ys:ye, xs:xe] = img[ys - y0:ye - y0, xs - x0:xe - x0]
    return out


def unify_head(frames: list[np.ndarray], ref_index: int = 0) -> list[np.ndarray]:
    """기준 장 머리(정수리 ~ 턱 아래 CUT)를 다른 장마다 위치(dx, dy)·배율(±2%)을 맞춰 붙임 — 위 40% 알파 IoU 정렬."""
    ref = frames[ref_index]
    rh, rw = ref.shape[:2]
    out = []
    for i, frame in enumerate(frames):
        if i == ref_index:
            out.append(frame)
            continue
        fh, fw = frame.shape[:2]
        target = frame[: round(fh * 0.40), :, 3] > 128
        best = (-1.0, (1.0, 0, 0))
        for s in (0.98, 0.99, 1.0, 1.01, 1.02):
            sw, sh = round(rw * s), round(rh * s)
            base_x, base_y = (fw - sw) // 2, fh - sh   # 발 밑 가운데 맞춤에서 시작
            for dy in range(-8, 9):
                for dx in range(-15, 16):
                    p = _place(ref, fh, fw, base_x + dx, base_y + dy, s)[: round(fh * 0.40), :, 3] > 128
                    iou = (p & target).sum() / max(1, (p | target).sum())
                    if iou > best[0]:
                        best = (iou, (s, base_x + dx, base_y + dy))
        s, x0, y0 = best[1]
        head = _place(ref, fh, fw, x0, y0, s)
        cut = y0 + round(rh * s * CUT)
        rows = np.arange(fh, dtype=np.float32)[:, None, None]
        w = np.clip((cut + FEATHER / 2 - rows) / FEATHER, 0, 1)   # 경계 위 1 → 아래 0
        a_f = frame[..., 3:].astype(np.float32) / 255
        a_h = head[..., 3:].astype(np.float32) / 255
        a = a_h * w + a_f * (1 - w)
        rgb = (head[..., :3] * a_h * w + frame[..., :3] * a_f * (1 - w)) / np.maximum(a, 1e-6)
        mixed = np.dstack([np.clip(rgb, 0, 255), np.clip(a * 255, 0, 255)]).astype(np.uint8)
        mixed[mixed[..., 3] == 0, :3] = 0
        out.append(mixed)
    return out
