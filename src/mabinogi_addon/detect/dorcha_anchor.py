"""Locate the shared ornament, then validate only Dorcha's inner word."""

from . import resource_anchor
from .dorcha_reader import read_dorcha, reference_assets, references_from_assets


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
    matches = resource_anchor.ornament_candidates(frame,templates,trace,cancelled)
    if len(matches) != 1:
        trace.setdefault("rejection","ambiguous_candidates" if matches else "anchor_not_found")
        return None
    match = matches[0]
    x,y,_,_ = match["anchor"]
    scale = match["scale"]
    box = (x+round(8*scale),y+round(17*scale),round(28*scale),round(23*scale))
    if box[0]+box[2] > frame.shape[1] or box[1]+box[3] > frame.shape[0]:
        trace["rejection"] = "digit_region_clipped"
        return None
    value = read_dorcha(frame[box[1]:box[1]+box[3],box[0]:box[0]+box[2]],references=references)
    if value is None:
        trace["rejection"] = "unreadable_digits"
        return None
    trace.update(value=value,result=list(box),ornament=match)
    return box
