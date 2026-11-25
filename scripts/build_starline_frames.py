"""Starline SD 시트 → 펫 프레임 PNG(캐릭터 알파, docs/characters/Starline.md '받은 그림'·'다시 그린 말하기·구석 확인').

실행: uv run python -m scripts.build_starline_frames
- 분리·축소·옅은 막 지우기·입만 바꾸기는 다른 캐릭터와 같은 도구. 서 있기(4면도 0번) 키 285.
- 크기: 후광·토끼귀 때문에 위 30% 폭(head_width)이 머리가 아님 → 시트마다 기준 그림 키로 배율 하나(기획 11-24):
  서 있는 시트는 키 중앙값 285, 착지는 끝(선) 그림, 앉기는 첫(선) 그림, 앉아 있기 = 앉기 끝 키, 일어나기 첫 장 = 앉기 끝 키,
  떨어지기(다리 굽힘)는 270. 얼굴 크기는 face_scale(서 있기 얼굴 창 matchTemplate)로 재서 status 표에 남김.
- 서 있기·걷기·말하기 반복은 B안 긴 체형 새 시트(사용자 11-24 '들었다 놓으면 작아짐' — 체형 통일).
- 말하기: 시작 0번 = 사이, 반복 6장(0 기준·1·2 입·3 강조·4 중간·5 깜빡임 — 입만 합성), 끝 = 시작 2장 거꾸로(1 → 0).
- 구석: 구석_앉기 1·2 → 구석_앉아있기 4(반복) → 일어나기 = 구석 7·8번 → 바로 서기(짧은 체형 서 있는 장은 안 씀).
- 마지막에 시트 색 맞추기(scripts/sheet_colors, 부위 scripts/color_parts 'Starline').
"""
from __future__ import annotations

import cv2
import numpy as np

from scripts.build_aria_frames import clean
from scripts.build_dare_frames import ROOT, _tight, imread, imwrite, scaled, split
from scripts.build_talk_frames import legs_swap, mouth_swap

SHEETS = ROOT / "docs/characters/assets/Starline/SD"
OUT = ROOT / "src/mabinogi_addon/assets/characters/Starline"
STAND_H = 285
FACE = (0.35, 0.53, 0.33, 0.77)   # 서 있기 얼굴 창(키·폭 비율: 위, 아래, 왼, 오른)
LEGS_Y = 350                       # 말하기_반복 원본 무릎 위(주머니 아래) — 그 아래 발·바지·망토 끝은 0번 것(QA 11-25)
MOUTH = (170, 205)                # 말하기_반복 0번 원본 입 대략 위치(B안 긴 체형, 11-24)


def sheet(name: str) -> list[np.ndarray]:
    return split(clean(imread(SHEETS / f"{name}.png", cv2.IMREAD_UNCHANGED)))


def _gray(frame: np.ndarray) -> np.ndarray:
    a = frame[..., 3:].astype(np.float32) / 255
    g = cv2.cvtColor(np.ascontiguousarray(frame[..., :3]), cv2.COLOR_BGR2GRAY).astype(np.float32)[..., None]
    return (g * a + 235 * (1 - a))[..., 0]


def face_crop(stand: np.ndarray) -> np.ndarray:
    h, w = stand.shape[:2]
    y0, y1, x0, x1 = FACE
    return _gray(stand)[int(h * y0):int(h * y1), int(w * x0):int(w * x1)]


def face_scale(face: np.ndarray, frame: np.ndarray) -> tuple[float, float]:
    """frame을 몇 배로 줄이면 서 있기 얼굴과 가장 잘 맞는지(배율, 맞음 점수)."""
    base = STAND_H / frame.shape[0]
    best = (base, -1.0)
    for k in np.linspace(0.7, 1.35, 66):
        s = base * k
        small = cv2.resize(_gray(frame), None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        if small.shape[0] < face.shape[0] or small.shape[1] < face.shape[1]:
            continue
        score = float(cv2.matchTemplate(small, face, cv2.TM_CCOEFF_NORMED).max())
        if score > best[1]:
            best = (s, score)
    return best


def sheet_scale(face: np.ndarray, frames: list[np.ndarray]) -> float:
    return float(np.median([face_scale(face, f)[0] for f in frames]))


def eye_gap(frame: np.ndarray) -> float | None:
    """노란 눈동자 두 개(키 22~60% 구간, 작은 덩어리) 사이 거리 — 얼굴 맞추기가 안 잡히는 기울어진 그림용."""
    h = frame.shape[0]
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[..., :3]), cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 0] >= 14) & (hsv[..., 0] <= 32) & (hsv[..., 1] > 110) & (hsv[..., 2] > 150)
         & (frame[..., 3] > 200)).astype(np.uint8)
    m[: int(h * 0.22)] = 0
    m[int(h * 0.6):] = 0
    count, _labels, stats, cents = cv2.connectedComponentsWithStats(m)
    blobs = [(stats[i, cv2.CC_STAT_AREA], cents[i]) for i in range(1, count) if 8 <= stats[i, cv2.CC_STAT_AREA] <= 150]
    pairs = []   # 두 눈 = 크기가 비슷하고(3배 안) 거의 가로로(높이 차 < 가로 35%) 20~70px 떨어진 쌍
    for i, (a1, c1) in enumerate(blobs):
        for a2, c2 in blobs[i + 1:]:
            dx, dy = abs(c1[0] - c2[0]), abs(c1[1] - c2[1])
            if 20 <= dx <= 70 and dy < 0.35 * dx and max(a1, a2) < 3 * min(a1, a2):
                pairs.append((a1 + a2, float(np.hypot(dx, dy))))
    return max(pairs)[1] if pairs else None


def head_ratio(face: np.ndarray, eyes: float, frame: np.ndarray) -> float | None:
    """서 있기 대비 이 그림의 머리 크기(1 = 같음). 얼굴 맞추기 점수 0.5 이상이면 그 배율, 아니면 눈 간격, 둘 다 없으면 None."""
    best = (1.0, -1.0)
    gray = _gray(frame)
    for k in np.linspace(0.75, 1.35, 61):
        small = cv2.resize(gray, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        if small.shape[0] < face.shape[0] or small.shape[1] < face.shape[1]:
            continue
        score = float(cv2.matchTemplate(small, face, cv2.TM_CCOEFF_NORMED).max())
        if score > best[1]:
            best = (float(k), score)
    ratio = 1.0 / best[0] if best[1] >= 0.5 else None
    if ratio is None:
        gap = eye_gap(frame)
        ratio = gap / eyes if gap else None
    return ratio if ratio is not None and 0.75 <= ratio <= 1.33 else None   # 범위 끝 = 못 잰 것


def build() -> dict[str, list[np.ndarray]]:
    """크기(사용자 11-24 B안 — 서 있기·걷기·말하기를 긴 체형으로 다시 그림): 서 있는 계열은 모두 긴 체형이라 시트별 기준 그림 키
    (서 있는 시트 키 중앙값 285·착지 끝 285). 서 있는 기준이 없는 떨어지기와 짧은 체형으로 남은 구석(앉기·앉아 있기·
    일어나기)은 머리 크기(head_ratio — 얼굴 맞추기, 안 되면 눈 간격)로 서 있기에 맞춤.
    구석 시트의 서 있는 장(앉기 0번·일어나기 끝)은 짧은 체형이라 안 씀 — 서기 → 앉기 1번, 일어나기 → 바로 서기."""
    out: dict[str, list[np.ndarray]] = {}
    stand = sheet("Starline_서있기")  # 0 씩 웃음(1번은 거의 같은 그림 — 안 씀)
    out["stand"] = [scaled(stand[0], STAND_H / stand[0].shape[0])]
    face = face_crop(out["stand"][0])
    eyes = eye_gap(out["stand"][0])

    def fit(frames, k):
        """배율 k로 줄인 그림들의 머리 크기 중앙값으로 k를 고쳐 다시 줄임."""
        ratios = [r for r in (head_ratio(face, eyes, scaled(f, k)) for f in frames) if r]
        c = float(np.median(ratios)) if ratios else 1.0
        return [scaled(f, k / c) for f in frames]

    def k_height(frames, ref=None, h=STAND_H):
        return h / (ref.shape[0] if ref is not None else float(np.median([f.shape[0] for f in frames])))

    def by_height(frames, ref=None):
        k = k_height(frames, ref)
        return [scaled(f, k) for f in frames]

    from scripts.silhouette import best_scale   # 크기는 같은 자세 장 실루엣을 서 있기에 맞춤(QA 11-25)
    flame = sheet("Starline_대기불꽃_v2")   # 기획 11-25 새 시트(머리·몸 비율을 서 있기와 맞춰 다시 그림)
    # 머리 크기 fit이 시트 전체를 약 7% 키웠음(QA 11-25 '불꽃 나올 때 커져') → 같은 자세인 0번 실루엣으로 시트 배율 하나
    k = k_height(flame)
    k *= best_scale(out["stand"][0], scaled(flame[0], k))
    out["flame"] = [scaled(f, k) for f in flame]
    out["walk"] = by_height(sheet("Starline_걷기"))
    out["drag"] = by_height(sheet("Starline_끌기"))
    fall = sheet("Starline_떨어지기")
    out["fall"] = fit(fall, k_height(fall, h=270))
    land = sheet("Starline_착지")
    out["land"] = by_height(land, land[2])           # 끝 = 서기
    pet = sheet("Starline_쓰다듬기")
    out["pet"] = fit(pet, k_height(pet))         # 키로는 머리 1.06~1.15 — 머리로 맞춤
    sneeze = sheet("Starline_재채기_v2")   # 기획 11-25 새 시트(머리·몸 비율을 서 있기와 맞춰 다시 그림)
    k = k_height(sneeze)
    k *= best_scale(out["stand"][0], scaled(sneeze[0], k))
    out["sneeze"] = [scaled(f, k) for f in sneeze]
    crouch = sheet("Starline_구석_앉기")[1:]          # 0번(짧은 체형 서 있는 장) 건너뜀
    out["crouch"] = fit(crouch, k_height(crouch, crouch[0], 0.9 * STAND_H))
    sit = sheet("Starline_구석_앉아있기")
    out["sit"] = fit(sit, k_height(sit, h=out["crouch"][-1].shape[0]))
    rise = sheet("Starline_구석")[7:9]               # 끝 서 있는 장(짧은 체형) 빼고 → 바로 서기
    out["rise"] = fit(rise, k_height(rise, rise[0], out["crouch"][-1].shape[0]))
    # 말하기 시작 v2(기획 11-25 — 예전 시트는 머리 1.14배·눈 흰자 넓음): 가이드 3칸(0 기준 서 있기 · 1 사이 · 2 손 든 자세)
    from scripts.build_dare_frames import guide_cells
    guide = guide_cells("Starline_말하기_시작_v2.png", 3, 1, SHEETS, (1800, 960), loose=True)
    start = guide[1:]                                 # 0 중간(사이) · 1 손 든 자세
    loop = sheet("Starline_말하기_반복")             # 0 기준 · 1·2 입 · 3 강조 · 4 중간 · 5 깜빡임
    base = loop[0]
    m1, _ = mouth_swap(base, loop[1], MOUTH)
    m2, _ = mouth_swap(base, loop[2], MOUTH)
    k = k_height(loop)
    # 반복 장(강조·깜빡임)은 발이 장마다 다르게 그려져 말하는 동안 발이 바뀜(QA 11-25) → 허리 아래는 0번 것으로
    emph, emph2, blink = (legs_swap(base, loop[i], LEGS_Y) for i in (3, 4, 5))
    for key, frame in zip(("base", "m1", "m2", "emph", "emph2", "blink"), (base, m1, m2, emph, emph2, blink)):
        out[f"talk_{key}"] = [scaled(frame, k)]
    k_start = STAND_H / guide[0].shape[0]   # 기준 칸(서 있기) 키 = 서 있기 키
    out["talk_mid"] = [scaled(start[0], k_start)]
    # 말하기 끝 시트가 없어 시작 2장을 거꾸로(기획 11-24): 손 든 자세 → 중간 → 서기
    out["talk_end1"] = [scaled(start[1], k_start)]
    out["talk_end2"] = [scaled(start[0], k_start)]
    from scripts.color_parts import PARTS
    from scripts.sheet_colors import harmonize
    groups = {("talk_m1", 0): ("talk_base", 0), ("talk_m2", 0): ("talk_base", 0)}
    out = harmonize(out, out["stand"][0], PARTS["Starline"], groups)
    # 재채기 시트 옷·망토 톤(QA 11-25 '색감이 달라짐', 새 시트도 1번이 L −1.6) — 중간 톤(옷·망토) 평균을 서 있기에 맞춤
    out["sneeze"] = [match_midtone(f, out["stand"][0]) for f in out["sneeze"]]
    # 말하기 두 시트(시작 = 탁하고 어두움, 반복 = 더 진함 — QA 11-25 '말할 때 색감이 달라져'): 어두운 톤·중간 톤 둘 다 서 있기에
    raw = {k: out[k][0] for k in ("talk_base", "talk_m1", "talk_m2")}
    # 불꽃 새 시트(11-25)도 같은 기준으로(중간 톤 b·채도가 조금 다름)
    for key in [k for k in out if k.startswith("talk_")] + ["flame"]:
        out[key] = [match_tones(f, out["stand"][0]) for f in out[key]]
    for key in ("talk_m1", "talk_m2"):   # 입만 다른 장은 입 밖을 base와 똑같이(입만 바꾸기 규칙 유지)
        same = (raw[key] == raw["talk_base"]).all(axis=-1)
        merged = out[key][0].copy()
        merged[same] = out["talk_base"][0][same]
        out[key] = [merged]
    return out


MID = (80, 170)   # 옷·망토 중간 톤(OpenCV 8비트 L) — 머리카락(밝음)·외곽선(검정)은 밖
DARK = (0, 79)    # 어두운 톤(망토 그림자·바지·외곽선)


def _midtone(frame: np.ndarray, band: tuple[int, int] = MID, gold_too: bool = False):
    lab = cv2.cvtColor(np.ascontiguousarray(frame[..., :3]), cv2.COLOR_BGR2LAB).astype(np.float32)
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[..., :3]), cv2.COLOR_BGR2HSV)
    gold = (hsv[..., 0] >= 12) & (hsv[..., 0] <= 32) & (hsv[..., 1] > 80)   # 후광·장신구는 그대로
    if gold_too:   # 말하기: 측정(불투명 전체)과 같은 픽셀로 맞춤 — 금색 장신구도 두 시트가 같이 다름
        gold[:] = False
    sel = (frame[..., 3] > 200) & (lab[..., 0] >= band[0]) & (lab[..., 0] <= band[1]) & ~gold
    return lab, sel


def match_midtone(frame: np.ndarray, stand: np.ndarray, band: tuple[int, int] = MID, gold_too: bool = False) -> np.ndarray:
    """중간 톤 픽셀(옷·망토)의 Lab 평균을 서 있기에 맞춤 — 그 픽셀만 바꿈(머리카락·피부 밝은 톤·후광·외곽선은 그대로)."""
    ref_lab, ref_sel = _midtone(stand, band, gold_too)
    out = frame.copy()
    for _ in range(4):   # 옮긴 픽셀이 중간 톤 경계를 넘나들어 한 번에 안 맞음 — 몇 번 되풀이
        lab, sel = _midtone(out, band, gold_too)
        if sel.sum() < 200 or ref_sel.sum() < 200:
            return out
        diff = ref_lab[ref_sel].mean(0) - lab[sel].mean(0)
        if np.abs(diff).max() < 0.3:
            break
        lab[sel] = np.clip(lab[sel] + diff, 0, 255)
        fixed = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)
        out[sel, :3] = fixed[sel]
    return out


EXPECTED = {"sneeze": 6, "stand": 1, "flame": 4, "walk": 6, "drag": 4, "fall": 1, "land": 3, "pet": 6, "crouch": 2, "sit": 4,
            "rise": 2, **{f"talk_{k}": 1 for k in ("base", "m1", "m2", "emph", "emph2", "blink", "mid", "end1", "end2")}}


def card() -> np.ndarray:
    """가로형 상반신(1355×1160) → 손 든 포즈가 다 보이게(기획 11-25 '손 전체 보이게'): x0 = 100, 폭 999
    (= 1160 × 224 / 260 — 카드 224×280에서 머리 위 20px을 뺀 260에 높이를 꽉 맞춤). 손·반지·금 팔찌가 보이고 얼굴은 오른쪽.
    이미 카드 비율이라 카드 그리기에서 양옆을 다시 자르지 않음(character_tab.CARD_FIT_HEIGHT)."""
    art = imread(ROOT / "docs/characters/assets/Starline/Starline_상반신.png", cv2.IMREAD_UNCHANGED)
    art = art[:, CARD_X0:CARD_X0 + CARD_CW]
    return scaled(art, 480 / art.shape[0])


CARD_X0, CARD_CW = 100, 999


def match_tones(frame: np.ndarray, stand: np.ndarray) -> np.ndarray:
    """채도 → 어두운 톤 → 중간 톤 Lab을 서 있기에(서로 조금씩 밀어내서 여섯 번 되풀이)."""
    for _ in range(6):
        frame = match_midtone(match_midtone(match_saturation(frame, stand), stand, DARK, True), stand, MID, True)
    return frame


def match_saturation(frame: np.ndarray, stand: np.ndarray) -> np.ndarray:
    """채도(HSV S, 불투명 픽셀 평균)를 서 있기에 — 옷·망토·그림자(L ≤ 170)만 바꿈(머리카락 밝은 톤은 시트 색 맞추기가 맡음)."""
    def stats(img):
        hsv = cv2.cvtColor(np.ascontiguousarray(img[..., :3]), cv2.COLOR_BGR2HSV)
        _lab, sel = _midtone(img, (0, MID[1]), True)
        return hsv, img[..., 3] > 200, sel

    ref_hsv, ref_a, _ = stats(stand)
    target = ref_hsv[ref_a][:, 1].astype(np.float32).mean()
    out = frame.copy()
    for _ in range(4):
        hsv, opaque, sel = stats(out)
        diff = target - hsv[opaque][:, 1].astype(np.float32).mean()
        if abs(diff) < 0.5 or sel.sum() < 200:
            break
        s = hsv[..., 1].astype(np.float32)
        s[sel] = np.clip(s[sel] + diff * opaque.sum() / sel.sum(), 0, 255)
        hsv[..., 1] = s.astype(np.uint8)
        fixed = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        out[sel, :3] = fixed[sel]
    return out


def main() -> None:
    frames = build()
    for key, count in EXPECTED.items():
        if len(frames[key]) != count:
            raise SystemExit(f"{key}: 프레임 {len(frames[key])}개(기대 {count}) — 시트가 바뀌었나요?")
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        if old.name != "frame.png":   # 카드 테두리(build_card_frames)는 남김
            old.unlink()
    for key, items in frames.items():
        for i, frame in enumerate(items):
            imwrite(OUT / f"{key}_{i}.png", frame)
            print(f"{key}_{i}: {frame.shape[1]}×{frame.shape[0]}")
    imwrite(OUT / "card.png", card())


if __name__ == "__main__":
    main()
