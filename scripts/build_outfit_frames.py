"""착장 펫 SD 프레임 — 기획 11-25(docs/character-pet-spec.md 3-2 착장). 이안 '넥타이 조끼'·아리아 '티셔츠 차림'(호감도 50).

받은 그림은 기본 앱 프레임을 칸에 놓은 템플릿(docs/characters/assets/<캐릭터>/의상/전체프레임/)을 옷만 바꿔 다시 그린 것
(아래는 이안 예 — 아리아는 전체프레임_1~5만, 나눔 없음):
- 전체프레임_1·3·4·5.png(4×4, 칸 240×330 — 받은 크기 약 1070×1470 → 960×1320으로 줄임), 칸 대응 칸_목록.json
- 나눔_2-1~3.png(4×2 — 1512×1040 → 960×660), 칸 대응 나눔_칸_목록.json(칸 0 = 정답 예시, 버림) — part 2를 대신함

칸마다 파란 테두리를 지우고 가장 큰 덩어리 2% 이상만 남겨 꼭 맞춤(build_dare_frames.guide_cells). 템플릿 칸 그림 = 그때의 앱 프레임
크기 그대로라, 배율 = 지금 앱 프레임 키 ÷ 템플릿 칸 키(대부분 1.0 — 앉기 sit은 템플릿 뒤 얼굴 맞춤으로 줄였으므로 0.94),
모션 칸(옷매무새·차)은 1.0. 색: 머리·피부는 시트 색 맞추기(서 있기 기준), 옷(바지·조끼) 어두운 톤은 서 있기 평균에.

저장: assets/characters/<캐릭터>/outfits/<key>/<프레임>.png(기본과 같은 이름 — 펫 창이 착장 폴더를 먼저 찾음),
모션은 MOTION_NAMES(이안 motion_tidy·motion_tea, 아리아 motion_water·motion_wreath).

    uv run --frozen python -m scripts.build_outfit_frames
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import cv2
import numpy as np

from mabinogi_addon.image_io import imread, imwrite
from scripts.build_dare_frames import guide_cells, scaled

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "characters" / "assets"
APP_ROOT = ROOT / "src" / "mabinogi_addon" / "assets" / "characters"
# (캐릭터 폴더, 옷 key) → (옷 이름 폴더, 색 기준 프레임)
OUTFITS = {("이안", "vest_tie"): ("넥타이 조끼", "stand_1"), ("아리아", "tshirt"): ("티셔츠 차림", "stand_0")}
MOTION_NAMES = {"옷매무새(25)": "motion_tidy", "차(75)": "motion_tea", "물주기(25)": "motion_water", "화관(75)": "motion_wreath"}


def frame_name(raw: str) -> str:
    """칸 목록 이름 → 저장 이름(motion:옷매무새(25)_3 → motion_tidy_3)."""
    m = re.fullmatch(r"motion:(.+)_(\d+)", raw)
    return f"{MOTION_NAMES[m.group(1)]}_{m.group(2)}" if m else raw


def cells_of(folder: Path, name: str, cols: int, rows: int, size: tuple[int, int]) -> list:
    return guide_cells(name, cols, rows, folder, size)


def build(folder: str, outfit_dir: Path) -> dict[str, np.ndarray]:
    template_dir = ASSETS / folder / "의상" / "전체프레임"
    app_dir = APP_ROOT / folder
    plan = json.loads((template_dir / "칸_목록.json").read_text(encoding="utf-8"))
    split_path = template_dir / "나눔_칸_목록.json"   # 이안만(part 2를 나눔 3장이 대신)
    split = json.loads(split_path.read_text(encoding="utf-8")) if split_path.is_file() else {}
    skip = {2} if split else set()
    jobs = []   # (템플릿 시트, 옷 시트, 열, 행, 크기, [(칸, 이름)])
    for part in sorted({x["part"] for x in plan} - skip):
        jobs.append((f"전체프레임_{part}.png", f"전체프레임_{part}.png", 4, 4, (960, 1320),
                     [(x["cell"], x["frame"]) for x in plan if x["part"] == part]))
    for key, items in split.items():
        part = key.split("_")[0]
        jobs.append((f"나눔_{key}.png", f"나눔_{part}.png", 4, 2, (960, 660),
                     [(c["cell"], c["frame"]) for c in items if not c["frame"].startswith("(")]))
    out: dict[str, np.ndarray] = {}
    for template_name, outfit_name, cols, rows, size, cells in jobs:
        template = cells_of(template_dir, template_name, cols, rows, size)
        dressed = cells_of(outfit_dir, outfit_name, cols, rows, size)
        for index, raw in cells:
            name = frame_name(raw)
            image = dressed[index]
            if image is None:
                raise SystemExit(f"{outfit_name} 칸 {index}({raw})가 비었어요")
            app = app_dir / f"{name}.png"
            k = imread(app, cv2.IMREAD_UNCHANGED).shape[0] / template[index].shape[0] if app.is_file() else 1.0
            out[name] = scaled(image, k) if abs(k - 1) > 0.005 else image
    return out


def harmonize_colors(frames: dict[str, np.ndarray], ref_name: str) -> dict[str, np.ndarray]:
    """시트마다 다른 밝기(바지 ΔE 2~17·머리 1.4~11, 기획 측정)를 이 옷의 stand_1(다문 입)에 — 어두운 톤(머리·바지·조끼)과
    중간 톤(피부·그림자) Lab 평균을 각각 맞춤. 흰 셔츠 같은 밝은 톤은 그대로(기준 = 그 옷의 서 있기)."""
    from scripts.build_starline_frames import DARK, MID, match_midtone

    ref = frames[ref_name]
    return {k: v if k == ref_name else match_midtone(match_midtone(v, ref, DARK, True), ref, MID, True)
            for k, v in frames.items()}


def main() -> None:
    for (folder, key), (name, ref) in OUTFITS.items():
        frames = harmonize_colors(build(folder, ASSETS / folder / "의상" / name), ref)
        dest = APP_ROOT / folder / "outfits" / key
        dest.mkdir(parents=True, exist_ok=True)
        for old in dest.glob("*.png"):
            if old.name != "card.png":
                old.unlink()
        for frame, image in sorted(frames.items()):
            imwrite(dest / f"{frame}.png", image)
        print(f"{folder} {key}: {len(frames)}장")


if __name__ == "__main__":
    main()
