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
from scripts.build_dare_frames import ROOT, _tight, head_width, imread, imwrite, scaled, split

SHEETS = ROOT / "docs/characters/assets/이안/SD"
OUT = ROOT / "src/mabinogi_addon/assets/characters/이안"
STAND_H = 285


def sheet(name: str) -> list[np.ndarray]:
    return split(clean(imread(SHEETS / name, cv2.IMREAD_UNCHANGED)))


def build() -> dict[str, list[np.ndarray]]:
    """서 있는 계열 시트는 머리 폭을 서 있기 머리 폭에 맞춤(사용자 11-24 — 키로 맞추면 클릭·걷기 때 머리가 커졌다
    작아짐: pet 113%·talk 94% 등). 앉은 계열은 이어지는 프레임과 맞춤 그대로."""
    out: dict[str, list[np.ndarray]] = {}
    stand = sheet("이안 치비 스프라이트 시트.png")  # 0 입 벌림 · 1 다문 입(기본)
    s_stand = STAND_H / np.median([f.shape[0] for f in stand])
    out["stand"] = [scaled(f, s_stand) for f in stand]
    head = head_width(stand[1]) * s_stand  # 서 있기 머리 폭(저장 크기) — 모든 서 있는 계열의 기준
    by_head = lambda frame: head / head_width(frame)  # noqa: E731
    # 여러 장 시트는 머리 폭 중앙값으로(장식 표시 '!'·땀이 머리 옆에 붙은 장 하나에 끌려가지 않게)
    by_heads = lambda frames: head / float(np.median([head_width(f) for f in frames]))  # noqa: E731
    watch = sheet("시계를 확인하는 치비 캐릭터 4컷.png")
    out["watch"] = [scaled(f, by_heads(watch)) for f in watch]
    walk = sheet("네이비 정장 치비 캐릭터 걷기 스프라이트 시트.png")
    out["walk"] = [scaled(f, by_heads(walk)) for f in walk]
    pet = sheet("6컷 남자 캐릭터 감정 변화 스프라이트.png")
    out["pet"] = [scaled(f, by_heads(pet)) for f in pet]
    drag = sheet("늘어진 회사원 치비 스프라이트 시트.png")
    out["drag"] = [scaled(f, by_head(drag[0])) for f in drag]
    fall = sheet("이안의 두 가지 추락 포즈 스프라이트.png")
    out["fall"] = [scaled(f, by_head(f)) for f in fall]  # 앱은 fall_0만 씀(사용자 11-24), fall_1은 예비
    land = sheet(next(SHEETS.glob("이안의 착지 애니메이션*.png")).name)
    l0, l2 = by_head(land[0]), by_head(land[2])  # 첫 장 머리 폭 → 끝(선 자세) 머리 폭으로 보간
    out["land"] = [scaled(f, r) for f, r in zip(land, (l0, (l0 + l2) / 2, l2))]
    crouch = sheet("이안의 3단계 웅크리기 포즈.png")
    s_crouch = STAND_H / crouch[0].shape[0]
    out["crouch"] = [scaled(f, s_crouch) for f in crouch]
    crouch_h, crouch_w = crouch[2].shape[0] * s_crouch, crouch[2].shape[1] * s_crouch
    sit = sheet("웅크린 이안 캐릭터 스프라이트 시트.png")
    out["sit"] = [scaled(f, crouch_h / np.median([x.shape[0] for x in sit])) for f in sit]
    rise = sheet("이안의 웅크림부터 기립까지 애니메이션 스프라이트셋.png")
    r0, r2 = crouch_w / rise[0].shape[1], by_head(rise[2])  # 쪼그림 폭 → 끝 머리 폭으로 보간
    out["rise"] = [scaled(f, r) for f, r in zip(rise, (r0, (r0 + r2) / 2, r2))]
    # 말하기(사용자 11-24 다시 만들기): 새 시트 입만 바꾸기 — 배율도 머리 폭으로
    from scripts.build_talk_frames import talk_frames
    out.update(talk_frames("이안", head))
    alert = sheet("시계를 가리키는 치비 캐릭터 스프라이트 시트.png")
    out["talk_alert"] = [scaled(f, by_head(alert[0])) for f in alert]
    return out


EXPECTED = {"stand": 2, "watch": 4, "walk": 6, "pet": 6, "drag": 4, "fall": 2, "land": 3, "crouch": 3, "sit": 4,
            "rise": 3, "talk_alert": 6, "talk_base": 1, "talk_m1": 1, "talk_m2": 1, "talk_emph": 1,
            "talk_emph2": 1, "talk_blink": 1, "talk_mid": 1}


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
