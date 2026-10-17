"""Strict native small-font percentage reader, aligned by its percent symbol."""

import cv2
import numpy as np
from zipfile import BadZipFile
from .. import paths


def _load():
    try:
        with np.load(paths.detect_templates_dir()/'tuarim/small_refs.npz',allow_pickle=False) as data:
            refs,labels,percent = data['refs'],data['labels'],data['percent']
            if (labels.ndim != 1 or labels.dtype.kind not in 'iu' or refs.dtype != np.uint8
                    or percent.dtype != np.uint8 or refs.shape != (len(labels),8,6) or percent.shape != (8,8)
                    or set(labels.tolist()) != set(range(10))
                    or not np.isin(refs,[0,1]).all() or not np.isin(percent,[0,1]).all()
                    or not percent.any() or percent.all()):
                return None
            return refs,labels,percent
    except (OSError,ValueError,KeyError,EOFError,BadZipFile):
        return None


_REFS = _load()


def read_small(region, threshold=.92):
    """Return (recognized rendering, value); uncertain words never use a legacy fallback."""
    if _REFS is None or region.shape[0] < 10 or region.shape[1] < 12:
        return False,None
    refs,labels,percent = _REFS
    ink = ((region.min(axis=2)>=180)&(np.ptp(region,axis=2)<=35)).astype(np.uint8)
    scores = cv2.matchTemplate(ink.astype(np.float32),percent.astype(np.float32),cv2.TM_CCOEFF_NORMED)
    _,score,_,(px,py) = cv2.minMaxLoc(scores)
    if score < .93:
        return False,None
    if py == 0 or py+8 >= ink.shape[0] or px < 4:
        return True,None
    strip = ink[py:py+8,:px]
    columns = np.flatnonzero(strip.any(axis=0))
    groups = np.split(columns,np.flatnonzero(np.diff(columns)>1)+1)
    groups = [group for group in groups if len(group)]
    chosen = []
    right = px
    for group in reversed(groups):
        left,end = int(group[0]),int(group[-1])+1
        if right-end > 4:
            break
        if len(chosen) == 3 or not 2 <= end-left <= 6 or left < 2:
            return True,None
        glyph = np.zeros((8,6),np.uint8)
        glyph[:,:end-left] = strip[:,left:end]
        if (not glyph[0].any() or not glyph[-1].any()
                or ink[py-1,left:end].any() or ink[py+8,left:end].any()):
            return True,None
        # One background pixel may extend a glyph's bounding box by one column.
        # Align inside padding without dropping any ink or relaxing the score.
        padded = np.pad(refs,((0,0),(0,0),(1,1)))
        actual = np.pad(glyph,((0,0),(1,1)))
        similarity = np.max(np.stack([
            1-(np.roll(padded,shift,axis=2)!=actual).sum(axis=(1,2))/48
            for shift in (-1,0,1)
        ]),axis=0)
        ranked = sorted((float(similarity[labels==digit].max()),digit) for digit in range(10))
        if ranked[-1][0] < max(.92,threshold) or ranked[-1][0]-ranked[-2][0] < .05:
            return True,None
        chosen.append(ranked[-1][1])
        right = left
    if not chosen or (len(chosen)>1 and chosen[-1]==0):
        return True,None
    value = sum(digit*10**i for i,digit in enumerate(chosen))
    return True,value if value < 100 else None
