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
from scripts.build_talk_frames import mouth_swap

SHEETS = ROOT / "docs/characters/assets/Starline/SD"
OUT = ROOT / "src/mabinogi_addon/assets/characters/Starline"
STAND_H = 285
FACE = (0.35, 0.53, 0.33, 0.77)   # 서 있기 얼굴 창(키·폭 비율: 위, 아래, 왼, 오른)
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

    flame = sheet("Starline_대기불꽃")
    out["flame"] = fit(flame, k_height(flame))   # 키로는 머리 0.93~0.96 — 머리로 맞춤
    out["walk"] = by_height(sheet("Starline_걷기"))
    out["drag"] = by_height(sheet("Starline_끌기"))
    fall = sheet("Starline_떨어지기")
    out["fall"] = fit(fall, k_height(fall, h=270))
    land = sheet("Starline_착지")
    out["land"] = by_height(land, land[2])           # 끝 = 서기
    pet = sheet("Starline_쓰다듬기")
    out["pet"] = fit(pet, k_height(pet))         # 키로는 머리 1.06~1.15 — 머리로 맞춤
    sneeze = sheet("스타라인의 재채기 애니메이션 스프라이트 시트")   # 기획 11-25 기본 동작(3~6분에 한 번)
    from scripts.silhouette import best_scale   # 크기는 같은 자세인 0번 실루엣을 서 있기에 맞춤(QA 11-25)
    k = k_height(sneeze)
    k *= best_scale(out["stand"][0], scaled(sneeze[0], k))
    out["sneeze"] = [scaled(f, k) for f in sneeze]
    crouch = sheet("Starline_구석_앉기")[1:]          # 0번(짧은 체형 서 있는 장) 건너뜀
    out["crouch"] = fit(crouch, k_height(crouch, crouch[0], 0.9 * STAND_H))
    sit = sheet("Starline_구석_앉아있기")
    out["sit"] = fit(sit, k_height(sit, h=out["crouch"][-1].shape[0]))
    rise = sheet("Starline_구석")[7:9]               # 끝 서 있는 장(짧은 체형) 빼고 → 바로 서기
    out["rise"] = fit(rise, k_height(rise, rise[0], out["crouch"][-1].shape[0]))
    start = sheet("Starline_말하기_시작")            # 0 중간(손 허리) · 1 손 든 자세
    loop = sheet("Starline_말하기_반복")             # 0 기준 · 1·2 입 · 3 강조 · 4 중간 · 5 깜빡임
    base = loop[0]
    m1, _ = mouth_swap(base, loop[1], MOUTH)
    m2, _ = mouth_swap(base, loop[2], MOUTH)
    k = k_height(loop)
    for key, frame in zip(("base", "m1", "m2", "emph", "emph2", "blink"), (base, m1, m2, loop[3], loop[4], loop[5])):
        out[f"talk_{key}"] = [scaled(frame, k)]
    k_start = k_height(start)
    out["talk_mid"] = [scaled(start[0], k_start)]
    # 말하기 끝 시트가 없어 시작 2장을 거꾸로(기획 11-24): 손 든 자세 → 중간 → 서기
    out["talk_end1"] = [scaled(start[1], k_start)]
    out["talk_end2"] = [scaled(start[0], k_start)]
    from scripts.color_parts import PARTS
    from scripts.sheet_colors import harmonize
    groups = {("talk_m1", 0): ("talk_base", 0), ("talk_m2", 0): ("talk_base", 0)}
    return harmonize(out, out["stand"][0], PARTS["Starline"], groups)


EXPECTED = {"sneeze": 6, "stand": 1, "flame": 4, "walk": 6, "drag": 4, "fall": 1, "land": 3, "pet": 6, "crouch": 2, "sit": 4,
            "rise": 2, **{f"talk_{k}": 1 for k in ("base", "m1", "m2", "emph", "emph2", "blink", "mid", "end1", "end2")}}


def card() -> np.ndarray:
    """가로형 상반신(1355×1160) → 얼굴(위 45% 알파 무게중심 x) 가운데로 다른 카드와 같은 세로 비율(1199:1312)."""
    art = imread(ROOT / "docs/characters/assets/Starline/Starline_상반신.png", cv2.IMREAD_UNCHANGED)
    h, w = art.shape[:2]
    top = art[: int(h * 0.45), :, 3] > 40
    cx = float(np.where(top)[1].mean())
    cw = int(round(h * 1199 / 1312))
    x0 = int(min(max(0, cx - cw / 2), w - cw))
    art = _tight(art[:, x0:x0 + cw])
    return scaled(art, 480 / art.shape[0])


def main() -> None:
    frames = build()
    for key, count in EXPECTED.items():
        if len(frames[key]) != count:
            raise SystemExit(f"{key}: 프레임 {len(frames[key])}개(기대 {count}) — 시트가 바뀌었나요?")
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    for key, items in frames.items():
        for i, frame in enumerate(items):
            imwrite(OUT / f"{key}_{i}.png", frame)
            print(f"{key}_{i}: {frame.shape[1]}×{frame.shape[0]}")
    imwrite(OUT / "card.png", card())


if __name__ == "__main__":
    main()
