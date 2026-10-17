"""Locate the movable Tuarim decoration, not its changing inner number."""

from pathlib import Path

import cv2
import numpy as np

from .. import image_io
from .autofind_anchors import ACCEPT, assets as load_anchors, candidates
from . import resource_anchor


def assets():
    result = load_anchors("tuarim")
    live = image_io.imread(Path(__file__).parent / "templates/autofind/tuarim_structure_live.png")
    if live is not None:
        result["structure_live"] = live
    result.update({f"circle_{key}":image for key,image in resource_anchor.assets().items()})
    return result


def locate_tuarim(frame, templates=None, diagnostics=None):
    trace = diagnostics if diagnostics is not None else {}
    templates = assets() if templates is None else templates
    if not resource_anchor.valid_inputs(frame,templates,trace):
        return None
    # Only the opaque button interior is invariant; the old mask also includes
    # game background below the button and beside the circle. Clip before scaling.
    button_mask = np.zeros_like(templates["mask"])
    button_mask[33:44,47:71] = templates["mask"][33:44,47:71]
    matches = candidates(frame,templates,trace)
    circle = {key.removeprefix("circle_"):image for key,image in templates.items() if key.startswith("circle_")}
    if not circle:
        # Older diagnostic ZIPs carry only the original full ornament.
        gray = cv2.cvtColor(templates["anchor"][:,:45],cv2.COLOR_BGR2GRAY)
        circle = {"anchor":cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR),"mask":templates["mask"][:,:45]}
    circle_trace = {}
    extra = resource_anchor.ornament_candidates(frame,circle,circle_trace)
    trace["ornament_search"] = circle_trace
    for item in extra:
        x,y,_,_ = item["anchor"]
        scale = item["scale"]
        w,h = round(templates["anchor"].shape[1]*scale),round(templates["anchor"].shape[0]*scale)
        if x+w > frame.shape[1] or y+h > frame.shape[0]:
            continue
        # Fractional scales must not include a pixel blended with scenery.
        coverage = cv2.resize(button_mask,(w,h),interpolation=cv2.INTER_AREA)
        mask = np.where(coverage == 255,255,0).astype(np.uint8)
        # The shared detector already validated the circle using all supported models.
        # Verify the independent right-hand structure, not the old circle a second time.
        if not mask.any():
            continue
        scores = []
        for name in ("anchor", "structure_live"):
            model = templates.get(name)
            if not isinstance(model,np.ndarray) or model.shape != templates["anchor"].shape or model.dtype != np.uint8:
                continue
            native = cv2.resize(model,(w,h),interpolation=cv2.INTER_AREA)
            score = float(cv2.matchTemplate(frame[y:y+h,x:x+w],native,cv2.TM_CCORR_NORMED,mask=mask)[0,0])
            scores.append((score if np.isfinite(score) else 0.0, name))
        score, model_name = max(scores)
        item = {**item,"ornament_score":item["score"],"structure_score":score,
                "structure_model":model_name,"score":score,"anchor":[x,y,w,h],"method":"shared_circle_right_structure"}
        trace["candidates"].append(item)
        if np.isfinite(score) and score >= ACCEPT and not any(
                abs(x-other["anchor"][0]) < w/2 and abs(y-other["anchor"][1]) < h/2 for other in matches):
            matches.append(item)
    valid = []
    for item in matches:
        x, y, _w, _h = item["anchor"]
        scale = item["scale"]
        box = (x + round(34 * scale), y + round(45 * scale), round(42 * scale), round(16 * scale))
        if box[0] + box[2] <= frame.shape[1] and box[1] + box[3] <= frame.shape[0]:
            item["result"] = list(box)
            valid.append(box)
        else:
            item["rejection"] = "percent_region_clipped"
    if len(valid) != 1:
        trace["rejection"] = "ambiguous_candidates" if len(valid) > 1 else "anchor_not_found"
        return None
    trace["result"] = list(valid[0])
    return valid[0]
