"""레나 SD 시트 → 펫 프레임 PNG(캐릭터 알파, docs/characters/레나.md '받은 그림' 표).

실행: uv run python -m scripts.build_lena_frames
- 분리·축소·옅은 막 지우기·입만 바꾸기는 다른 캐릭터와 같은 도구. 서 있는 키 285(시트마다 머리/키 비율이 0.49~0.52로 고름).
- 쓰다듬기 시트만 머리가 110%라 머리 폭을 서 있기에 맞춤(이안과 같은 방식).
- 떨어지기는 1번 한 장만(사용자 11-24), 배율은 같은 크기 시트 '말하기_시작'.
- 부분 합성(몸이 장마다 다시 그려져 꿈틀거림 — 측정 9~20%):
  · 쓰다듬기 3·4번: 2번 그림 위에 얼굴 타원만(가운데·키 42% 높이, 반지름 폭 22%·키 11%, phaseCorrelate 맞춤, 가장자리 σ6)
  · 앉아 있기 1·2·3번: 0번 그림 위에 0번과 다른 가장 큰 덩어리(발끝·얼굴)만 팽창·흐림 마스크로
- 말하기 끝: '말하기_한장모음' 오른쪽 두 장(끝 사이·서기와 같은 자세).
- 시트 색 맞추기(사용자 11-24 '쓰다듬을 때 머리색이 달라짐' 등): 마지막에 공통 단계(scripts/sheet_colors, 부위는
  scripts/color_parts '레나')로 머리·피부를 서 있기 색에 맞춤. 부분 합성(쓰다듬기 3·4·앉아 있기 1~3·입)은 기준 그림의 차이를 그대로.
- 카드: 상반신이 가로형(1312×1199)이라 얼굴 중심으로 가로를 잘라 다른 카드와 같은 세로 비율(1199:1312)로.
"""
from __future__ import annotations

import cv2
import numpy as np

from scripts.build_aria_frames import clean
from scripts.build_dare_frames import ROOT, _tight, head_width, imread, imwrite, scaled, split
from scripts.build_talk_frames import _on, _shift
from scripts.color_parts import PARTS
from scripts.sheet_colors import harmonize

SHEETS = ROOT / "docs/characters/assets/레나/SD"
OUT = ROOT / "src/mabinogi_addon/assets/characters/레나"
STAND_H = 285


def sheet(name: str) -> list[np.ndarray]:
    return split(clean(imread(SHEETS / f"{name}.png", cv2.IMREAD_UNCHANGED)))


def _aligned(base: np.ndarray, other: np.ndarray, box, r: float) -> np.ndarray:
    """other를 base 크기 캔버스에 놓고 box(y0,y1,x0,x1) 창으로 phaseCorrelate 맞춤(실패면 제자리)."""
    h, w = base.shape[:2]
    other = _on(other, (h, w))
    dx, dy = _shift(base, other, box, r)
    if dx is None:
        return other
    return cv2.warpAffine(other, np.float32([[1, 0, -dx], [0, 1, -dy]]), (w, h), flags=cv2.INTER_LINEAR,
                          borderValue=(0, 0, 0, 0))


def _blend(base: np.ndarray, top: np.ndarray, mask: np.ndarray) -> np.ndarray:
    mask = mask.copy()
    mask[mask < 1 / 255] = 0
    m = mask[..., None]
    return np.clip(base.astype(np.float32) * (1 - m) + top.astype(np.float32) * m, 0, 255).astype(np.uint8)


def face_only(base: np.ndarray, other: np.ndarray) -> np.ndarray:
    """쓰다듬기 참는 중: base 몸에 other의 얼굴 타원만(가운데·42% 높이, 반지름 폭 22%·키 11%)."""
    h, w = base.shape[:2]
    cx, cy, rx, ry = w / 2, h * 0.42, w * 0.22, h * 0.11
    box = (int(max(0, cy - 2 * ry)), int(min(h, cy + 2 * ry)), int(max(0, cx - 1.5 * rx)), int(min(w, cx + 1.5 * rx)))
    aligned = _aligned(base, other, box, ry)
    mask = np.zeros((h, w), np.float32)
    cv2.ellipse(mask, (int(cx), int(cy)), (int(rx), int(ry)), 0, 0, 360, 1.0, -1)
    return _blend(base, aligned, cv2.GaussianBlur(mask, (0, 0), 6))


def changed_part(base: np.ndarray, other: np.ndarray) -> np.ndarray:
    """앉아 있기: base 위에 other에서 달라진 가장 큰 덩어리(발끝 까딱·흘겨봄·깜빡임)만."""
    h, w = base.shape[:2]
    aligned = _aligned(base, other, (0, h, 0, w), h * 0.05)
    diff = np.abs(aligned.astype(np.int16) - base.astype(np.int16)).max(-1)
    strong = (diff > 40).astype(np.uint8)
    strong = cv2.morphologyEx(strong, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(strong, np.ones((9, 9), np.uint8)))
    if count <= 1:
        return base.copy()
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask = cv2.dilate((labels == biggest).astype(np.uint8), np.ones((15, 15), np.uint8)).astype(np.float32)
    return _blend(base, aligned, cv2.GaussianBlur(mask, (0, 0), 5))


def end_frames() -> list[np.ndarray]:
    """'말하기_한장모음' 오른쪽 두 장(끝 사이 → 서기와 같은 자세) — 덩어리로 잘라냄(줄·칸 분리로는 묶여 나옴)."""
    image = clean(imread(SHEETS / "레나_말하기_한장모음.png", cv2.IMREAD_UNCHANGED))
    alpha = (image[..., 3] > 40).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(alpha, np.ones((7, 7), np.uint8)))
    blobs = sorted((stats[i, cv2.CC_STAT_LEFT], i) for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] > 5000)
    out = []
    for _x, i in blobs[-2:]:
        x, y, bw, bh = (stats[i, k] for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        part = image[y:y + bh, x:x + bw].copy()
        part[labels[y:y + bh, x:x + bw] != i] = 0
        out.append(_tight(part))
    return out


def build() -> dict[str, list[np.ndarray]]:
    by_height = lambda frames: STAND_H / np.median([f.shape[0] for f in frames])  # noqa: E731
    out: dict[str, list[np.ndarray]] = {}
    rise = sheet("레나_일어나기")  # 앉음 → 반쯤 → 선(= 서 있기)
    s_stand = STAND_H / rise[2].shape[0]
    out["stand"] = [scaled(rise[2], s_stand)]
    out["rise"] = [scaled(f, s_stand) for f in rise]
    head = head_width(rise[2]) * s_stand
    walk = sheet("레나_걷기")
    out["walk"] = [scaled(f, by_height(walk)) for f in walk]
    drag = sheet("레나_끌기")
    out["drag"] = [scaled(f, by_height(drag)) for f in drag]
    start = sheet("레나_말하기_시작")
    s_start = by_height(start)
    out["fall"] = [scaled(sheet("레나_떨어지기")[0], s_start)]  # 1번 한 장만(사용자 11-24)
    land = sheet("레나_착지")  # 엎어짐 → 일으킴 → 옷 털기 → 팔짱 서기
    out["land"] = [scaled(f, STAND_H / land[3].shape[0]) for f in land]
    crouch = sheet("레나_앉기")
    s_crouch = STAND_H / crouch[0].shape[0]
    out["crouch"] = [scaled(f, s_crouch) for f in crouch]
    sit = sheet("레나_앉아있기")  # 0 기본 · 1 발끝 까딱 · 2 흘겨보며 한숨 · 3 깜빡임
    s_sit = crouch[2].shape[0] * s_crouch / np.median([f.shape[0] for f in sit])
    out["sit"] = [scaled(sit[0], s_sit)] + [scaled(changed_part(sit[0], f), s_sit) for f in sit[1:]]
    pet = sheet("레나_쓰다듬기")  # 0 움찔 · 1 이 악묾 · 2·3·4 참는 중 · 5 '흥' 팔짱
    s_pet = head / float(np.median([head_width(f) for f in pet]))  # 이 시트만 머리 110% → 머리 폭 맞춤
    composed = pet[:3] + [face_only(pet[2], pet[3]), face_only(pet[2], pet[4])] + pet[5:]
    out["pet"] = [scaled(f, s_pet) for f in composed]
    # 마법 연습 펑 실패(기획 11-25 기본 동작 — 3~6분에 한 번): 서 있기 머리 폭에 맞춤
    magic = split(clean(imread(ROOT / "docs/characters/assets/레나/마법 폭발을 겪은 소녀의 6컷 감정극.png",
                               cv2.IMREAD_UNCHANGED)))
    from scripts.silhouette import best_scale   # 크기는 같은 자세인 0번 실루엣을 서 있기에 맞춤(QA 11-25)
    k = head / float(np.median([head_width(f) for f in magic]))
    k *= best_scale(out["stand"][0], scaled(magic[0], k))
    out["magic"] = [scaled(f, k) for f in magic]
    from scripts.build_talk_frames import talk_frames
    out.update(talk_frames("레나"))
    end_mid, end_stand = end_frames()
    out["talk_end1"] = [scaled(end_mid, STAND_H / end_stand.shape[0])]
    out["talk_end2"] = [scaled(end_stand, STAND_H / end_stand.shape[0])]
    return harmonize(out, out["stand"][0], PARTS["레나"], GROUPS)


GROUPS = {("pet", 3): ("pet", 2), ("pet", 4): ("pet", 2), ("sit", 1): ("sit", 0), ("sit", 2): ("sit", 0),
          ("sit", 3): ("sit", 0), ("talk_m1", 0): ("talk_base", 0), ("talk_m2", 0): ("talk_base", 0)}


EXPECTED = {"magic": 6, "stand": 1, "rise": 3, "walk": 6, "drag": 4, "fall": 1, "land": 4, "crouch": 3, "sit": 4, "pet": 6,
            "talk_base": 1, "talk_m1": 1, "talk_m2": 1, "talk_emph": 1, "talk_emph2": 1, "talk_blink": 1,
            "talk_mid": 1, "talk_end1": 1, "talk_end2": 1}


def card() -> np.ndarray:
    """가로형 상반신 → 얼굴(위 45% 알파 무게중심 x) 가운데로 세로 비율 1199:1312에 맞게 가로를 자름."""
    art = imread(ROOT / "docs/characters/assets/레나/레나_상반신.png", cv2.IMREAD_UNCHANGED)
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
        if old.name != "frame.png":   # 카드 테두리(build_card_frames)는 남김
            old.unlink()
    for key, items in frames.items():
        for i, frame in enumerate(items):
            imwrite(OUT / f"{key}_{i}.png", frame)
            print(f"{key}_{i}: {frame.shape[1]}×{frame.shape[0]}")
    imwrite(OUT / "card.png", card())


if __name__ == "__main__":
    main()
