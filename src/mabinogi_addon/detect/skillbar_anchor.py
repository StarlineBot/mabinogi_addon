"""Locate original paired page controls and verify the complete mirror grid."""

import cv2
import numpy as np

from .autofind_anchors import assets, candidates, native_band_candidates


def _grid_score(frame, box):
    crop = compose(frame, box)
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


# ---- 작은 인터페이스(게임 인터페이스 크기를 줄인 화면, 테스터 11-26 image (34)) ----------------------------------
# 아이콘·간격은 배율 s(≈0.77)로 줄지만 ◀n▶ 화살표는 원래 픽셀 그대로이고 두 줄 사이만 좁아진다(기본 49 → 37).
# 둘째 단축바는 다른 UI(보라 원)에 밀려 기본 자리(620·s)가 아닐 수 있다 → 상자 폭에 실제 거리를 담는다:
# 상자 = (x, y, (gap + 548)·s, 89·s), 배율 s = 높이/89, 둘째 단축바 시작 = gap·s(기본 gap 620 → 폭 1168·s).
BLOCK_W = 548          # 한 단축바(4칸 × 3묶음) 폭(배율 1.0)
STD_GAP = 620          # 기본 배치의 둘째 단축바 시작
SMALL_CUTS = range(4, 21)   # 화살표 두 줄 사이를 줄인 양(px) — 작은 인터페이스 후보


def layout(box) -> tuple[float, float]:
    """단축바 상자 → (배율 s, 둘째 단축바 시작 gap — 배율 1.0 단위). 기본 배치는 (w/1168, 620)."""
    x, y, w, h = box
    s = h / 89.0
    gap = w / s - BLOCK_W if s > 0 else STD_GAP
    tol = 2 + 1168 * 0.6 / max(h, 1)  # 높이 반올림(±0.5px)이 폭 환산에 주는 오차(배율 0.75 → ±12)
    return s, (STD_GAP if abs(gap - STD_GAP) <= tol else gap)


def split_layout(box) -> bool:
    """둘째 단축바가 기본 자리(620·s)보다 오른쪽에 떨어진 상자(작은 인터페이스)인가."""
    if box is None or len(box) != 4 or box[3] <= 0:
        return False
    return layout(box)[1] > STD_GAP


def source_box_of(anchor) -> tuple[int, int, int, int] | None:
    """저장된 단축바 자리 {x, y[, w, h]} → 원본 상자(논리 좌표). w·h는 작은 인터페이스일 때만 저장된다."""
    if not isinstance(anchor, dict) or not all(isinstance(anchor.get(k), (int, float)) for k in ("x", "y")):
        return None
    w, h = anchor.get("w"), anchor.get("h")
    if isinstance(w, (int, float)) and isinstance(h, (int, float)) and split_layout((0, 0, w, h)):
        return int(anchor["x"]), int(anchor["y"]), int(w), int(h)
    return int(anchor["x"]), int(anchor["y"]), 1168, 89


def anchor_of(box) -> dict:
    """원본 상자 → 저장할 단축바 자리. 기본 배치는 예전처럼 {x, y}만(크기는 1168×89 고정)."""
    x, y, w, h = (int(v) for v in box)
    return {"x": x, "y": y, "w": w, "h": h} if split_layout(box) else {"x": x, "y": y}


def compose(frame, box):
    """상자 안 단축바를 기본 배치 원본(1168×89)으로 — 둘째 단축바가 떨어져 있으면 두 블록을 잘라 붙인다."""
    x, y, w, h = (int(round(v)) for v in box)
    s, gap = layout(box)
    if gap == STD_GAP:
        return cv2.resize(frame[y:y + h, x:x + w], (1168, 89), interpolation=cv2.INTER_AREA)
    out = np.zeros((89, 1168, 3), np.uint8)
    for src_x, dst_x in ((0, 0), (gap, STD_GAP)):
        x0 = x + int(round(src_x * s))
        part = frame[y:y + h, x0:x0 + int(round(BLOCK_W * s))]
        if part.size:
            out[:, dst_x:dst_x + BLOCK_W] = cv2.resize(part, (BLOCK_W, 89), interpolation=cv2.INTER_AREA)
    return out


def _cell_map(edges_cum_rows, edges_cum_cols, n):
    """모든 (y, x)에서 n×n 칸 테두리 점수(_grid_score와 같은 규칙: 위·아래·왼·오른 안쪽 1줄 평균)."""
    rows, cols = edges_cum_rows, edges_cum_cols
    h, w = rows.shape[0], rows.shape[1] - 1
    if h < n or w < n:
        return None
    hh, ww = h - n + 1, w - n + 1

    def hline(dy):  # y+dy 줄, x..x+n
        r = rows[dy:dy + hh]
        return r[:, n:n + ww] - r[:, 0:ww]

    def vline(dx):  # x+dx 열, y..y+n
        c = cols[:, dx:dx + ww]
        return c[n:n + hh] - c[0:hh]
    return (hline(1) + hline(n - 2) + vline(1) + vline(n - 2)) / (4.0 * n)


_SMALL_CELLS = [(ry, gx + c * 44) for ry in (0, 49) for gx in (0, 188, 376) for c in range(4)]


def _block_maps(edges, s):
    """배율 s 한 단축바(24칸) — 모든 (y, x) 시작점의 칸 평균 점수 지도와 묶음(6) 최소 점수 지도."""
    e = edges.astype(np.float32)
    rows = np.pad(np.cumsum(e, axis=1), ((0, 0), (1, 0)))
    cols = np.pad(np.cumsum(e, axis=0), ((1, 0), (0, 0)))
    cells = _cell_map(rows, cols, max(3, int(round(40 * s))))
    if cells is None:
        return None, None
    offs = [(int(round(ry * s)), int(round(cx * s))) for ry, cx in _SMALL_CELLS]
    hh = cells.shape[0] - max(o[0] for o in offs)
    ww = cells.shape[1] - max(o[1] for o in offs)
    if hh <= 0 or ww <= 0:
        return None, None
    groups = []
    for g in range(6):
        acc = np.zeros((hh, ww), np.float32)
        for dy, dx in offs[g * 4:g * 4 + 4]:
            acc += cells[dy:dy + hh, dx:dx + ww]
        groups.append(acc / 4)
    groups = np.stack(groups)
    return groups.mean(axis=0), groups.min(axis=0)


def _small_ui(frame, templates, trace):
    """작은 인터페이스: 줄 사이를 줄인 화살표를 위쪽 띠 원본에서 찾고, 그 옆 단축바 격자(배율 s)와 떨어진 둘째 단축바를 찾는다."""
    anchor, mask = templates.get("anchor"), templates.get("mask")
    if anchor is None or mask is None or frame is None or getattr(frame, "ndim", 0) != 3:
        return None
    band = frame[:min(frame.shape[0], BAND_HEIGHT)]
    if band.shape[0] < anchor.shape[0] or band.shape[1] < anchor.shape[1]:
        return None
    # 위 화살표(◀n▶ 한 줄)만 먼저 찾고, 봉우리마다 줄 사이를 줄인 전체 화살표로 확인한다(전체 띠를 17번 비교하면 2초 넘게 걸림).
    top = np.nan_to_num(cv2.matchTemplate(band, anchor[:20], cv2.TM_CCORR_NORMED, mask=mask[:20]),
                        nan=0, posinf=0, neginf=0)
    hits = []
    for _ in range(6):
        _, score, _, (px, py) = cv2.minMaxLoc(top)
        if score < 0.97:
            break
        top[max(0, py - 10):py + 11, max(0, px - 20):px + 21] = 0
        crop = band[max(0, py - 2):py + anchor.shape[0] + 2, max(0, px - 2):px + anchor.shape[1] + 2]
        for cut in SMALL_CUTS:
            a = np.vstack([anchor[:20], anchor[20 + cut:]])
            m = np.vstack([mask[:20], mask[20 + cut:]])
            if crop.shape[0] < a.shape[0] or crop.shape[1] < a.shape[1]:
                continue
            r = np.nan_to_num(cv2.matchTemplate(crop, a, cv2.TM_CCORR_NORMED, mask=m), nan=0, posinf=0, neginf=0)
            _, sc, _, (cx, cy) = cv2.minMaxLoc(r)
            if sc >= 0.985:
                hits.append((float(sc), cut, max(0, px - 2) + cx, max(0, py - 2) + cy))
    trace["small_ui_anchors"] = [list(h) for h in hits]
    for _score, cut, ax, ay in sorted(hits, reverse=True)[:3]:
        top_y = max(0, ay - 40)
        strip = frame[top_y:min(frame.shape[0], ay + 120)]
        edges = cv2.dilate(cv2.Canny(cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY), 50, 120), np.ones((3, 3), np.uint8)) > 0
        s0 = (49 - cut) / 49.0
        best = None
        for s in np.arange(s0 - 0.03, s0 + 0.031, 0.005):
            mean, low = _block_maps(edges, s)
            if mean is None:
                continue
            # 첫 단축바: 화살표 왼쪽에 붙어 있다(블록 끝 ≈ 화살표 왼쪽)
            x_lo, x_hi = int(round(ax - BLOCK_W * s)) - 14, int(round(ax - BLOCK_W * s)) + 15
            y_lo, y_hi = ay - top_y - 14, ay - top_y + 3
            x_lo, y_lo = max(0, x_lo), max(0, y_lo)
            win = mean[y_lo:y_hi, x_lo:x_hi]
            if win.size == 0:
                continue
            iy, ix = np.unravel_index(int(np.argmax(win)), win.shape)
            if best is None or win[iy, ix] > best[0]:
                best = (float(win[iy, ix]), x_lo + ix, y_lo + iy, float(s), mean, low)
        if best is None:
            continue
        score1, x1, y1, s, mean, low = best
        if not (low[y1, x1] >= 0.60 and score1 >= 0.80):
            continue
        # 둘째 단축바: 같은 줄 오른쪽 어딘가
        start = int(x1 + BLOCK_W * s + 20 * s)
        row_mean, row_low = mean[y1, start:], low[y1, start:]
        if row_mean.size == 0:
            trace["small_ui_rejection"] = "second_block_not_found"
            continue
        i2 = int(np.argmax(row_mean))
        if not (row_low[i2] >= 0.60 and row_mean[i2] >= 0.80):
            trace["small_ui_rejection"] = "second_block_not_found"
            continue
        gap = (start + i2 - x1) / s
        box = (int(x1), int(y1 + top_y), int(round((gap + BLOCK_W) * s)), int(round(89 * s)))
        trace.update(small_ui={"scale": round(s, 3), "gap": round(float(gap), 1), "first": round(score1, 3),
                               "second": round(float(row_mean[i2]), 3)})
        return box
    return None


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
    # 1.5단계: 작은 인터페이스(화살표는 원래 크기, 아이콘만 작음 — 둘째 단축바가 떨어져 있을 수 있음)
    small = _small_ui(frame, templates, trace)
    if small is not None:
        trace.update(stage="small_ui", result=list(small))
        return small
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
