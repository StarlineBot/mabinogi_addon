"""이안 SD 시트 → 펫 프레임 PNG(캐릭터 알파, docs/characters/이안.md 'SD 프레임 시트' 표).

실행: uv run python -m scripts.build_ian_frames
- 분리·축소·옅은 막 지우기는 다래·아리아와 같은 도구. 저장 키 STAND_H 285.
- 시트(11-24 사용자 다시 그림): 걷기·끌기·착지·쓰다듬기·웅크리기·앉아 기다리기·일어나기·말하기 시작/반복/끝·알림 말하기는
  SD/v2/, 서 있기·시계 보기·떨어지기는 SD/ 그대로(docs/characters/이안_다시그리기.md '결과').
- 크기: 시트마다 배율 하나 = 서 있기 머리 폭 / 시트 머리 폭 중앙값(웅크리기만 첫 장 키 285, 일어나기는 쪼그림 폭 → 끝 머리 폭).
- 알림 말하기는 세 명이 붙은 덩어리 두 줄 — 1/3·2/3 둘레에서 알파가 가장 적은 열로 가로 3등분.
- 결과: src/mabinogi_addon/assets/characters/이안/<동작>_<번호>.png + card.png(상반신).
"""
from __future__ import annotations

import cv2
import numpy as np

from scripts.build_aria_frames import clean
from scripts.build_dare_frames import ALPHA_MIN, ROOT, _tight, head_width, imread, imwrite, scaled, split

SHEETS = ROOT / "docs/characters/assets/이안/SD"
V2 = SHEETS / "v2"   # 사용자가 대기 그림 기준으로 다시 그린 시트(11-24, docs/characters/이안_다시그리기.md '결과')
OUT = ROOT / "src/mabinogi_addon/assets/characters/이안"
STAND_H = 285


def sheet(name: str, folder=V2) -> list[np.ndarray]:
    return split(clean(imread(folder / name, cv2.IMREAD_UNCHANGED)))


def thirds(frame: np.ndarray) -> list[np.ndarray]:
    """세 명이 붙은 덩어리(빈 열 없음)를 가로 3등분 — 1/3·2/3 둘레(±12%)에서 알파가 가장 적은 열로 자름."""
    w = frame.shape[1]
    cols = (frame[..., 3] > ALPHA_MIN).sum(0).astype(np.float64)
    cuts = [0]
    for k in (1, 2):
        lo, hi = int(w * (k / 3 - 0.12)), int(w * (k / 3 + 0.12))
        cuts.append(lo + int(np.argmin(cols[lo:hi])))
    cuts.append(w)
    return [_tight(frame[:, a:b]) for a, b in zip(cuts, cuts[1:])]


def face_ratio(stand: np.ndarray, frame: np.ndarray) -> float:
    """frame 얼굴이 stand 얼굴의 몇 배인지 — stand 얼굴 영역(머리 꼭대기에서 키 10~30%, 가운데 폭 40%)을 템플릿으로
    배율 0.75~1.35(61단계) matchTemplate(기획 11-25 측정 방법)."""
    import cv2

    def gray(img):
        a = img[..., 3:].astype(np.float32) / 255
        g = cv2.cvtColor(np.ascontiguousarray(img[..., :3]), cv2.COLOR_BGR2GRAY).astype(np.float32)[..., None]
        return (g * a + 235 * (1 - a))[..., 0].astype(np.uint8)

    h, w = stand.shape[:2]
    tmpl = gray(stand)[int(h * 0.10):int(h * 0.30), int(w * 0.30):int(w * 0.70)]
    target = gray(frame)
    best = (-2.0, 1.0)
    for k in np.linspace(0.75, 1.35, 61):
        t = cv2.resize(tmpl, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        if t.shape[0] > target.shape[0] or t.shape[1] > target.shape[1]:
            continue
        score = float(cv2.matchTemplate(target, t, cv2.TM_CCOEFF_NORMED).max())
        if score > best[0]:
            best = (score, float(k))
    return best[1]


def build() -> dict[str, list[np.ndarray]]:
    """시트마다 배율 하나 = 서 있기 머리 폭 / 그 시트 머리 폭 중앙값(사용자 11-24 머리 크기 규칙 — 한 시트 안에선 같은 배율이라
    프레임끼리 꿈틀거리지 않음). 웅크리기만 첫 장(선 자세) 키 285, 일어나기는 쪼그림 폭 → 끝 머리 폭 보간."""
    out: dict[str, list[np.ndarray]] = {}
    stand = sheet("이안 치비 스프라이트 시트.png", SHEETS)  # 0 입 벌림 · 1 다문 입(기본) — 그대로
    s_stand = STAND_H / np.median([f.shape[0] for f in stand])
    out["stand"] = [scaled(f, s_stand) for f in stand]
    head = head_width(stand[1]) * s_stand  # 서 있기 머리 폭(저장 크기) — 모든 서 있는 계열의 기준
    by_head = lambda frame: head / head_width(frame)  # noqa: E731
    by_heads = lambda frames: head / float(np.median([head_width(f) for f in frames]))  # noqa: E731
    watch = sheet("시계를 확인하는 치비 캐릭터 4컷.png", SHEETS)  # 그대로
    out["watch"] = [scaled(f, by_heads(watch)) for f in watch]
    fall = sheet("이안의 두 가지 추락 포즈 스프라이트.png", SHEETS)  # 그대로(앱은 fall_0 한 장)
    out["fall"] = [scaled(f, by_head(f)) for f in fall]
    for key, name in (("walk", "이안_걷기.png"), ("drag", "이안_끌기.png"), ("land", "이안_착지.png"),
                      ("pet", "이안_쓰다듬기.png")):
        frames = sheet(name)
        out[key] = [scaled(f, by_heads(frames)) for f in frames]
    # 앉아 있기: 머리 폭 구간에 머리카락·어깨가 섞여 머리 폭으론 얼굴이 약 8% 커짐(사용자 11-25) → 얼굴 템플릿 배율로 서 있기와 같게
    sit = sheet("이안_앉아기다리기.png")
    k_sit = by_heads(sit)
    k_sit /= float(np.median([face_ratio(out["stand"][1], scaled(f, k_sit)) for f in sit]))
    out["sit"] = [scaled(f, k_sit) for f in sit]
    crouch = sheet("이안_웅크리기.png")
    s_crouch = STAND_H / crouch[0].shape[0]
    out["crouch"] = [scaled(f, s_crouch) for f in crouch]
    rise = sheet("이안_일어나기.png")
    r0, r2 = crouch[2].shape[1] * s_crouch / rise[0].shape[1], by_head(rise[2])  # 쪼그림 폭 → 끝 머리 폭
    out["rise"] = [scaled(f, r) for f, r in zip(rise, (r0, (r0 + r2) / 2, r2))]
    # 말하기: 시작 0번 = 사이, 반복 6장 입만 합성(build_talk_frames), 끝 두 장 = 말 끝(레나와 같은 틀)
    from scripts.build_talk_frames import talk_frames
    out.update(talk_frames("이안", head))
    end = sheet("이안_말하기_끝.png")
    k_end = by_heads(end)
    out["talk_end1"], out["talk_end2"] = [scaled(end[0], k_end)], [scaled(end[1], k_end)]
    alert = [f for blob in sheet("이안_알림말하기.png") for f in thirds(blob)]  # 3명씩 두 줄
    out["talk_alert"] = [scaled(f, by_heads(alert)) for f in alert]
    return out


EXPECTED = {"stand": 2, "watch": 4, "walk": 6, "pet": 6, "drag": 4, "fall": 2, "land": 3, "crouch": 3, "sit": 4,
            "rise": 3, "talk_alert": 6, "talk_base": 1, "talk_m1": 1, "talk_m2": 1, "talk_emph": 1,
            "talk_emph2": 1, "talk_blink": 1, "talk_mid": 1, "talk_end1": 1, "talk_end2": 1}


def card() -> np.ndarray:
    """상반신이 가로형이라(폭 맞춤하면 카드 아래가 비어 보임 — 사용자 11-24 Windows) 얼굴(위 45% 알파 무게중심 x)
    가운데로 다른 카드와 같은 세로 비율(1199:1312)로 자름(레나·Starline과 같은 방식)."""
    art = _tight(imread(ROOT / "docs/characters/assets/이안/이안_상반신.png", cv2.IMREAD_UNCHANGED))
    h, w = art.shape[:2]
    cw = int(round(h * 1199 / 1312))
    if w > cw:
        cx = float(np.where(art[: int(h * 0.45), :, 3] > 40)[1].mean())
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
