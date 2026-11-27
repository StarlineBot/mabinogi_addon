"""Starline 영상판 프레임(사용자 11-27 '맘에 들어, 개발로 넘겨줘' — docs/characters/Starline_영상모션_작업표.md).

실행: uv run python -m scripts.build_starline_video
- 소스: docs/characters/assets/Starline/영상/앱크기/ — 기획이 배경 빼기·크기(서기 키 약 282)·높이·효과까지 끝낸 투명 PNG,
  0.1초 간격. 동작 폴더 안에서는 같은 틀 크기(아래·가운데 맞춰 그리면 위치 맞음). 색 처리 다시 하지 않음(harmonize 없음).
- 걷기: docs/characters/assets/Starline/의상/새디자인2/영상걷기/앱크기2/vwalk14_0~13.png(장마다 꽉 맞춘 그림).
- 앱 폴더(assets/characters/Starline)의 예전 프레임은 지우고 쓰는 장만 넣음(card.png·frame.png·frame.json·lines.json은 그대로).
- 말하기: 장마다 몸이 조금씩 달라 그대로 쓰면 말할 때 몸이 튐 → 입 다문 10번 몸에 작은 입(6번)·큰 입(11번)만 얼굴로 맞춰 붙임.
- 사이 모션 10(6_어깨금장·7_소매팔찌)은 기능이 아직 없어 넣지 않음.
"""
from __future__ import annotations

import cv2
import numpy as np

from scripts.build_dare_frames import imread, imwrite
from scripts.build_outfit_frames import APP_ROOT, ASSETS

SRC = ASSETS / "Starline" / "영상" / "앱크기"
WALK_SRC = ASSETS / "Starline" / "의상" / "새디자인2" / "영상걷기" / "앱크기2"
OUT = APP_ROOT / "Starline"
KEEP = {"card.png", "frame.png"}
# 동작 틀마다 서 있는 발 자리가 서기 틀(아래 끝·발 가운데 +13.5)과 달라 동작이 바뀔 때 튐 → 그리기 오프셋(저장 px, anchors.json).
# 쓰다듬기·모자 마술은 몸이 왼쪽으로 7·5px(귀·모자 자리 때문에 틀이 넓음), 앉기·일어나기는 서 있는 장 발이 틀 바닥 10px 위
# (앉은 장은 공중에 떠 있는 그림이라 그대로 같이 내림), 착지는 끝 장 발이 13px 위·1.5px 왼쪽(떨어지는 4번도 같은 틀).
ANCHORS = {"pet": (7, 0), "motion_hat_magic": (5, 0), "crouch": (0, 10), "rise": (0, 10), "land": (2, 13)}
# 앱 이름 앞부분 → (소스 폴더, 쓸 장 번호)
FOLDERS = {
    "flame": ("1_대기불꽃", range(30)),
    "sneeze": ("2_재채기", range(30)),
    "pet": ("3_쓰다듬기", range(30)),
    "motion_flame_shot": ("4_장난불꽃", range(30)),
    "motion_hat_magic": ("5_모자마술", range(30)),
    "crouch": ("8_웅크리기_구석앉기", range(30)),
    "rise": ("9_일어나기", range(30)),
    "drag": ("10_끌기", (6, 7, 8, 9, 14, 15, 16, 17)),   # 10~13은 귀 끝이 잘려 뺌
    "land": ("11_떨어지기착지", (4, *range(12, 30))),      # 4 = 떨어지는 한 장
    "laugh": ("13_대기_웃음", range(30)),
    "chin": ("14_대기_턱괴기", range(30)),
}
TALK = "12_말하기"
TALK_PICK = {"mid": 4, "emph": 15, "emph2": 16, "end1": 25, "end2": 27}
TALK_BODY = 10                  # 입 다문 장 = talk_base(몸)
TALK_MOUTH = {"m1": 6, "m2": 11}   # 작은 입·큰 입
MOUTH_BOX = (88, 111, 34, 22)      # (x, y, w, h) 입 둘레 — 10번 기준 입 선 y≈118, 큰 입 y 116~125
EYES_BOX = (72, 95, 62, 18)        # 얼굴 맞춤 기준(눈 줄)


def _src(folder: str, index: int) -> np.ndarray:
    image = imread(SRC / folder / f"{index:02d}.png", cv2.IMREAD_UNCHANGED)
    if image is None:
        raise SystemExit(f"{folder}/{index:02d}.png가 없어요")
    return image


def _shift(src: np.ndarray, base: np.ndarray) -> tuple[int, int]:
    """src 눈 줄을 base에서 찾아 (dx, dy) — src 좌표 + 이 값 = base 좌표."""
    x, y, w, h = EYES_BOX
    g = lambda im: cv2.cvtColor(np.ascontiguousarray(im[..., :3]), cv2.COLOR_BGR2GRAY)   # noqa: E731
    t = g(src)[y:y + h, x:x + w]
    pad = 6
    area = g(base)[y - pad:y + h + pad, x - pad:x + w + pad]
    _, _, _, (bx, by) = cv2.minMaxLoc(cv2.matchTemplate(area, t, cv2.TM_CCOEFF_NORMED))
    return bx - pad, by - pad


def mouth_on(base: np.ndarray, src: np.ndarray) -> np.ndarray:
    """base 몸에 src 입만 — 입 둘레 타원(가장자리 3px 흐림)으로 섞음."""
    dx, dy = _shift(src, base)
    x, y, w, h = MOUTH_BOX
    patch = src[y:y + h, x:x + w].astype(np.float32)
    mask = np.zeros((h, w), np.float32)
    cv2.ellipse(mask, (w // 2, h // 2), (w // 2 - 3, h // 2 - 3), 0, 0, 360, 1.0, -1)
    mask = cv2.GaussianBlur(mask, (7, 7), 0)[..., None]
    out = base.astype(np.float32)
    region = out[y + dy:y + dy + h, x + dx:x + dx + w]
    out[y + dy:y + dy + h, x + dx:x + dx + w] = region * (1 - mask) + patch * mask
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def frames() -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    out.update({f"stand_{i}": imread(SRC / f"stand_{i:02d}.png", cv2.IMREAD_UNCHANGED) for i in range(30)})
    out.update({f"walk_{i}": imread(WALK_SRC / f"vwalk14_{i}.png", cv2.IMREAD_UNCHANGED) for i in range(14)})
    for prefix, (folder, indices) in FOLDERS.items():
        out.update({f"{prefix}_{i}": _src(folder, i) for i in indices})
    body = _src(TALK, TALK_BODY)
    out["talk_base_0"] = body
    out["talk_blink_0"] = body   # 영상에 말하며 깜빡이는 장이 없음 — 깜빡임 없이 base 그대로
    for key, index in TALK_MOUTH.items():
        out[f"talk_{key}_0"] = mouth_on(body, _src(TALK, index))
    out.update({f"talk_{key}_0": _src(TALK, index) for key, index in TALK_PICK.items()})
    missing = [n for n, im in out.items() if im is None]
    if missing:
        raise SystemExit(f"소스가 없어요: {missing}")
    return out


def main() -> None:
    made = frames()
    for old in OUT.glob("*.png"):
        if old.name not in KEEP:
            old.unlink()
    for name, image in sorted(made.items()):
        imwrite(OUT / f"{name}.png", image)
    import json
    anchors = {name: list(ANCHORS[name.rsplit("_", 1)[0]]) for name in sorted(made) if name.rsplit("_", 1)[0] in ANCHORS}
    (OUT / "anchors.json").write_text(json.dumps(anchors, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("Starline", len(made), "anchors", len(anchors))


if __name__ == "__main__":
    main()
