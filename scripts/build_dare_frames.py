"""다래 SD 시트 → 펫 프레임 PNG(캐릭터 알파, docs/character-pet-spec.md 2절·docs/characters/다래.md).

실행: uv run python -m scripts.build_dare_frames
- 시트는 투명 배경이라 빈 줄·빈 칸으로 프레임을 자동 분리한다(4면도 정면만 눈금선 때문에 수동 자르기).
- 크기는 '서 있는 키'로 맞춘다(다래.md 크기 맞추기 주의): 서 있기 프레임 키 = STAND_H.
  앉은 계열(무릎베개·자다 깨기)은 웅크리기 시트의 쪼그림 폭에 맞추고, 일어나기는 쪼그림 폭→서 있는 키로 배율을 점점 바꾼다.
  착지·세 가지 자세는 같은 크기의 시트(724×2172)라 세 가지 자세의 서 있는 프레임 배율을 함께 쓴다.
- 결과: src/mabinogi_addon/assets/characters/다래/<동작>_<번호>.png (발 밑 가운데 기준으로 앱이 그림).
  저장 키 STAND_H = 285px(배율 150%에서 190px×1.5 — 100%는 앱이 줄여 그림).
"""
from __future__ import annotations

import pathlib
import sys

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from mabinogi_addon.image_io import imread, imwrite  # noqa: E402

SHEETS = ROOT / "docs/characters/assets/다래/SD"
OUT = ROOT / "src/mabinogi_addon/assets/characters/다래"
STAND_H = 285
ALPHA_MIN = 40


def _segments(on: np.ndarray, gap: int) -> list[tuple[int, int]]:
    segs, i, n = [], 0, len(on)
    while i < n:
        if not on[i]:
            i += 1
            continue
        j = i
        while j < n and (on[j] or on[j:j + gap].any()):
            j += 1
        if j - i >= 8:
            segs.append((i, j))
        i = j
    return segs


def split(image: np.ndarray) -> list[np.ndarray]:
    """빈 줄 → 줄마다 빈 칸으로 자른 프레임(읽는 순서). 각 프레임은 알파 경계로 꼭 맞게."""
    alpha = image[..., 3] > ALPHA_MIN
    frames = []
    for r0, r1 in _segments(alpha.sum(1) > 2, gap=6):
        for c0, c1 in _segments(alpha[r0:r1].sum(0) > 2, gap=10):
            frames.append(_tight(image[r0:r1, c0:c1]))
    return frames


def _tight(image: np.ndarray) -> np.ndarray:
    ys, xs = np.where(image[..., 3] > ALPHA_MIN)
    return image[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def front_view() -> np.ndarray:
    """4면도 정면(눈금선 102~103행·바닥선 623행부터, 정면과 45도 사이 빈 칸 655~668열 — 11-24 측정)."""
    image = imread(SHEETS / "다래 SD 캐릭터 4면도 모델 시트.png", cv2.IMREAD_UNCHANGED).copy()
    crop = image[:623, 150:660].copy()
    for y in (102, 103):  # 점선: 위·아래가 비어 있는 칸만 지운다(헤일로·머리와 겹친 곳은 그대로)
        row = crop[y]
        empty = (crop[y - 3, :, 3] <= ALPHA_MIN) & (crop[y + 3, :, 3] <= ALPHA_MIN)
        row[empty] = 0
    # 왼쪽 '2등신' 화살표(세로선)를 떼려고 가장 큰 덩어리만 남긴다
    mask = (crop[..., 3] > ALPHA_MIN).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(mask, np.ones((5, 5), np.uint8)))
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    crop[labels != biggest] = 0
    return _tight(crop)


def scaled(frame: np.ndarray, factor: float) -> np.ndarray:
    h, w = frame.shape[:2]
    size = (max(1, round(w * factor)), max(1, round(h * factor)))
    # 미리 곱한 알파로 줄여야 가장자리에 검은 테가 안 생긴다
    rgb = frame[..., :3].astype(np.float32) * (frame[..., 3:] / 255.0)
    small = cv2.resize(np.dstack([rgb, frame[..., 3:].astype(np.float32)]), size, interpolation=cv2.INTER_AREA)
    a = small[..., 3:]
    out_rgb = np.where(a > 0, small[..., :3] / np.maximum(a, 1e-6) * 255.0, 0)
    return np.dstack([np.clip(out_rgb, 0, 255), np.clip(a, 0, 255)]).astype(np.uint8)


def sheet(name: str) -> list[np.ndarray]:
    return split(imread(SHEETS / name, cv2.IMREAD_UNCHANGED))


def build() -> dict[str, list[np.ndarray]]:
    by_height = lambda frames, h: STAND_H * h / np.median([f.shape[0] for f in frames])  # noqa: E731
    out: dict[str, list[np.ndarray]] = {}
    stand = front_view()
    out["stand"] = [scaled(stand, STAND_H / stand.shape[0])]
    walk = sheet("오른쪽을 향한 고딕 치비 걷기 애니메이션 스프라이트.png")
    out["walk"] = [scaled(f, by_height(walk, 1.0)) for f in walk]
    surprise = sheet("깜짝 놀란 고딕 천사 소녀 애니메이션 시트.png")
    out["surprise"] = [scaled(f, by_height(surprise, 1.0)) for f in surprise]
    pet = sheet("부끄러운 치비 천사 악마 스티커 세트.png")
    out["pet"] = [scaled(f, by_height(pet, 1.0)) for f in pet]
    drag = sheet("움직이는 꼬마 천사 드래그 포즈 시트.png")
    out["drag"] = [scaled(f, by_height(drag, 1.0)) for f in drag]
    rise3 = sheet("세 가지 자세의 놀란 뿔소녀 스프라이트.png")
    s3 = STAND_H / rise3[2].shape[0]
    out["land"] = [scaled(f, s3) for f in sheet(next(SHEETS.glob("착지부터*.png")).name)]
    out["getup"] = [scaled(f, s3) for f in rise3]
    crouch = sheet("졸린 천사 캐릭터의 웅크리기 3단계.png")
    sc = STAND_H / crouch[0].shape[0]
    out["crouch"] = [scaled(f, sc) for f in crouch]
    crouch_w = crouch[2].shape[1] * sc
    sit = sheet("잠든 무릎베개 포즈 치비 스프라이트 시트.png")  # 읽는 순서: 졸림·알아챔·꾸벅 졸기·반쯤 뜸
    ss = crouch_w / sit[0].shape[1]
    names = ("sit_drowsy", "sit_notice", "sit_doze", "sit_half")
    for key, frame in zip(names, sit):
        out[key] = [scaled(frame, ss)]
    rise = sheet("졸린 천사 캐릭터의 상승 애니메이션.png")
    r0, r2 = crouch_w / rise[0].shape[1], STAND_H / rise[2].shape[0]
    out["rise"] = [scaled(f, r) for f, r in zip(rise, (r0, (r0 + r2) / 2, r2))]
    talk = sheet("6종 천사 악마 치비 스프라이트 시트.png")  # 입 다묾·조금 벌림·크게 벌림·손 들고·손 내밀고·말 끝 다묾
    for key, frame in zip(("talk_closed", "talk_small", "talk_big", "talk_hand_up", "talk_hand_out", "talk_end"), talk):
        out[key] = [scaled(frame, by_height(talk, 1.0))]
    mood = sheet("세 가지 표정의 천사 소녀들.png")  # 가리키며 설명·턱에 손 생각·눈 감고 웃음
    for key, frame in zip(("talk_point", "talk_think", "talk_smile"), mood):
        out[key] = [scaled(frame, by_height(mood, 1.0))]
    wake = sheet("잠에서 깨어나는 꼬마 천사 악마_sprite.sheet.png")
    out["wake"] = [scaled(f, crouch_w / wake[0].shape[1]) for f in wake]
    return out


EXPECTED = {"stand": 1, "walk": 6, "surprise": 2, "pet": 6, "drag": 4, "land": 3, "getup": 3, "crouch": 3,
            "sit_drowsy": 1, "sit_notice": 1, "sit_doze": 1, "sit_half": 1, "rise": 3, "wake": 4,
            "talk_closed": 1, "talk_small": 1, "talk_big": 1, "talk_hand_up": 1, "talk_hand_out": 1, "talk_end": 1,
            "talk_point": 1, "talk_think": 1, "talk_smile": 1}


def main() -> None:
    frames = build()
    for key, count in EXPECTED.items():
        if len(frames[key]) != count:
            raise SystemExit(f"{key}: 프레임 {len(frames[key])}개(기대 {count}) — 시트가 바뀌었나요?")
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        if old.name != "card.png":
            old.unlink()
    for key, items in frames.items():
        for i, frame in enumerate(items):
            imwrite(OUT / f"{key}_{i}.png", frame)
            print(f"{key}_{i}: {frame.shape[1]}×{frame.shape[0]}")


if __name__ == "__main__":
    main()
