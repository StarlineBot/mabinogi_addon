"""아리아 SD 시트 → 펫 프레임 PNG(캐릭터 알파, docs/characters/아리아.md 'SD 프레임 시트' 표).

실행: uv run python -m scripts.build_aria_frames
- 분리·축소는 다래와 같은 도구(scripts/build_dare_frames.split·scaled). 저장 키 STAND_H 285(앱 FRAME_DIR_H와 같음).
- 모든 시트: 가장자리와 이어진 알파 40 이하(옅은 막 — 끌기 시트에 깔려 있음)를 먼저 지운다(다른 시트에는 무해).
- 크기: 시트마다 서 있는 프레임 키 = 285. 착지는 일어나기 시트의 서 있는 프레임 배율, 끌기는 서 있기 시트 배율,
  앉아 있기는 웅크리기 끝 프레임 높이에 맞춤, 일어나기(쪼그려 앉아 일어나는 3컷)는 쪼그림 높이→서 있는 키로 점점.
- 걷기('파스텔 치비 소녀 걷기')는 정수리 머리색이 서 있기보다 노래서 보정: 서 있기 프레임 위 18%의 알파>220 픽셀 Lab
  중앙값과의 차이(L은 절반)를 HSV H 5~25·S 30~150·V>150 픽셀(1.5px 흐린 마스크)에만 더한다.
- 결과: src/mabinogi_addon/assets/characters/아리아/<동작>_<번호>.png + card.png(상반신).
"""
from __future__ import annotations

import pathlib

import cv2
import numpy as np

from scripts.build_dare_frames import ALPHA_MIN, ROOT, _tight, imread, imwrite, scaled, split

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


def _top_lab(frame: np.ndarray) -> np.ndarray:
    """프레임 위 18%의 알파>220 픽셀 Lab 중앙값(정수리 머리색)."""
    top = frame[: max(1, int(frame.shape[0] * 0.18))]
    solid = top[..., 3] > 220
    lab = cv2.cvtColor(np.ascontiguousarray(top[..., :3]), cv2.COLOR_BGR2LAB).reshape(-1, 3)[solid.reshape(-1)]
    return np.median(lab.astype(np.float32), axis=0)


def match_hair(frame: np.ndarray, target_lab: np.ndarray) -> np.ndarray:
    """머리색(노랑~살구, 중간 채도, 밝음) 픽셀에만 서 있기와의 Lab 차이를 더한다(L은 절반, 경계 1.5px 흐림)."""
    diff = target_lab - _top_lab(frame)
    diff[0] *= 0.5
    bgr = np.ascontiguousarray(frame[..., :3])
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    mask = ((h >= 5) & (h <= 25) & (s >= 30) & (s <= 150) & (v > 150) & (frame[..., 3] > 0)).astype(np.float32)
    mask = cv2.GaussianBlur(mask, (0, 0), 1.5)[..., None]
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    lab = np.clip(lab + mask * diff, 0, 255).astype(np.uint8)
    out = frame.copy()
    out[..., :3] = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    return out


def build() -> dict[str, list[np.ndarray]]:
    by_height = lambda frames, h: STAND_H * h / np.median([f.shape[0] for f in frames])  # noqa: E731
    out: dict[str, list[np.ndarray]] = {}
    stand = sheet("양쪽 포즈의 꽃장식 소녀 캐릭터 스프라이트.png")
    s_stand = by_height(stand, 1.0)
    out["stand"] = [scaled(f, s_stand) for f in stand]
    target = _top_lab(out["stand"][0])
    walk = sheet("파스텔 치비 소녀 걷기 스프라이트.png")
    out["walk"] = [match_hair(scaled(f, by_height(walk, 1.0)), target) for f in walk]
    surprise = sheet("투명 배경 치비 캐릭터 4컷 스프라이트.png")
    out["surprise"] = [scaled(f, by_height(surprise, 1.0)) for f in surprise]
    drag = sheet("떨어지는 치비 소녀 애니메이션 프레임.png")
    out["drag"] = [scaled(f, s_stand) for f in drag]  # 끌기는 서 있기 시트 배율(같은 크기 시트)
    getup = sheet("일어나는 치비 소녀 3단계 포즈.png")
    s_getup = STAND_H / getup[2].shape[0]
    out["land"] = [scaled(f, s_getup) for f in sheet("세 가지 포즈의 귀여운 착지 소녀.png")]
    out["getup"] = [scaled(f, s_getup) for f in getup]
    pet = sheet("귀여운 소녀 쓰다듬기 반응 스프라이트 시트.png")
    out["pet"] = [scaled(f, by_height(pet, 1.0)) for f in pet]
    crouch = sheet("세 장면으로 이어지는 귀여운 소녀의 웅크리기 변화.png")
    s_crouch = STAND_H / crouch[0].shape[0]
    out["crouch"] = [scaled(f, s_crouch) for f in crouch]
    crouch_h = crouch[2].shape[0] * s_crouch
    sit = sheet("머리카락을 안은 꼬마 요정 4컷.png")  # 보통·웃음·눈 감고 웃음·보통
    out["sit"] = [scaled(f, crouch_h / np.median([x.shape[0] for x in sit])) for f in sit]
    rise = sheet("쪼그려 앉아 일어나는 요정 소녀 3컷.png")
    r0, r2 = crouch_h / rise[0].shape[0], STAND_H / rise[2].shape[0]
    out["rise"] = [scaled(f, r) for f, r in zip(rise, (r0, (r0 + r2) / 2, r2))]
    stroke = sheet("복숭아빛 머리 소녀 치비 4종 세트.png")
    out["hair"] = [scaled(f, by_height(stroke, 1.0)) for f in stroke]
    # 말하기(사용자 11-24 다시 만들기): 보통·설명·강조·깜빡임은 새 시트 A·B 입만 바꾸기(build_talk_frames),
    # 기쁨은 예전 그림(두 꼬마 요정 + 입 시트 웃음) 그대로
    mouth = sheet("말하는 귀여운 소녀 6컷 스프라이트 시트.png")  # 3번 = 웃음만 씀
    out["talk_laugh"] = [scaled(mouth[3], by_height(mouth, 1.0))]
    from scripts.build_talk_frames import talk_frames
    out.update(talk_frames("아리아"))
    happy = sheet("말하는 귀여운 두 꼬마 요정.png")
    out["talk_happy"] = [scaled(f, by_height(happy, 1.0)) for f in happy]
    return out


EXPECTED = {"stand": 2, "walk": 6, "surprise": 4, "drag": 2, "land": 3, "getup": 3, "pet": 6, "crouch": 3, "sit": 4,
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
        old.unlink()
    for key, items in frames.items():
        for i, frame in enumerate(items):
            imwrite(OUT / f"{key}_{i}.png", frame)
            print(f"{key}_{i}: {frame.shape[1]}×{frame.shape[0]}")
    imwrite(OUT / "card.png", card())


if __name__ == "__main__":
    main()
