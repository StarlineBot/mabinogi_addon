"""레나 영상판 프레임(기획 11-28 — docs/status.md '레나 원본크기', 사용자 지시 '다래 레나까지 한번에').

실행: uv run python -m scripts.build_lena_video
- 소스: docs/characters/assets/레나/영상/원본크기/ — Starline·다래와 같은 원본 px 체계(서 있기 상자 키 404 = Starline × 0.782),
  0.1초 간격, 동작 폴더마다 30장이 같은 상자 — 상자째 놓음(다래 scripts/build_dare_video와 같은 규칙).
- 그림은 원본 그대로(WebP 화질 90, 말하기 장만 무손실). 말하기는 팔짱 낀 입 다문 8번 몸에 작은 입(21번)·큰 입(11번)만.
- 놓는 자리(anchors.json): 기준 장 발 = 서 있기 발. 구석 가만히(L8)는 첫 장이 구석 앉기(L7) 끝 장과 같은 자세 → 그 장에 겹치게.
  마법서는 펼치기(L11) 0번·덮기(L12) 29번이 각각 기준 장(한 모션 60장 — 앞 30장 L11, 뒤 30장 L12).
- 착장(빨간 원피스·연구실 차림) 그림·card.png·frame.png·frame.json·lines.json은 그대로, 예전 기본 옷 PNG는 지움.
"""
from __future__ import annotations

import json

import cv2
import numpy as np

from scripts.build_dare_frames import imread
from scripts.build_dare_video import _overlap_anchor, foot, mouth_on
from scripts.build_outfit_frames import APP_ROOT, ASSETS

SRC = ASSETS / "레나" / "영상" / "원본크기"
OUT = APP_ROOT / "레나"
KEEP = {"card.png", "frame.png", "frame.json", "lines.json"}
WEBP_QUALITY = 90
# 앱 이름 앞부분 → (소스 폴더, 쓸 장 번호, 기준 장 — 그 장 발을 서 있기 발 자리에; "crouch"면 구석 앉기 끝 장에 겹침)
FOLDERS = {
    "walk": ("L2_걷기", range(10, 25), None),        # 오른쪽 보는 옆모습, 10~24 반복
    "pet": ("L4_쓰다듬기", range(30), 0),
    "drag": ("L5_끌기", range(30), 0),               # 0~7 매달림 시작 한 번 → 8~29 왕복
    "land": ("L6_떨어지기착지", range(7, 30), 29),   # 7 = 떨어지는 한 장
    "crouch": ("L7_구석앉기", range(30), 0),
    "sit": ("L8_구석가만히", range(30), "crouch"),   # 첫 장 = 구석 앉기 끝 장 자세
    "rise": ("L9_구석에서내려오기", range(30), 29),
    "magic": ("L10_마법펑", range(30), 0),
}
GRIMOIRE = (("L11_마법서펼치기", 0), ("L12_마법서덮기", 29))   # motion_grimoire_0~29, 30~59
CROUCH_END = 29
TALK = "L3_말하기"
TALK_ANCHOR = 0                 # 말하기 영상 기준 장(서 있는 0번)
TALK_BODY = 8                   # 팔짱 끼고 입 다문 장 = talk_base(몸)
TALK_MOUTH = {"m1": 21, "m2": 11}   # 작은 입·큰 입
# 검지 세운 장은 12~19 — 14~17은 오른쪽 머리끝이 발 높이까지 내려와 발 띠(qa_frame_check)가 10px 옆으로 잡힘(발은 같음) → 13·18
TALK_PICK = {"mid": 3, "emph": 13, "emph2": 18, "end1": 28, "end2": 29, "alert": 13}
MOUTH_BOX = (134, 156, 34, 26)  # (x, y, w, h) 8번 입 둘레(저장 px)
EYES_BOX = (102, 128, 96, 26)   # 얼굴 맞춤 기준(눈 줄)
DRAW_SCALE: dict = {}


def _src(folder: str, index: int) -> np.ndarray:
    image = imread(SRC / folder / f"{index:02d}.png", cv2.IMREAD_UNCHANGED)
    if image is None:
        raise SystemExit(f"{folder}/{index:02d}.png가 없어요")
    return image


def frames() -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {f"stand_{i}": imread(SRC / f"stand_{i:02d}.png", cv2.IMREAD_UNCHANGED) for i in range(30)}
    for prefix, (folder, indices, _ref) in FOLDERS.items():
        out.update({f"{prefix}_{i}": _src(folder, i) for i in indices})
    for part, (folder, _ref) in enumerate(GRIMOIRE):
        out.update({f"motion_grimoire_{part * 30 + i}": _src(folder, i) for i in range(30)})
    body = _src(TALK, TALK_BODY)
    out["talk_base_0"] = body
    out["talk_blink_0"] = body   # 말하며 깜빡이는 장 없음 — base 그대로(Starline·다래와 같음)
    for key, index in TALK_MOUTH.items():
        out[f"talk_{key}_0"] = mouth_on(body, _src(TALK, index), MOUTH_BOX, EYES_BOX)
    out.update({f"talk_{key}_0": _src(TALK, index) for key, index in TALK_PICK.items()})
    missing = [n for n, im in out.items() if im is None]
    if missing:
        raise SystemExit(f"소스가 없어요: {missing}")
    return out


def anchors(made: dict[str, np.ndarray]) -> dict[str, tuple[int, int]]:
    """장 이름 → 놓는 오프셋(저장 px)."""
    sy, sx = foot(made["stand_0"])

    def to_stand(image: np.ndarray) -> tuple[int, int]:
        fy, fx = foot(image)
        return round(sx - fx), round(fy - sy)

    by_prefix: dict[str, tuple[int, int]] = {}
    for prefix, (folder, indices, ref) in FOLDERS.items():
        if isinstance(ref, int):
            by_prefix[prefix] = to_stand(_src(folder, ref))
        elif ref is None:   # 걷기: 기준 장 없음 — 발 평균을 서 있기 발 자리에
            feet = [foot(_src(folder, i)) for i in indices]
            fy, fx = float(np.mean([f[0] for f in feet])), float(np.mean([f[1] for f in feet]))
            by_prefix[prefix] = (round(sx - fx), round(fy - sy))
    by_prefix["sit"] = _overlap_anchor(_src(FOLDERS["sit"][0], 0), _src(FOLDERS["crouch"][0], CROUCH_END), by_prefix["crouch"])
    talk = to_stand(_src(TALK, TALK_ANCHOR))
    out: dict[str, tuple[int, int]] = {}
    for name in made:
        prefix = name.rsplit("_", 1)[0]
        if prefix.startswith("talk_"):
            out[name] = talk
        elif prefix in by_prefix:
            out[name] = by_prefix[prefix]
    for part, (folder, ref) in enumerate(GRIMOIRE):
        offset = to_stand(_src(folder, ref))
        for i in range(30):
            out[f"motion_grimoire_{part * 30 + i}"] = offset
    return out


def main() -> None:
    made = frames()
    for old in [*OUT.glob("*.png"), *OUT.glob("*.webp")]:
        if old.name not in KEEP:
            old.unlink()
    for name, image in sorted(made.items()):
        quality = 101 if name.startswith("talk_") else WEBP_QUALITY   # 말하기는 무손실(입만 바뀌는 장끼리 몸 픽셀 같게)
        ok, data = cv2.imencode(".webp", image, [cv2.IMWRITE_WEBP_QUALITY, quality])
        if not ok:
            raise SystemExit(f"{name} WebP로 못 바꿨어요")
        (OUT / f"{name}.webp").write_bytes(data.tobytes())
    table = {name: list(v) for name, v in sorted(anchors(made).items()) if v != (0, 0)}
    (OUT / "anchors.json").write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    stand_h = int(made["stand_0"].shape[0])
    meta = {"standH": stand_h, **({"drawScale": DRAW_SCALE} if DRAW_SCALE else {})}
    (OUT / "frames.json").write_text(json.dumps(meta) + "\n", encoding="utf-8")
    print("레나", len(made), "anchors", sorted({tuple(v) for v in table.values()}))


if __name__ == "__main__":
    main()
