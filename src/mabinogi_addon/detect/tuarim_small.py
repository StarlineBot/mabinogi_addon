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


def _load_uhd():
    """4K(9px) 작은 글자 세트(0.30.2, scripts/build_tuarim_uhd_refs.py). 자료에 있던 숫자만(5·6·7 없음 → 못 읽음)."""
    try:
        with np.load(paths.detect_templates_dir()/'tuarim/small_uhd_refs.npz',allow_pickle=False) as data:
            refs,labels,percent = data['refs'],data['labels'],data['percent']
            if (labels.ndim != 1 or labels.dtype.kind not in 'iu' or refs.dtype != np.uint8 or percent.dtype != np.uint8
                    or refs.ndim != 3 or refs.shape[0] != len(labels) or percent.ndim != 3 or refs.shape[1] != percent.shape[1]
                    or not np.isin(refs,[0,1]).all() or not np.isin(percent,[0,1]).all()
                    or not percent.any() or percent.all()):
                return None
            return refs,labels,percent
    except (OSError,ValueError,KeyError,EOFError,BadZipFile):
        return None


_UHD = _load_uhd()


def read_small(region, threshold=.92):
    """Return (recognized rendering, value); uncertain words never use a legacy fallback.

    기본(8px) 렌더링의 '%'가 안 맞으면 4K(9px) 렌더링으로 한 번 더 본다(0.30.2)."""
    if region.shape[0] < 10 or region.shape[1] < 12:
        return False,None
    for rendering in (_REFS, _UHD):
        if rendering is None:
            continue
        matched,value = _read_rendering(region, rendering, threshold)
        if matched:
            return True,value
    return False,None


def _read_rendering(region, rendering, threshold):
    refs,labels,percents = rendering
    gh,gw = refs.shape[1],refs.shape[2]
    ink = ((region.min(axis=2)>=180)&(np.ptp(region,axis=2)<=35)).astype(np.uint8)
    score,px,py = -1.0,0,0
    for percent in (percents if percents.ndim == 3 else [percents]):  # 4K는 '%' 모양 변형이 여럿
        if ink.shape[0] < percent.shape[0] or ink.shape[1] < percent.shape[1]:
            continue
        scores = cv2.matchTemplate(ink.astype(np.float32),percent.astype(np.float32),cv2.TM_CCOEFF_NORMED)
        _,s,_,(x,y) = cv2.minMaxLoc(scores)
        if s > score:
            score,px,py = s,x,y
    if score < .93:
        return False,None
    if py == 0 or py+gh >= ink.shape[0] or px < 4:
        return True,None
    strip = ink[py:py+gh,:px]
    columns = np.flatnonzero(strip.any(axis=0))
    groups = np.split(columns,np.flatnonzero(np.diff(columns)>1)+1)
    groups = [group for group in groups if len(group)]
    chosen = []
    right = px
    for group in reversed(groups):
        left,end = int(group[0]),int(group[-1])+1
        if right-end > 4:
            break
        if len(chosen) == 3 or not 2 <= end-left <= gw or left < 2:
            return True,None
        glyph = np.zeros((gh,gw),np.uint8)
        glyph[:,:end-left] = strip[:,left:end]
        if (not glyph[0].any() or not glyph[-1].any()
                or ink[py-1,left:end].any() or ink[py+gh,left:end].any()):
            return True,None
        # One background pixel may extend a glyph's bounding box by one column.
        # Align inside padding without dropping any ink or relaxing the score.
        padded = np.pad(refs,((0,0),(0,0),(1,1)))
        actual = np.pad(glyph,((0,0),(1,1)))
        similarity = np.max(np.stack([
            1-(np.roll(padded,shift,axis=2)!=actual).sum(axis=(1,2))/(gh*gw)
            for shift in (-1,0,1)
        ]),axis=0)
        ranked = sorted((float(similarity[labels==digit].max()),digit) for digit in np.unique(labels).tolist())
        if ranked[-1][0] < max(.92,threshold) or ranked[-1][0]-ranked[-2][0] < .05:
            return True,None
        chosen.append(ranked[-1][1])
        right = left
    if not chosen or (len(chosen)>1 and chosen[-1]==0):
        return True,None
    value = sum(digit*10**i for i,digit in enumerate(chosen))
    return True,value if value < 100 else None
