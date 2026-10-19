"""Conservative timer glyph matching; raw observations never use the clock prediction."""

from functools import lru_cache

import cv2
import numpy as np

from .. import paths


def ink(frame):
    low = frame.min(axis=2)
    spread = frame.max(axis=2).astype(np.int16)-low
    return ((low > 235) & (spread < 15)).astype(np.uint8)


def normalize(mask):
    _,labels,stats,_=cv2.connectedComponentsWithStats(mask)
    height,width=mask.shape
    eligible=[(i,s) for i,s in enumerate(stats[1:],1)
              if 0<s[1] and s[1]+s[3]<height and .65*height<=s[3]<=height
              and .15*height<=s[2]<=.9*height]
    if len(eligible)!=1:
        return None
    i,(x,y,w,h,_)=eligible[0]
    glyph=(labels[y:y+h,x:x+w]==i).astype(np.uint8)
    scale=min(20/w,26/h)
    w,h=max(1,round(w*scale)),max(1,round(h*scale))
    result=np.zeros((29,22),np.uint8)
    left,top=(22-w)//2,(29-h)//2
    result[top:top+h,left:left+w]=cv2.resize(glyph,(w,h),interpolation=cv2.INTER_NEAREST)
    return result


def cells(frame):
    if (not isinstance(frame,np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3
            or frame.shape[2] != 3 or not frame.size or frame.size > 3*1024*1024):
        return []
    mask = ink(frame)
    _,_,stats,_ = cv2.connectedComponentsWithStats(mask)
    dots = [tuple(map(int,s)) for s in stats[1:] if 2 <= s[2] <= 14 and 2 <= s[3] <= 14
            and .6 <= s[2]/s[3] <= 1.5 and s[4] >= .55*s[2]*s[3]]
    if len(dots)>64:
        return []
    candidates = []
    for x,y,w,h,_ in dots:
        for xx,yy,ww,hh,_ in dots:
            distance = yy-y
            if not (abs(x-xx) <= 1 and abs(w-ww) <= 1 and abs(h-hh) <= 1 and 2.5*h <= distance <= 4*h):
                continue
            scale = distance/16
            cx = x+w/2
            top = round(y-3*scale)
            height = round(29*scale)
            glyphs = []
            for left,right in ((-46,-28),(-26,-4),(6,28),(28,50)):
                a,b = round(cx+left*scale),round(cx+right*scale)
                if a < 0 or b > mask.shape[1] or top < 0 or top+height > mask.shape[0]:
                    break
                glyph=normalize(mask[top:top+height,a:b])
                if glyph is None:
                    break
                glyphs.append(glyph)
            if len(glyphs)==4:
                candidates.append((glyphs,(round(cx-46*scale),top,round(96*scale),height)))
            if len(candidates)>32:
                return []
    return candidates


@lru_cache(maxsize=1)
def references():
    path = paths.detect_templates_dir()/'halo_timer/refs.npz'
    with np.load(path,allow_pickle=False) as archive:
        return archive['images'].copy(),archive['labels'].copy(),archive['slots'].copy()


def read_seconds(frame):
    """Return a raw 0..900 second observation, or None on ambiguity/missing glyphs."""
    found = []
    try:
        images,labels,slots = references()
        for glyphs,box in cells(frame):
            digits = []
            for slot,glyph in enumerate(glyphs):
                refs = images
                names = labels
                if not len(refs):
                    break
                intersection = (refs & glyph).sum(axis=(1,2))
                union = (refs | glyph).sum(axis=(1,2))
                scores = intersection/np.maximum(union,1)
                ranked = sorted(((float(scores[names==digit].max()),int(digit)) for digit in np.unique(names)),reverse=True)
                best,digit = ranked[0]
                if best < .55 or len(ranked)>1 and best-ranked[1][0] < .08:
                    break
                digits.append(digit)
            if len(digits)==4:
                minutes,seconds = digits[0]*10+digits[1],digits[2]*10+digits[3]
                total=minutes*60+seconds
                if seconds<60 and total<=900:
                    found.append((total,box))
    except (OSError,ValueError,KeyError,cv2.error):
        return None
    return found[0][0] if len(found)==1 else None
