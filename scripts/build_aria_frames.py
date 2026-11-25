"""아리아 SD 시트 → 펫 프레임 PNG(캐릭터 알파, docs/characters/아리아.md 'SD 프레임 시트' 표).

실행: uv run python -m scripts.build_aria_frames
- 분리·축소는 다래와 같은 도구(scripts/build_dare_frames.split·scaled). 저장 키 STAND_H 285(앱 FRAME_DIR_H와 같음).
- 모든 시트: 가장자리와 이어진 알파 40 이하(옅은 막 — 끌기 시트에 깔려 있음)를 먼저 지운다(다른 시트에는 무해).
- 크기: 시트마다 서 있는 프레임 키 = 285. 착지는 일어나기 시트의 서 있는 프레임 배율, 끌기는 서 있기 시트 배율,
  앉아 있기는 웅크리기 끝 프레임 높이에 맞춤, 일어나기(쪼그려 앉아 일어나는 3컷)는 쪼그림 높이→서 있는 키로 점점.
- 시트 색 맞추기(사용자 11-24 '걸을 때 톤이 다르고 말할 때·클릭할 때 머리색이 다름'): 마지막에 공통 단계
  (scripts/sheet_colors, 부위 scripts/color_parts '아리아')로 머리·피부를 서 있기 색에 따로 맞춤 — 예전 걷기 머리 보정
  (match_hair, 피부까지 바꿈)은 쓰지 않음. 입만 합성(m1·m2)은 base의 차이를 그대로.
- 결과: src/mabinogi_addon/assets/characters/아리아/<동작>_<번호>.png + card.png(상반신).
"""
from __future__ import annotations

import pathlib

import cv2
import numpy as np

from scripts.build_dare_frames import ALPHA_MIN, ROOT, _tight, head_width, imread, imwrite, scaled, split

SHEETS = ROOT / "docs/characters/assets/아리아/SD"
OUT = ROOT / "src/mabinogi_addon/assets/characters/아리아"
STAND_H = 285


def clean(image: np.ndarray) -> np.ndarray:
    """가장자리와 이어진 옅은 막(알파 ≤ 40)을 지운다."""
    image = image.copy()
    faint = (image[..., 3] <= ALPHA_MIN).astype(np.uint8)
    _count, labels = cv2.connectedComponents(faint, connectivity=4)
    edge = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])))
    mask = np.isin(labels, [label for label in edge if label != 0])  # 0 = 옅지 않은 픽셀
    image[mask] = 0
    return image


def sheet(name: str) -> list[np.ndarray]:
    return split(clean(imread(SHEETS / name, cv2.IMREAD_UNCHANGED)))


def build() -> dict[str, list[np.ndarray]]:
    by_height = lambda frames, h: STAND_H * h / np.median([f.shape[0] for f in frames])  # noqa: E731
    out: dict[str, list[np.ndarray]] = {}
    stand = sheet("양쪽 포즈의 꽃장식 소녀 캐릭터 스프라이트.png")
    s_stand = by_height(stand, 1.0)
    out["stand"] = [scaled(f, s_stand) for f in stand]
    # 서 있는 계열은 머리 폭을 서 있기 머리 폭에 맞춤(사용자 11-24 — 키로 맞추면 동작마다 머리 크기가 달라짐:
    # land 109%·pet 107%·talk 94%). 앉은 계열은 이어지는 프레임과 맞춤 그대로.
    head = head_width(stand[0]) * s_stand
    by_head = lambda frame: head / head_width(frame)  # noqa: E731
    # 여러 장 시트는 머리 폭 중앙값으로(장식 표시 '!'·땀이 머리 옆에 붙은 장 하나에 끌려가지 않게)
    by_heads = lambda frames: head / float(np.median([head_width(f) for f in frames]))  # noqa: E731
    walk = sheet("파스텔 치비 소녀 걷기 스프라이트.png")
    out["walk"] = [scaled(f, by_head(walk[0])) for f in walk]  # 머리·피부는 마지막 색 맞추기에서(예전 머리 보정은 피부까지 바꿈)
    surprise = sheet("투명 배경 치비 캐릭터 4컷 스프라이트.png")
    out["surprise"] = [scaled(f, by_heads(surprise)) for f in surprise]
    drag = sheet("떨어지는 치비 소녀 애니메이션 프레임.png")
    out["drag"] = [scaled(f, by_head(drag[0])) for f in drag]
    getup = sheet("일어나는 치비 소녀 3단계 포즈.png")
    land = sheet("세 가지 포즈의 귀여운 착지 소녀.png")
    out["land"] = [scaled(f, by_head(land[0])) for f in land]
    out["getup"] = [scaled(f, by_head(getup[2])) for f in getup]
    pet = sheet("귀여운 소녀 쓰다듬기 반응 스프라이트 시트.png")
    out["pet"] = [scaled(f, by_heads(pet)) for f in pet]
    crouch = sheet("세 장면으로 이어지는 귀여운 소녀의 웅크리기 변화.png")
    s_crouch = STAND_H / crouch[0].shape[0]
    out["crouch"] = [scaled(f, s_crouch) for f in crouch]
    crouch_h = crouch[2].shape[0] * s_crouch
    sit = sheet("머리카락을 안은 꼬마 요정 4컷.png")  # 보통·웃음·눈 감고 웃음·보통
    out["sit"] = [scaled(f, crouch_h / np.median([x.shape[0] for x in sit])) for f in sit]
    rise = sheet("쪼그려 앉아 일어나는 요정 소녀 3컷.png")
    r0, r2 = crouch_h / rise[0].shape[0], by_head(rise[2])
    out["rise"] = [scaled(f, r) for f, r in zip(rise, (r0, (r0 + r2) / 2, r2))]
    stroke = sheet("복숭아빛 머리 소녀 치비 4종 세트.png")
    out["hair"] = [scaled(f, by_heads(stroke)) for f in stroke]
    # 말하기(사용자 11-24 다시 만들기): 보통·설명·강조·깜빡임은 새 시트 A·B 입만 바꾸기(build_talk_frames),
    # 기쁨은 예전 그림(두 꼬마 요정 + 입 시트 웃음) 그대로
    mouth = sheet("말하는 귀여운 소녀 6컷 스프라이트 시트.png")  # 3번 = 웃음만 씀
    out["talk_laugh"] = [scaled(mouth[3], by_head(mouth[3]))]
    from scripts.build_talk_frames import talk_frames
    out.update(talk_frames("아리아", head))
    happy = sheet("말하는 귀여운 두 꼬마 요정.png")
    out["talk_happy"] = [scaled(f, by_heads(happy)) for f in happy]
    # 기지개(기획 11-25 기본 동작 — 3~6분에 한 번): 서 있기 머리 폭에 맞춤
    stretch = split(clean(imread(ROOT / "docs/characters/assets/아리아/스트레칭하는 복숭아빛 머리 소녀 스프라이트 시트.png",
                                 cv2.IMREAD_UNCHANGED)))
    # 크기는 같은 자세인 0번 실루엣을 서 있기에 맞춤(QA 11-25 — 머리 폭은 머리카락에 끌려 1.07배로 튐)
    from scripts.silhouette import best_scale
    k = by_heads(stretch)
    k *= best_scale(out["stand"][0], scaled(stretch[0], k))
    out["stretch"] = [scaled(f, k) for f in stretch]
    from scripts.color_parts import PARTS
    from scripts.sheet_colors import harmonize
    groups = {(f"talk_{v}_{k}", 0): (f"talk_{v}_base", 0) for v in "ab" for k in ("m1", "m2")}
    return harmonize(out, out["stand"][0], PARTS["아리아"], groups)


EXPECTED = {"stretch": 6, "stand": 2, "walk": 6, "surprise": 4, "drag": 2, "land": 3, "getup": 3, "pet": 6, "crouch": 3, "sit": 4,
            "rise": 3, "hair": 4, "talk_laugh": 1, "talk_happy": 2,
            **{f"talk_{v}_{k}": 1 for v in "ab" for k in ("base", "m1", "m2", "emph", "emph2", "blink", "mid")}}


def card() -> np.ndarray:
    art = _tight(imread(ROOT / "docs/characters/assets/아리아/아리아_상반신.png", cv2.IMREAD_UNCHANGED))
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
