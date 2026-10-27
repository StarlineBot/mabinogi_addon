"""Shared ornament search, independent of both resource readers and settings."""

from pathlib import Path

import cv2
import numpy as np

from .. import image_io
from .autofind_anchors import ACCEPT, SCALES, assets as load_anchors, candidates


def assets():
    source = load_anchors("tuarim")
    if "anchor" not in source or "mask" not in source:
        return {}
    gray = cv2.cvtColor(source["anchor"][:, :45], cv2.COLOR_BGR2GRAY)
    result = {"anchor":cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR),
              "mask":source["mask"][:, :45].copy()}
    alternate = image_io.imread(Path(__file__).parent / "templates/autofind/dorcha_anchor_alt.png")
    if alternate is not None:
        result["anchor_alt"] = alternate
    live = image_io.imread(Path(__file__).parent / "templates/autofind/dorcha_anchor_live.png")
    if live is not None:
        result["anchor_live"] = live
    seven = image_io.imread(Path(__file__).parent / "templates/autofind/dorcha_anchor_seven.png")
    if seven is not None:
        result["anchor_seven"] = seven
    return result


def valid_inputs(frame,templates,trace):
    if (not templates or not isinstance(frame,np.ndarray) or frame.dtype != np.uint8
            or frame.ndim != 3 or frame.shape[2] != 3 or not frame.size):
        trace["rejection"] = "invalid_frame_or_assets"
        return False
    anchor,mask = templates.get("anchor"),templates.get("mask")
    if (not isinstance(anchor,np.ndarray) or not isinstance(mask,np.ndarray)
            or anchor.dtype != np.uint8 or mask.dtype != np.uint8
            or anchor.ndim != 3 or anchor.shape[2] != 3 or mask.shape != anchor.shape[:2]
            or not anchor.size or not np.any(mask)):
        trace["rejection"] = "invalid_assets"
        return False
    return True


def ornament_candidates(frame,templates,trace,cancelled=None,accept=ACCEPT):
    """accept: 후보로 돌려줄 최저 점수(기본 0.97). 도르카는 0.94까지 받아 숫자 판독으로 한 번 더 거른다."""
    if not valid_inputs(frame,templates,trace):
        return []
    anchor,mask = templates["anchor"],templates["mask"]
    anchors = [anchor]
    for name in ("anchor_alt", "anchor_live", "anchor_seven"):
        alternate = templates.get(name)
        if alternate is None:
            continue
        if not isinstance(alternate,np.ndarray) or alternate.dtype != np.uint8 or alternate.shape != anchor.shape:
            trace["rejection"] = "invalid_assets"
            return []
        anchors.append(alternate)
    gray = cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    search_frame = cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR)
    matches,searches = [],[]
    for source in anchors:
        if cancelled is not None and cancelled():
            trace["rejection"] = "cancelled"
            return []
        search = {}
        matches.extend(candidates(search_frame,{"anchor":source,"mask":mask},search,cancelled,accept))
        searches.append(search)
    trace.update(searches[0])
    trace["anchor_searches"] = searches
    trace["transforms"] = [*trace["transforms"],"grayscale circle only; inner digits and percent excluded"]
    trace["candidates"] = [item for search in searches for item in search["candidates"]]
    if not matches:
        trace["transforms"].append("native grayscale fallback; unchanged acceptance score")
        for source,scale in ((source,scale) for source in anchors for scale in SCALES):
            if cancelled is not None and cancelled():
                trace["rejection"] = "cancelled"
                return []
            native = cv2.cvtColor(source,cv2.COLOR_BGR2GRAY)
            w,h = round(native.shape[1]*scale),round(native.shape[0]*scale)
            if w > gray.shape[1] or h > gray.shape[0]:
                continue
            template = cv2.resize(native,(w,h),interpolation=cv2.INTER_AREA)
            scaled_mask = cv2.resize(mask,(w,h),interpolation=cv2.INTER_NEAREST)
            scores = cv2.matchTemplate(gray,template,cv2.TM_CCORR_NORMED,mask=scaled_mask)
            scores = np.nan_to_num(scores,nan=0,posinf=0,neginf=0)
            for _ in range(3):
                _,score,_,(x,y) = cv2.minMaxLoc(scores)
                if score < accept:
                    break
                item = dict(anchor=[x,y,w,h],scale=scale,score=float(score))
                trace["candidates"].append(item)
                matches.append(item)
                scores[max(0,y-h//2):y+h//2+1,max(0,x-w//2):x+w//2+1] = 0
    unique = []
    for item in sorted(matches,key=lambda candidate:candidate["score"],reverse=True):
        x,y,w,h = item["anchor"]
        if not any(abs(x-other["anchor"][0]) < w/2 and abs(y-other["anchor"][1]) < h/2 for other in unique):
            unique.append(item)
    return unique
