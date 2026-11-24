"""이안 SD 시트 → 펫 프레임 PNG(캐릭터 알파, docs/characters/이안.md 'SD 프레임 시트' 표).

실행: uv run python -m scripts.build_ian_frames
- 분리·축소·옅은 막 지우기는 다래·아리아와 같은 도구. 저장 키 STAND_H 285.
- 크기: 시트마다 서 있는 키 285. 끌기는 매달린 키를 서 있는 키로, 떨어지기는 서 있기 시트 배율, 착지는 마지막(선) 프레임 키,
  앉아 기다리기는 웅크리기 끝 프레임 높이, 일어나기는 첫 프레임 쪼그림 폭 → 마지막 서 있는 키로 배율을 점점(다래와 같음).
- 결과: src/mabinogi_addon/assets/characters/이안/<동작>_<번호>.png + card.png(상반신).
"""
from __future__ import annotations

import cv2
import numpy as np

from scripts.build_aria_frames import clean
from scripts.build_dare_frames import ROOT, _tight, imread, imwrite, scaled, split

SHEETS = ROOT / "docs/characters/assets/이안/SD"
OUT = ROOT / "src/mabinogi_addon/assets/characters/이안"
STAND_H = 285
# 원본 시트 머리 폭(px, 기획 측정 11-24 — docs/characters/이안.md '움직임 시안 고침')
HEAD_STAND = 467
HEAD_FALL = (438, 465)
HEAD_LAND0 = 402


def sheet(name: str) -> list[np.ndarray]:
    return split(clean(imread(SHEETS / name, cv2.IMREAD_UNCHANGED)))


def build() -> dict[str, list[np.ndarray]]:
    by_height = lambda frames: STAND_H / np.median([f.shape[0] for f in frames])  # noqa: E731
    out: dict[str, list[np.ndarray]] = {}
    stand = sheet("이안 치비 스프라이트 시트.png")  # 0 입 벌림(말하기) · 1 다문 입(기본)
    s_stand = by_height(stand)
    out["stand"] = [scaled(f, s_stand) for f in stand]
    watch = sheet("시계를 확인하는 치비 캐릭터 4컷.png")
    out["watch"] = [scaled(f, by_height(watch)) for f in watch]
    walk = sheet("네이비 정장 치비 캐릭터 걷기 스프라이트 시트.png")
    out["walk"] = [scaled(f, by_height(walk)) for f in walk]
    pet = sheet("6컷 남자 캐릭터 감정 변화 스프라이트.png")
    out["pet"] = [scaled(f, by_height(pet)) for f in pet]
    drag = sheet("늘어진 회사원 치비 스프라이트 시트.png")
    out["drag"] = [scaled(f, by_height(drag)) for f in drag]  # 매달린 키 = 서 있는 키
    # 떨어지기·착지 시트는 머리/키 비율이 커서(0.60~0.65, 서 있기 0.55) 서 있는 키로 맞추면 착지 순간 머리가 커진다
    # (사용자 11-24 '낙하가 어색') → 떨어지기는 머리 폭을 서 있기 머리 폭에, 착지는 첫 장 머리 폭 → 마지막 서 있는 키로 보간.
    head = HEAD_STAND * s_stand  # 서 있기 머리 폭(저장 크기)
    fall = sheet("이안의 두 가지 추락 포즈 스프라이트.png")
    out["fall"] = [scaled(f, head / w) for f, w in zip(fall, HEAD_FALL)]
    land = sheet(next(SHEETS.glob("이안의 착지 애니메이션*.png")).name)
    l0, l2 = head / HEAD_LAND0, STAND_H / land[2].shape[0]  # 마지막 = 선 자세
    out["land"] = [scaled(f, r) for f, r in zip(land, (l0, (l0 + l2) / 2, l2))]
    crouch = sheet("이안의 3단계 웅크리기 포즈.png")
    s_crouch = STAND_H / crouch[0].shape[0]
    out["crouch"] = [scaled(f, s_crouch) for f in crouch]
    crouch_h, crouch_w = crouch[2].shape[0] * s_crouch, crouch[2].shape[1] * s_crouch
    sit = sheet("웅크린 이안 캐릭터 스프라이트 시트.png")
    out["sit"] = [scaled(f, crouch_h / np.median([x.shape[0] for x in sit])) for f in sit]
    rise = sheet("이안의 웅크림부터 기립까지 애니메이션 스프라이트셋.png")
    r0, r2 = crouch_w / rise[0].shape[1], STAND_H / rise[2].shape[0]
    out["rise"] = [scaled(f, r) for f, r in zip(rise, (r0, (r0 + r2) / 2, r2))]
    point = sheet("말하는 이안의 두 가지 포즈.png")
    out["talk_point"] = [scaled(f, by_height(point)) for f in point]
    alert = sheet("시계를 가리키는 치비 캐릭터 스프라이트 시트.png")
    out["talk_alert"] = [scaled(f, by_height(alert)) for f in alert]
    return out


EXPECTED = {"stand": 2, "watch": 4, "walk": 6, "pet": 6, "drag": 4, "fall": 2, "land": 3, "crouch": 3, "sit": 4,
            "rise": 3, "talk_point": 2, "talk_alert": 6}


def card() -> np.ndarray:
    art = _tight(imread(ROOT / "docs/characters/assets/이안/이안_상반신.png", cv2.IMREAD_UNCHANGED))
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
