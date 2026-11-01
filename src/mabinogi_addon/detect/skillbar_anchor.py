"""Locate original paired page controls and verify the complete mirror grid."""

import cv2
import numpy as np

from .autofind_anchors import assets, candidates, native_band_candidates


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


# 단축바(원본 격자)는 해상도와 무관하게 1168×89(배율 1.0)이고 화면 위쪽에 있다 — 위쪽 띠를 원본 그대로 먼저 본다.
BAND_HEIGHT = 400
# 격자 왼쪽이 화면 밖으로 몇 px 나가는 것(4K에서 화살표가 두 블록 사이일 때 -7 등)은 0으로 맞춘다.
CLIP_TOLERANCE = 12


def _uhd_variant(templates):
    if any(key.endswith("_uhd") for key in templates):
        return {key.removesuffix("_uhd"): image for key, image in templates.items() if key.endswith("_uhd")}
    return _uhd_assets()


def _merge(matches, found):
    return matches + [item for item in found if not any(
        abs(item["anchor"][0] - other["anchor"][0]) < item["anchor"][2] / 2
        and abs(item["anchor"][1] - other["anchor"][1]) < item["anchor"][3] / 2 for other in matches)]


NUDGE = 6  # 격자 위치 미세 조정 범위(px, 배율 1.0)


# 12묶음(블록 2 × 줄 2 × 묶음 3)의 원본 기준 위치 (x, y) — _grid_score와 같은 순서
_GROUPS = [(bx + gx, ry) for bx in (0, 620) for ry in (0, 49) for gx in (0, 188, 376)]


def _grid_ok(scores, strict: bool = False, frame=None, box=None) -> bool:
    """칸 테두리가 격자로 보이는지. 12묶음 중 최대 2묶음은 툴팁·전투 효과에 가려도 된다
    (2026-10-09 유튜브 알림·보스전 효과가 둘째 블록 일부를 가린 장). 나머지는 모두 0.6 이상, 전체 평균 0.85 이상.
    가린 묶음은 내용(무늬)이 있어야 한다 — 단색으로 비어 있으면 칸이 없는 격자로 보고 거부한다."""
    means = np.mean(np.reshape(scores, (12, 4)), axis=1)
    mean = float(np.mean(scores))
    if means.min() >= 0.60 and mean >= 0.80:
        return True  # 예전 기준(가림 없음)
    if strict or frame is None or box is None:
        return False
    if not (np.sort(means)[2] >= 0.60 and mean >= 0.85):
        return False
    x, y, w, h = box
    sx, sy = w / 1168, h / 89
    for index in np.flatnonzero(means < 0.60):
        gx, gy = _GROUPS[index]
        part = frame[y + round(gy * sy):y + round((gy + 40) * sy), x + round(gx * sx):x + round((gx + 172) * sx)]
        if part.size == 0 or float(np.std(cv2.cvtColor(part, cv2.COLOR_BGR2GRAY))) < 8.0:
            return False
    return True


def _nudge(frame, box):
    """box 주변 ±NUDGE px에서 격자 점수가 가장 높은 위치."""
    x0, y0, w, h = box
    best = (-1.0, box, None)
    for dy in range(-NUDGE, NUDGE + 1):
        for dx in range(-NUDGE, NUDGE + 1):
            x, y = x0 + dx, y0 + dy
            if x < 0 or y < 0 or x + w > frame.shape[1] or y + h > frame.shape[0]:
                continue
            scores = _grid_score(frame, (x, y, w, h))
            mean = float(np.mean(scores))
            if mean > best[0]:
                best = (mean, (x, y, w, h), scores)
    if best[2] is None:
        return box, _grid_score(frame, box)
    return best[1], best[2]


def _verify(frame, matches):
    """후보 화살표마다 격자 위치(두 블록 오른쪽/사이)를 확인. 반환: [(평균 점수, box)]."""
    valid = []
    for item in matches:
        x, y, _w, _h = item["anchor"]
        scale = item["scale"]
        for offset in _GRID_OFFSETS:
            box = [x - round(offset * scale), y - round(12 * scale), round(1168 * scale), round(89 * scale)]
            tol = round(CLIP_TOLERANCE * scale)
            if -tol <= box[0] < 0:
                box[0] = 0
            if -tol <= box[1] < 0:
                box[1] = 0
            if (box[0] < 0 or box[1] < 0 or box[0] + box[2] > frame.shape[1]
                    or box[1] + box[3] > frame.shape[0]):
                item.setdefault("rejection", "source_grid_clipped")
                continue
            box = tuple(box)
            scores = _grid_score(frame, box)
            if not _grid_ok(scores, strict=True):
                # 1) 화면마다 격자가 화살표 기준에서 몇 px 어긋나는 경우(4K 123333·dorcha +4,+2) — 주변에서 엄격 기준으로.
                # 2) 그래도 아니면 원래 자리에서만 가림 허용(툴팁·효과). 옮긴 자리는 가림 허용으로 받지 않는다
                #    (어긋난 자리·빈 칸을 '가려졌다'로 받아들이지 않게).
                nudged, nudged_scores = _nudge(frame, box)
                if _grid_ok(nudged_scores, strict=True):
                    box, scores = nudged, nudged_scores
            if not _grid_ok(scores, frame=frame, box=box):
                item.update(result=list(box), cell_border_scores=scores, rejection="unsupported_grid")
                continue
            item.update(result=list(box), cell_border_scores=scores, rejection=None)
            valid.append((float(np.mean(scores)), box))
            break
    unique = []
    for score, box in sorted(valid, key=lambda v: -v[0]):
        if not any(abs(box[0] - b[0]) < 20 and abs(box[1] - b[1]) < 20 for _, b in unique):
            unique.append((score, box))
    return unique


def locate_skillbar(frame, templates=None, diagnostics=None):
    trace = diagnostics if diagnostics is not None else {}
    templates = assets("skillbar") if templates is None else templates
    uhd = _uhd_variant(templates)
    # 1단계: 위쪽 띠·원본 해상도·배율 1.0(빠르고 축소 손실 없음)
    if frame is not None and getattr(frame, "ndim", 0) == 3:
        band = native_band_candidates(frame, templates, trace, BAND_HEIGHT)
        if uhd:
            uhd_trace = {}
            band = _merge(band, native_band_candidates(frame, uhd, uhd_trace, BAND_HEIGHT))
            trace["band_uhd_candidates"] = uhd_trace.get("band_candidates", [])
        trace.setdefault("candidates", []).extend(trace.get("band_candidates", []))
        if uhd:
            trace["uhd_candidates"] = list(trace.get("band_uhd_candidates", []))
        valid = _verify(frame, band)
        if len(valid) == 1:
            trace.update(stage="native_band", result=list(valid[0][1]))
            return valid[0][1]
        trace["band_valid"] = [list(b) for _, b in valid]
    # 2단계: 기존 전체 탐색(축소 → 원본 정밀). 배율마다 봉우리 10개까지 확인한다.
    matches = candidates(frame, templates, trace, peaks=10)
    if trace.get("rejection") in ("invalid_frame", "invalid_mask"):
        return None
    # 4K에서는 화살표가 회색·검은 테두리 거의 없이 그려져 기본 앵커와 0.91~0.93 — 변형으로 한 번 더 찾는다
    if uhd:
        uhd_trace = {}
        found = candidates(frame, uhd, uhd_trace, peaks=10)
        trace["uhd_candidates"] = uhd_trace.get("candidates", [])
        matches = _merge(matches, found)
    valid = _verify(frame, matches)
    if len(valid) != 1:
        trace["rejection"] = "ambiguous_candidates" if len(valid) > 1 else "original_grid_not_found"
        return None
    trace.update(stage="full_search", result=list(valid[0][1]))
    return valid[0][1]
