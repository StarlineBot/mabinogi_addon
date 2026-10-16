"""Locate the masked circular ornament without relying on its number or percent."""

import cv2
import numpy as np
from pathlib import Path

from .. import image_io
from .autofind_anchors import ACCEPT, SCALES, assets as tuarim_assets, candidates
from .dorcha_reader import read_dorcha, reference_assets, references_from_assets


def assets():
    source = tuarim_assets("tuarim")
    if "anchor" not in source or "mask" not in source:
        return {}
    circle = source["anchor"][:, :45].copy()
    gray = cv2.cvtColor(circle, cv2.COLOR_BGR2GRAY)
    result = {"anchor": cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR),
              "mask": source["mask"][:, :45].copy()}
    alternate = image_io.imread(Path(__file__).parent / "templates/autofind/dorcha_anchor_alt.png")
    if alternate is not None:
        result["anchor_alt"] = alternate
    result.update(reference_assets())
    return result


def locate_dorcha(frame, templates=None, diagnostics=None, cancelled=None):
    trace = diagnostics if diagnostics is not None else {}
    templates = assets() if templates is None else templates
    if (not templates or not isinstance(frame, np.ndarray) or frame.dtype != np.uint8
            or frame.ndim != 3 or frame.shape[2] != 3 or not frame.size):
        trace["rejection"] = "invalid_frame_or_assets"
        return None
    anchor,mask = templates.get("anchor"),templates.get("mask")
    if (not isinstance(anchor,np.ndarray) or not isinstance(mask,np.ndarray)
            or anchor.dtype != np.uint8 or mask.dtype != np.uint8
            or anchor.ndim != 3 or anchor.shape[2] != 3 or mask.shape != anchor.shape[:2]
            or not anchor.size or not np.any(mask)):
        trace["rejection"] = "invalid_assets"
        return None
    references = references_from_assets(templates)
    if references is None:
        trace["rejection"] = "missing_word_references"
        return None
    anchors = [anchor]
    alternate = templates.get("anchor_alt")
    if alternate is not None:
        if not isinstance(alternate, np.ndarray) or alternate.dtype != np.uint8 or alternate.shape != anchor.shape:
            trace["rejection"] = "invalid_assets"
            return None
        anchors.append(alternate)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    search_frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    matches = []
    searches = []
    for source in anchors:
        if cancelled is not None and cancelled():
            trace["rejection"] = "cancelled"
            return None
        search = {}
        matches.extend(candidates(search_frame, {"anchor":source,"mask":mask}, search, cancelled))
        searches.append(search)
    trace.update(searches[0])
    trace["anchor_searches"] = searches
    trace.setdefault("transforms", []).append("grayscale circle only; inner digits and percent excluded")
    if not matches and trace.get("rejection") != "invalid_mask":
        # Bright backgrounds can hide the ornament in the downsampled search.
        # Retry native pixels with the same strict score, not a weaker threshold.
        trace["transforms"].append("native grayscale fallback; unchanged acceptance score")
        for source, scale in ((source, scale) for source in anchors for scale in SCALES):
            if cancelled is not None and cancelled():
                trace["rejection"] = "cancelled"
                return None
            anchor = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
            w,h = round(anchor.shape[1]*scale),round(anchor.shape[0]*scale)
            if w > gray.shape[1] or h > gray.shape[0]:
                continue
            template = cv2.resize(anchor,(w,h),interpolation=cv2.INTER_AREA)
            scaled_mask = cv2.resize(mask,(w,h),interpolation=cv2.INTER_NEAREST)
            scores = cv2.matchTemplate(gray,template,cv2.TM_CCORR_NORMED,mask=scaled_mask)
            scores = np.nan_to_num(scores,nan=0,posinf=0,neginf=0)
            for _ in range(3):
                _,score,_,point = cv2.minMaxLoc(scores)
                if score < ACCEPT:
                    break
                x,y = point
                item = dict(anchor=[x,y,w,h],scale=scale,score=float(score))
                trace.setdefault("candidates",[]).append(item)
                if not any(abs(x-other["anchor"][0]) < w/2 and abs(y-other["anchor"][1]) < h/2
                           for other in matches):
                    matches.append(item)
                scores[max(0,y-h//2):y+h//2+1,max(0,x-w//2):x+w//2+1] = 0
    unique = []
    for item in sorted(matches, key=lambda candidate: candidate["score"], reverse=True):
        x,y,w,h = item["anchor"]
        if not any(abs(x-other["anchor"][0]) < w/2 and abs(y-other["anchor"][1]) < h/2
                   for other in unique):
            unique.append(item)
    matches = unique
    if len(matches) != 1:
        trace["rejection"] = "ambiguous_candidates" if matches else "anchor_not_found"
        return None
    match = matches[0]
    x, y, _, _ = match["anchor"]
    scale = match["scale"]
    box = (x + round(8*scale), y + round(17*scale), round(28*scale), round(23*scale))
    if box[0] + box[2] > frame.shape[1] or box[1] + box[3] > frame.shape[0]:
        trace["rejection"] = "digit_region_clipped"
        return None
    value = read_dorcha(frame[box[1]:box[1]+box[3], box[0]:box[0]+box[2]], references=references)
    if value is None:
        trace["rejection"] = "unreadable_digits"
        return None
    trace["value"] = value
    trace["result"] = list(box)
    return box
