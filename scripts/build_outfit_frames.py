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

from mabinogi_addon.image_io import imread
from mabinogi_addon.image_io import write_sprite as imwrite   # 알파 0 RGB 0·압축 9
from scripts.build_dare_frames import guide_cells, scaled

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "characters" / "assets"
APP_ROOT = ROOT / "src" / "mabinogi_addon" / "assets" / "characters"
# (캐릭터 폴더, 옷 key) → (옷 이름 폴더, 색 기준 프레임)
OUTFITS = {("이안", "vest_tie"): ("넥타이 조끼", "stand_1"), ("아리아", "tshirt"): ("티셔츠 차림", "stand_0"),
           ("레나", "lab"): ("연구실 차림", "stand_0")}
# 옷마다 템플릿(폴더, 열, 행, 시트 크기, 칸마다 머리 맞춤). 기본 = 옛 전체프레임(4×4, 960×1320), 키 비율만.
# 레나 연구실 차림(기획 11-26): 프레임표 v2(3×4, 930×1320, 테두리 없음, 새 걷기 8장 포함) — 옷 칸 키가 +1~5%로 들쭉날쭉하고
# 머리가 끌기·일어나기·웅크리기에서 크고 걷기 몇 장에서 작아, 칸마다 위 42% 실루엣으로 템플릿 머리에 맞춤(QA 11-25 규칙).
DEFAULT_TEMPLATE = ("전체프레임", 4, 4, (960, 1320), False)
TEMPLATES = {("레나", "lab"): ("전체프레임_v2", 3, 4, (930, 1320), True)}
HEAD = 0.42
# 템플릿 뒤에 다시 그려 받은 시트(가이드 방식) — (키, 파일, 열, 행, 가이드 크기, 쓸 칸). 배율 = 앱 기본 프레임 키 중앙값 ÷ 칸 키 중앙값
REDRAWN: dict = {}   # 걷기는 기획이 앱 크기로 정리한 걷기_v2/walk_0~7.png를 그대로(11-26, scripts/build_walk_v2.OUTFIT_WALKS)
MOTION_NAMES = {"옷매무새(25)": "motion_tidy", "차(75)": "motion_tea", "물주기(25)": "motion_water", "화관(75)": "motion_wreath",
                "마법서(25)": "motion_grimoire", "공중앉기(75)": "motion_float_sit"}


def frame_name(raw: str) -> str:
    """칸 목록 이름 → 저장 이름(motion:옷매무새(25)_3 → motion_tidy_3)."""
    m = re.fullmatch(r"motion:(.+)_(\d+)", raw)
    return f"{MOTION_NAMES[m.group(1)]}_{m.group(2)}" if m else raw


def cells_of(folder: Path, name: str, cols: int, rows: int, size: tuple[int, int]) -> list:
    return guide_cells(name, cols, rows, folder, size)


def _head(frame: np.ndarray) -> np.ndarray:
    return frame[:max(1, round(frame.shape[0] * HEAD))]


def build(folder: str, outfit_dir: Path, template=DEFAULT_TEMPLATE) -> dict[str, np.ndarray]:
    template_name_dir, t_cols, t_rows, t_size, head_fit = template
    template_dir = ASSETS / folder / "의상" / template_name_dir
    app_dir = APP_ROOT / folder
    plan = json.loads((template_dir / "칸_목록.json").read_text(encoding="utf-8"))
    split_path = template_dir / "나눔_칸_목록.json"   # 이안만(part 2를 나눔 3장이 대신)
    split = json.loads(split_path.read_text(encoding="utf-8")) if split_path.is_file() else {}
    skip = {2} if split else set()
    jobs = []   # (템플릿 시트, 옷 시트, 열, 행, 크기, [(칸, 이름)])
    for part in sorted({x["part"] for x in plan} - skip):
        jobs.append((f"전체프레임_{part}.png", f"전체프레임_{part}.png", t_cols, t_rows, t_size,
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
            if head_fit:   # 옷 칸을 템플릿 칸 키로 맞춘 뒤 머리(위 42%)를 템플릿 칸 머리에
                from scripts.silhouette import best_scale
                fit = template[index].shape[0] / image.shape[0]
                k *= fit * best_scale(_head(template[index]), _head(scaled(image, fit)), 0.85, 1.15, 61)
            out[name] = scaled(image, k) if abs(k - 1) > 0.005 else image
    return out


def redraw(folder: str, key: str, frames: dict[str, np.ndarray], outfit_dir: Path) -> dict[str, np.ndarray]:
    """REDRAWN 시트로 그 동작 프레임을 바꿈(예: 이안 걷기 v3 8장 — 템플릿 6장 대신)."""
    from scripts.build_dare_frames import guide_cells

    app_dir = APP_ROOT / folder
    for prefix, name, cols, rows, size, cells in REDRAWN.get((folder, key), []):
        cut = guide_cells(name, cols, rows, outfit_dir, size, loose=True)
        images = [cut[i] for i in cells]
        base_h = np.median([imread(p, cv2.IMREAD_UNCHANGED).shape[0] for p in app_dir.glob(f"{prefix}_*.png")])
        k = float(base_h / np.median([im.shape[0] for im in images]))
        frames = {n: v for n, v in frames.items() if not re.fullmatch(rf"{prefix}_\d+", n)}
        frames.update({f"{prefix}_{i}": scaled(im, k) for i, im in enumerate(images)})
    return frames


def harmonize_colors(frames: dict[str, np.ndarray], ref_name: str) -> dict[str, np.ndarray]:
    """시트마다 다른 밝기(바지 ΔE 2~17·머리 1.4~11, 기획 측정)를 이 옷의 stand_1(다문 입)에 — 어두운 톤(머리·바지·조끼)과
    중간 톤(피부·그림자) Lab 평균을 각각 맞춤. 흰 셔츠 같은 밝은 톤은 그대로(기준 = 그 옷의 서 있기)."""
    from scripts.build_starline_frames import DARK, MID, match_midtone

    ref = frames[ref_name]
    return {k: v if k == ref_name else match_midtone(match_midtone(v, ref, DARK, True), ref, MID, True)
            for k, v in frames.items()}


def main() -> None:
    for (folder, key), (name, ref) in OUTFITS.items():
        outfit_dir = ASSETS / folder / "의상" / name
        frames = harmonize_colors(redraw(folder, key, build(folder, outfit_dir, TEMPLATES.get((folder, key), DEFAULT_TEMPLATE)),
                                         outfit_dir), ref)
        from scripts.build_walk_v2 import FRAMES, OUTFIT_WALKS
        walk_dir = OUTFIT_WALKS.get((folder, key))
        if walk_dir is not None:   # 걷기 8장은 정리해 둔 PNG 그대로(색 맞추기·배율 없음)
            frames = {n: v for n, v in frames.items() if not re.fullmatch(r"walk_\d+", n)}
            frames.update({f"walk_{i}": imread(walk_dir / f"walk_{i}.png", cv2.IMREAD_UNCHANGED) for i in range(FRAMES)})
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
