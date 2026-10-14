"""Locate original paired page controls and verify the complete mirror grid."""

import cv2
import numpy as np

from .autofind_anchors import assets, candidates


def _grid_score(frame, box):
    x, y, w, h = box
    crop = cv2.resize(frame[y:y + h, x:x + w], (1168, 89), interpolation=cv2.INTER_AREA)
    edges = cv2.Canny(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), 50, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8)) > 0
    scores = []
    for bx in (0, 620):
        for ry in (0, 49):
            for gx in (0, 188, 376):
                for cell in range(4):
                    tile = edges[ry:ry + 40, bx + gx + cell * 44:bx + gx + cell * 44 + 40]
                    scores.append(float(np.mean(np.concatenate((tile[1, :], tile[-2, :], tile[:, 1], tile[:, -2])))))
    return scores


def locate_skillbar(frame, templates=None, diagnostics=None):
    trace = diagnostics if diagnostics is not None else {}
    matches = candidates(frame, assets("skillbar") if templates is None else templates, trace)
    valid = []
    for item in matches:
        x, y, _w, _h = item["anchor"]
        scale = item["scale"]
        box = (x - round(1182 * scale), y - round(12 * scale), round(1168 * scale), round(89 * scale))
        if (box[0] < 0 or box[1] < 0 or box[0] + box[2] > frame.shape[1]
                or box[1] + box[3] > frame.shape[0]):
            item["rejection"] = "source_grid_clipped"
            continue
        scores = _grid_score(frame, box)
        item.update(result=list(box), cell_border_scores=scores)
        if min(np.mean(np.reshape(scores, (12, 4)), axis=1)) < 0.60 or np.mean(scores) < 0.80:
            item["rejection"] = "unsupported_grid"
            continue
        valid.append(box)
    if len(valid) != 1:
        trace["rejection"] = "ambiguous_candidates" if len(valid) > 1 else "original_grid_not_found"
        return None
    trace["result"] = list(valid[0])
    return valid[0]
