"""Locate the movable Tuarim decoration, not its changing inner number."""

from .autofind_anchors import assets, candidates


def locate_tuarim(frame, templates=None, diagnostics=None):
    trace = diagnostics if diagnostics is not None else {}
    matches = candidates(frame, assets("tuarim") if templates is None else templates, trace)
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
