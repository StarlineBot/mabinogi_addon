"""Masked structural anchors shared by the two opt-in UI locators."""

from pathlib import Path

import cv2
import numpy as np

from .. import image_io


SCALES = (0.75, 1.0, 1.25, 1.5, 2.0)
ACCEPT = 0.97


def assets(feature):
    root = Path(__file__).parent / "templates/autofind"
    result = {}
    for name in ("anchor", "mask"):
        flags = cv2.IMREAD_GRAYSCALE if name == "mask" else cv2.IMREAD_COLOR
        image = image_io.imread(root / f"{feature}_{name}.png", flags)
        if image is not None:
            result[name] = image
    return result


def candidates(frame, templates, trace, cancelled=None, accept=ACCEPT):
    anchor, mask = templates["anchor"], templates["mask"]
    if frame is None or frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
        trace["rejection"] = "invalid_frame"
        return []
    if mask.shape != anchor.shape[:2] or not np.any(mask):
        trace["rejection"] = "invalid_mask"
        return []
    ratio = min(1.0, 1280 / max(frame.shape[:2]))
    small = cv2.resize(frame, None, fx=ratio, fy=ratio, interpolation=cv2.INTER_AREA)
    trace.update(accept_score=accept, search_scales=list(SCALES),
                 transforms=["BGR masked CCORR_NORMED", "coarse max side <= 1280", "native-resolution refinement"],
                 coarse_ratio=ratio, candidates=[])
    found = []
    for scale in SCALES:
        if cancelled is not None and cancelled():
            return []
        w, h = round(anchor.shape[1] * scale), round(anchor.shape[0] * scale)
        cw, ch = max(2, round(w * ratio)), max(2, round(h * ratio))
        if cw > small.shape[1] or ch > small.shape[0]:
            continue
        template = cv2.resize(anchor, (cw, ch), interpolation=cv2.INTER_AREA)
        scaled_mask = cv2.resize(mask, (cw, ch), interpolation=cv2.INTER_NEAREST)
        scores = cv2.matchTemplate(small, template, cv2.TM_CCORR_NORMED, mask=scaled_mask)
        scores = np.nan_to_num(scores, nan=0, posinf=0, neginf=0)
        for _ in range(3):
            _, score, _, point = cv2.minMaxLoc(scores)
            if score < 0.90:
                break
            x, y = (round(v / ratio) for v in point)
            left, top = max(0, x - 6), max(0, y - 6)
            right, bottom = min(frame.shape[1], x + w + 7), min(frame.shape[0], y + h + 7)
            crop = frame[top:bottom, left:right]
            if crop.shape[1] >= w and crop.shape[0] >= h:
                native = cv2.resize(anchor, (w, h), interpolation=cv2.INTER_AREA)
                native_mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
                refined = cv2.matchTemplate(crop, native, cv2.TM_CCORR_NORMED, mask=native_mask)
                refined = np.nan_to_num(refined, nan=0, posinf=0, neginf=0)
                _, score, _, point_native = cv2.minMaxLoc(refined)
                x, y = left + point_native[0], top + point_native[1]
                item = {"anchor": [x, y, w, h], "scale": scale, "score": float(score)}
                trace["candidates"].append(item)
                if score >= accept:
                    found.append(item)
            px, py = point
            scores[max(0, py - ch // 2):py + ch // 2 + 1,
                   max(0, px - cw // 2):px + cw // 2 + 1] = 0
    unique = []
    for item in sorted(found, key=lambda c: c["score"], reverse=True):
        x, y, w, h = item["anchor"]
        if not any(abs(x - other["anchor"][0]) < w / 2
                   and abs(y - other["anchor"][1]) < h / 2 for other in unique):
            unique.append(item)
    return unique
