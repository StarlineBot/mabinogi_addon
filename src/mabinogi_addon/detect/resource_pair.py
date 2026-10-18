"""One captured input; independent validators, paired only at the same ornament."""

from . import dorcha_anchor, tuarim_anchor


def assets():
    return {f"{key}_{name}":image for key,loader in
            (("dorcha",dorcha_anchor.assets),("tuarim",tuarim_anchor.assets))
            for name,image in loader().items()}


def locate_resources(frame, templates, trace,cancelled=None):
    regions = {}
    for key,detector in (("dorcha",dorcha_anchor.locate_dorcha),("tuarim",tuarim_anchor.locate_tuarim)):
        if cancelled is not None and cancelled():
            trace["rejection"] = "cancelled"
            return None
        model = {name.removeprefix(key+'_'):image for name,image in templates.items() if name.startswith(key+'_')}
        detail = {}
        box = detector(frame,model,detail)
        trace[key] = detail
        if detail.get("rejection") == "ambiguous_candidates":
            trace["rejection"] = "ambiguous_candidates"
            return None
        if box is not None:
            regions[key] = list(box)
    if len(regions) == 2:
        d,t = regions["dorcha"],regions["tuarim"]
        ds,ts = d[2]/28,t[2]/42
        if (abs(ds-ts) > .04 or abs(d[0]-round(8*ds)-t[0]+round(34*ts)) > 2
                or abs(d[1]-round(17*ds)-t[1]+round(45*ts)) > 2):
            trace["rejection"] = "different_ornaments"
            return None
    trace["regions"] = regions
    if not regions:
        trace["rejection"] = "no_valid_resource"
        return None
    left = min(box[0] for box in regions.values())
    top = min(box[1] for box in regions.values())
    right = max(box[0]+box[2] for box in regions.values())
    bottom = max(box[1]+box[3] for box in regions.values())
    return left,top,right-left,bottom-top
