"""Locate the shared ornament, then validate only Dorcha's inner word."""

from . import resource_anchor
from .autofind_anchors import ACCEPT
from .dorcha_reader import read_dorcha, reference_assets, references_from_assets

# 2026-10-27 사용자 문의: 장식 둘레가 밝은 배경(모래·흰 바닥·보라 이펙트)이면 장식 점수가 0.958~0.967로 0.97에 못 미쳐
# 숫자를 읽을 수 있는데도 '장식 못 찾음'. 0.94~0.97 구간은 그 자리 숫자를 기준(점수·차이) 통과로 읽을 때만 인정한다.
SOFT_ACCEPT = 0.94


def assets():
    result = resource_anchor.assets()
    if result:
        result.update(reference_assets())
    return result


def locate_dorcha(frame,templates=None,diagnostics=None,cancelled=None):
    trace = diagnostics if diagnostics is not None else {}
    templates = assets() if templates is None else templates
    if not resource_anchor.valid_inputs(frame,templates,trace):
        return None
    references = references_from_assets(templates)
    if references is None:
        trace["rejection"] = "missing_word_references"
        return None
    matches = resource_anchor.ornament_candidates(frame,templates,trace,cancelled,accept=SOFT_ACCEPT)
    # 장식만으로 인정하는 기준은 그대로 0.97, 0.94~0.97은 숫자 판독까지 통과해야 함(진단에 둘 다 남김)
    trace.update(accept_score=ACCEPT,soft_accept_score=SOFT_ACCEPT)
    strong = [match for match in matches if match["score"] >= ACCEPT]
    if len(strong) > 1:
        trace.setdefault("rejection","ambiguous_candidates")
        return None
    if strong:  # 기존 기준(0.97) 통과 장식: 지금처럼 숫자까지 읽혀야 인정
        box,value,reason = _digits(frame,strong[0],references)
        if box is None:
            trace["rejection"] = reason
            return None
        trace.update(value=value,result=list(box),ornament=strong[0])
        return box
    # 0.94~0.97: 숫자를 기준 통과로 읽는 후보만. 밝은 배경에선 장식 최고점이 몇 px 어긋나고 바른 위치는 겹치는 후보로
    # 밀려나(문의 4K: 최고 y=1722 0.958, 바른 y=1719 0.956), 겹침 제거 전 후보를 모두 시험해 숫자가 읽히는 자리를 고른다.
    pool = [item for item in trace.get("candidates",[]) if item.get("score",0) >= SOFT_ACCEPT] or matches
    readable = []
    for match in sorted(pool,key=lambda item:item["score"],reverse=True):
        box,value,_ = _digits(frame,match,references)
        if box is not None and not any(abs(box[0]-other[0]) < box[2]/2 and abs(box[1]-other[1]) < box[3]/2
                                       for _,other,_ in readable):
            readable.append((match,box,value))
    if len(readable) != 1:
        trace.setdefault("rejection","ambiguous_candidates" if readable else "anchor_not_found")
        return None
    match,box,value = readable[0]
    trace.update(value=value,result=list(box),ornament=match,soft_ornament=True)
    return box


def _digits(frame,match,references):
    """장식 위치에서 가운데 숫자 칸과 값을 읽는다. (칸, 값, 거절 이유)"""
    x,y,_,_ = match["anchor"]
    scale = match["scale"]
    box = (x+round(8*scale),y+round(17*scale),round(28*scale),round(23*scale))
    if box[0]+box[2] > frame.shape[1] or box[1]+box[3] > frame.shape[0]:
        return None,None,"digit_region_clipped"
    value = read_dorcha(frame[box[1]:box[1]+box[3],box[0]:box[0]+box[2]],references=references)
    if value is None:
        return None,None,"unreadable_digits"
    return box,value,None
