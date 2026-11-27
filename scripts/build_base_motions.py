"""기본 옷 호감도 모션 프레임(25·75) — 호감도 게이지 배포(기획 11-26, docs/characters/호감도_모션.md).

실행: uv run python -m scripts.build_base_motions
- 아리아·다래·레나·이안: 프레임표 v2 템플릿(docs/characters/assets/<이름>/의상/전체프레임_v2/ + 칸_목록.json)의 motion:* 칸이
  이미 앱 크기(머리 맞춤)라 그대로 잘라 assets/characters/<이름>/motion_<key>_N.png로(착장과 같은 이름).
- Starline(착장 없음): 원본 시트 '스타 발사 마법사 6컷 애니메이션'(25 장난 불꽃)·'토끼 귀 마법사의 모자 소동'(75 모자 마술)을
  다른 시트처럼 잘라, 키 중앙값을 서 있기(285)에 맞춘 뒤 첫 장 머리(위 42%) 실루엣을 서 있기에 맞춤. 실행 배율(1.15)은 그대로.
  머리·피부는 다른 동작처럼 시트 색 맞추기(서 있기 기준).
"""
from __future__ import annotations

import json

import cv2
import numpy as np

from scripts.build_dare_frames import imread, imwrite, scaled
from scripts.build_outfit_frames import ASSETS, APP_ROOT, TEMPLATES, cells_of, frame_name

FOLDERS = ("아리아", "다래", "레나", "이안")
STARLINE = {"motion_flame_shot": "스타 발사 마법사 6컷 애니메이션", "motion_hat_magic": "토끼 귀 마법사의 모자 소동"}
HEAD = 0.42


def _head(frame: np.ndarray) -> np.ndarray:
    return frame[:max(1, round(frame.shape[0] * HEAD))]


def template_motions(folder: str) -> dict[str, np.ndarray]:
    template_dir = ASSETS / folder / "의상" / "전체프레임_v2"
    _name, cols, rows, size, _fit = next(v for (f, _k), v in TEMPLATES.items() if f == folder)
    plan = json.loads((template_dir / "칸_목록.json").read_text(encoding="utf-8"))
    out = {}
    for part in sorted({x["part"] for x in plan}):
        cells = [(x["cell"], x["frame"]) for x in plan if x["part"] == part and x["frame"].startswith("motion:")]
        if not cells:
            continue
        cut = cells_of(template_dir, f"전체프레임_{part}.png", cols, rows, size)
        for index, raw in cells:
            if cut[index] is None:
                raise SystemExit(f"{folder} 전체프레임_{part} 칸 {index}({raw})가 비었어요")
            out[frame_name(raw)] = cut[index]
    return out


def starline_motions() -> dict[str, np.ndarray]:
    from scripts.build_starline_frames import STAND_H, sheet
    from scripts.silhouette import best_scale

    stand = imread(APP_ROOT / "Starline" / "stand_0.png", cv2.IMREAD_UNCHANGED)
    out = {}
    for key, name in STARLINE.items():
        frames = sheet(name)
        k = STAND_H / float(np.median([f.shape[0] for f in frames]))
        k *= best_scale(_head(stand), _head(scaled(frames[0], k)), 0.85, 1.15, 61)
        out.update({f"{key}_{i}": scaled(f, k) for i, f in enumerate(frames)})
    from scripts.color_parts import PARTS
    from scripts.sheet_colors import harmonize
    fixed = harmonize({"m": list(out.values())}, stand, PARTS["Starline"])["m"]   # 머리·피부 시트 색 맞추기(서 있기 대비 ΔE<3)
    return dict(zip(out, fixed))


def main() -> None:
    for folder in FOLDERS:
        frames = template_motions(folder)
        for name, image in sorted(frames.items()):
            imwrite(APP_ROOT / folder / f"{name}.png", image)
        print(folder, len(frames))
    # Starline 모션은 영상판(11-27, scripts/build_starline_video) — 옛 시트(starline_motions)로 덮지 않음


if __name__ == "__main__":
    main()
