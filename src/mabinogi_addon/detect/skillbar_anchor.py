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


# 화살표(앵커) 왼쪽 끝 → 원본 격자 왼쪽 끝 거리(기준 배율). 화살표는 두 블록 오른쪽(창 모드 등) 또는
# 두 블록 사이(0.30.4 4K 화면: 첫 블록 바로 뒤, 둘째 블록은 620에서 그대로)에 놓인다.
_GRID_OFFSETS = (1182, 1182 - 620)


def _uhd_assets():
    """4K 화살표 앵커 변형(scripts/build_skillbar_uhd_anchor.py). 없으면 빈 dict."""
    from pathlib import Path

    import cv2

    from .. import image_io
    root = Path(__file__).parent / "templates/autofind"
    anchor = image_io.imread(root / "skillbar_anchor_uhd.png", cv2.IMREAD_COLOR)
    mask = image_io.imread(root / "skillbar_mask_uhd.png", cv2.IMREAD_GRAYSCALE)
    return {"anchor": anchor, "mask": mask} if anchor is not None and mask is not None else {}


def locate_skillbar(frame, templates=None, diagnostics=None):
    trace = diagnostics if diagnostics is not None else {}
    templates = assets("skillbar") if templates is None else templates
    matches = candidates(frame, templates, trace)
    # 4K에서는 화살표가 회색·검은 테두리 거의 없이 그려져 기본 앵커와 0.91~0.93 — 변형으로 한 번 더 찾는다
    uhd = {key.removesuffix("_uhd"): image for key, image in templates.items() if key.endswith("_uhd")} \
        if any(key.endswith("_uhd") for key in templates) else _uhd_assets()
    if uhd:
        uhd_trace = {}
        found = candidates(frame, uhd, uhd_trace)
        trace["uhd_candidates"] = uhd_trace.get("candidates", [])
        matches += [item for item in found if not any(
            abs(item["anchor"][0] - other["anchor"][0]) < item["anchor"][2] / 2
            and abs(item["anchor"][1] - other["anchor"][1]) < item["anchor"][3] / 2 for other in matches)]
    valid = []
    for item in matches:
        x, y, _w, _h = item["anchor"]
        scale = item["scale"]
        for offset in _GRID_OFFSETS:
            box = (x - round(offset * scale), y - round(12 * scale), round(1168 * scale), round(89 * scale))
            if (box[0] < 0 or box[1] < 0 or box[0] + box[2] > frame.shape[1]
                    or box[1] + box[3] > frame.shape[0]):
                item.setdefault("rejection", "source_grid_clipped")
                continue
            scores = _grid_score(frame, box)
            if min(np.mean(np.reshape(scores, (12, 4)), axis=1)) < 0.60 or np.mean(scores) < 0.80:
                item.update(result=list(box), cell_border_scores=scores, rejection="unsupported_grid")
                continue
            item.update(result=list(box), cell_border_scores=scores, rejection=None)
            valid.append(box)
            break
    if len(valid) != 1:
        trace["rejection"] = "ambiguous_candidates" if len(valid) > 1 else "original_grid_not_found"
        return None
    trace["result"] = list(valid[0])
    return valid[0]
