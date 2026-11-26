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
           ("레나", "lab"): ("연구실 차림", "stand_0"), ("다래", "frill_pajama"): ("프릴 잠옷 원피스", "stand_0"),
           ("이안", "guild_uniform"): ("길드 고위 정복", "stand_1"), ("아리아", "summer_dress"): ("가벼운 여름 드레스", "stand_0"),
           ("다래", "white_offshoulder"): ("하얀 오프숄더 프릴 원피스", "stand_0"), ("레나", "red_dress"): ("빨간 원피스", "stand_0")}
# 옷마다 템플릿(폴더, 열, 행, 시트 크기, 칸마다 머리 맞춤). 기본 = 옛 전체프레임(4×4, 960×1320), 키 비율만.
# 레나 연구실 차림(기획 11-26): 프레임표 v2(3×4, 930×1320, 테두리 없음, 새 걷기 8장 포함) — 옷 칸 키가 +1~5%로 들쭉날쭉하고
# 머리가 끌기·일어나기·웅크리기에서 크고 걷기 몇 장에서 작아, 칸마다 위 42% 실루엣으로 템플릿 머리에 맞춤(QA 11-25 규칙).
DEFAULT_TEMPLATE = ("전체프레임", 4, 4, (960, 1320), False)
TEMPLATES = {("레나", "lab"): ("전체프레임_v2", 3, 4, (930, 1320), True),
             ("다래", "frill_pajama"): ("전체프레임_v2", 3, 4, (930, 1320), True),
             # 호감도 100 옷 4벌(기획 11-26) — 다래·레나 일부 시트는 1053×1496으로 와서 템플릿 크기로 줄여 자름(cells_of size)
             ("이안", "guild_uniform"): ("전체프레임_v2", 4, 4, (960, 1320), True),
             ("아리아", "summer_dress"): ("전체프레임_v2", 4, 4, (996, 1320), "median"),   # 밀짚모자 — 머리 배율 중앙값으로 나눔
             ("다래", "white_offshoulder"): ("전체프레임_v2", 3, 4, (930, 1320), True),
             ("레나", "red_dress"): ("전체프레임_v2", 3, 4, (930, 1320), True)}
HEAD = 0.42
FACE_FIX = {("레나", "lab"): ("walk",)}
HALO_FIT = {"다래": ("drag",)}
# 다래 하얀 오프숄더 drag_0만 다리 편 서 있는 자세로 그려져(키 282 vs 249~258, 몸통 폭 198 vs 179~191) 잡을 때 몸이 커짐 →
# 이번 배포는 drag_1 그림으로 대신(반복 = drag_1, drag_1, drag_2, drag_3, fall도 drag_1). 새 drag_0은 사용자에게 물어 따로.
FRAME_COPY = {("다래", "white_offshoulder"): (("drag_1", "drag_0"),),
              }
# 기획이 다시 그려 앱 크기로 맞춘 칸(배경 정리·기본 옷 같은 칸 키 × 머리 맞춤, 11-26) — 템플릿 칸 대신 그대로 넣고 색 맞추기만 같이
OVERRIDES = {
    ("이안", "guild_uniform"): ("모션별/다시_앱크기", tuple(f"drag_{i}" for i in range(4))),
    ("아리아", "tshirt"): ("모션별/다시_앱크기", ("drag_0", "drag_1", "land_0", "land_1", "land_2")),
}
# 그림 후처리(scripts/outfit_fixes) — 옷 → 할 일
FIXES = {("이안", "guild_uniform"): ("one_coat_line",), ("이안", "vest_tie"): ("vest_badge",)}   # 옷 그림 끌기 칸마다 몸 크기가 달라(후광 폭 142→163) 후광 폭으로 칸 배율을 맞춤
HALO_BAND = 0.09                 # 맨 위 9% 띠 = 날개 달린 후광
# 머리 위 장식(밀짚모자)으로 머리 실루엣을 못 쓰는 옷 → 같은 템플릿 자세 옷(티셔츠)의 같은 칸 '모자 아래 띠(키 25~55%) 폭'에 맞춤
REF_FIT = {("아리아", "summer_dress"): ("tshirt", ("pet",))}
BAND = (0.25, 0.55)   # 옷 그림 걷기 얼굴 옆선이 무너진 옷 → scripts/outfit_face_fix
# 템플릿 뒤에 다시 그려 받은 시트(가이드 방식) — (키, 파일, 열, 행, 가이드 크기, 쓸 칸). 배율 = 앱 기본 프레임 키 중앙값 ÷ 칸 키 중앙값
REDRAWN: dict = {}   # 걷기는 기획이 앱 크기로 정리한 걷기_v2/walk_0~7.png를 그대로(11-26, scripts/build_walk_v2.OUTFIT_WALKS)
MOTION_NAMES = {"옷매무새(25)": "motion_tidy", "차(75)": "motion_tea", "물주기(25)": "motion_water", "화관(75)": "motion_wreath",
                "마법서(25)": "motion_grimoire", "공중앉기(75)": "motion_float_sit",
                "양인형(25)": "motion_sheep_doll", "비눗방울(75)": "motion_bubbles"}


def frame_name(raw: str) -> str:
    """칸 목록 이름 → 저장 이름(motion:옷매무새(25)_3 → motion_tidy_3)."""
    m = re.fullmatch(r"motion:(.+)_(\d+)", raw)
    return f"{MOTION_NAMES[m.group(1)]}_{m.group(2)}" if m else raw


def cells_of(folder: Path, name: str, cols: int, rows: int, size: tuple[int, int]) -> list:
    return guide_cells(name, cols, rows, folder, size)


def group_scales(pending, head_fit) -> list[tuple[str, np.ndarray, float]]:
    """칸마다 (이름, 그림, 키 배율, 칸 머리 배율) → (이름, 그림, 최종 배율).
    한 동작(걷기·모션·말하기 세트·앉기 등) 안에서는 머리 배율 하나(그 묶음 칸들의 중앙값) — 칸마다 다르면 걷는 동안 크기가
    들쭉날쭉(QA 11-26 아리아 여름 드레스 걷기 298~312). 묶음 사이 머리 맞춤은 그대로.
    "median": 머리 위에 새 장식(아리아 여름 드레스 밀짚모자)이 있어 위 42% 실루엣이 커 보이는 옷 — 머리 배율 ÷ 전 칸 중앙값
    (모자 몫을 빼고, 0.9~1.1로 자름 — 기획 11-26)."""
    if not pending:
        return []
    middle = float(np.median([h for *_, h in pending])) if head_fit == "median" else 1.0
    groups: dict[str, list[float]] = {}
    for name, _image, _k, head in pending:
        groups.setdefault(group_of(name), []).append(head)
    out = []
    for name, image, k, head_cell in pending:
        # 모션(호감도 보상)은 칸마다 그대로(사용자 11-26 '모션은 이번에 건드리지 말 것')
        own = name.startswith("motion_")
        h = (head_cell if own else float(np.median(groups[group_of(name)]))) / middle
        if head_fit == "median":
            h = min(1.1, max(0.9, h))
        out.append((name, image, k * h))
    return out


def band_width(frame: np.ndarray) -> float:
    """키 25~55% 띠(모자 아래 얼굴·머리카락)의 알파(>128) 가로 폭."""
    h = frame.shape[0]
    band = frame[round(h * BAND[0]):round(h * BAND[1]), :, 3] > 128
    xs = np.where(band.any(axis=0))[0]
    return float(xs.max() - xs.min() + 1) if xs.size else float(frame.shape[1])


def halo_width(frame: np.ndarray) -> float:
    """다래 후광 폭 — 맨 위 HALO_BAND 띠의 알파(>128) 가로 폭."""
    band = frame[:max(1, round(frame.shape[0] * HALO_BAND)), :, 3] > 128
    xs = np.where(band.any(axis=0))[0]
    return float(xs.max() - xs.min() + 1) if xs.size else float(frame.shape[1])


def group_of(name: str) -> str:
    """프레임 이름 → 같은 애니메이션 묶음(walk_3 → walk, motion_water_2 → motion_water, talk_a_m1_0 → talk_a,
    talk_base_0·talk_happy_1 → talk, sit_doze_0 → sit)."""
    parts = name.split("_")
    if parts[0] == "motion" and len(parts) > 2:
        return "_".join(parts[:-1])
    if parts[0] == "talk" and len(parts) > 2 and len(parts[1]) == 1:
        return f"talk_{parts[1]}"
    return parts[0]


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
    pending = []   # (이름, 그림, 키 배율, 머리 배율) — 머리 배율 중앙값으로 나눌 옷(밀짚모자)은 다 모은 뒤 정함
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
                pending.append((name, image, k * fit, best_scale(_head(template[index]), _head(scaled(image, fit)), 0.85, 1.15, 61)))
                continue
            out[name] = scaled(image, k) if abs(k - 1) > 0.005 else image
    for name, image, k in group_scales(pending, head_fit):
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
        built = redraw(folder, key, build(folder, outfit_dir, TEMPLATES.get((folder, key), DEFAULT_TEMPLATE)), outfit_dir)
        if (folder, key) in OVERRIDES:
            sub, names = OVERRIDES[(folder, key)]
            for name in names:
                built[name] = imread(outfit_dir / sub / f"{name}.png", cv2.IMREAD_UNCHANGED)
        frames = harmonize_colors(built, ref)
        from scripts.build_walk_v2 import FRAMES, OUTFIT_WALKS
        walk_dir = OUTFIT_WALKS.get((folder, key))
        if walk_dir is not None:   # 걷기 8장은 정리해 둔 PNG 그대로(색 맞추기·배율 없음)
            frames = {n: v for n, v in frames.items() if not re.fullmatch(r"walk_\d+", n)}
            frames.update({f"walk_{i}": imread(walk_dir / f"walk_{i}.png", cv2.IMREAD_UNCHANGED) for i in range(FRAMES)})
        for src, dst in FRAME_COPY.get((folder, key), ()):   # 다른 자세로 그려진 칸을 같은 묶음 다른 칸으로(임시, QA 11-26)
            frames[dst] = frames[src].copy()
        if (folder, key) in FIXES:
            from scripts import outfit_fixes
            for fix in FIXES[(folder, key)]:
                frames = getattr(outfit_fixes, f"apply_{fix}")(frames, folder, key)
        if folder in HALO_FIT:   # 다래 끌기(QA 11-26): 후광(모양이 안 변하는 물체) 폭을 기본 다래 같은 칸 × (이 옷/기본 서 있기)에
            for name in [n for n in frames if group_of(n) in HALO_FIT[folder]]:
                base = imread(APP_ROOT / folder / f"{name}.png", cv2.IMREAD_UNCHANGED)
                base_stand = imread(APP_ROOT / folder / "stand_0.png", cv2.IMREAD_UNCHANGED)
                target = halo_width(base) * halo_width(frames["stand_0"]) / halo_width(base_stand)
                frames[name] = scaled(frames[name], target / halo_width(frames[name]))
        if (folder, key) in REF_FIT:   # 아리아 여름 드레스 쓰다듬기(QA 11-26): 모자 아래 띠 폭을 티셔츠 같은 칸 × 서 있기 비에
            other, groups_fit = REF_FIT[(folder, key)]
            ref_dir = APP_ROOT / folder / "outfits" / other
            ratio = band_width(frames["stand_0"]) / band_width(imread(ref_dir / "stand_0.png", cv2.IMREAD_UNCHANGED))
            for name in [n for n in frames if group_of(n) in groups_fit]:
                ref = imread(ref_dir / f"{name}.png", cv2.IMREAD_UNCHANGED)
                frames[name] = scaled(frames[name], band_width(ref) * ratio / band_width(frames[name]))
        if (folder, key) in FACE_FIX:   # 걷기 얼굴 옆선(QA 11-26) — 기본 걷기 얼굴을 옮겨 붙이고 옷의 안경만 다시
            from scripts.outfit_face_fix import fix_face
            for name in [n for n in frames if group_of(n) in FACE_FIX[(folder, key)]]:
                base = imread(APP_ROOT / folder / f"{name}.png", cv2.IMREAD_UNCHANGED)
                frames[name] = fix_face(frames[name], base, frames["stand_0"])
            # 머리는 걷는 동안 움직이지 않는 부분 — 기준 장(walk_0) 머리 하나로 맞춤(장마다 땋은 머리·하이라이트가 달라 지글거림, QA 11-26)
            from scripts.outfit_face_fix import unify_head
            walk = sorted((n for n in frames if group_of(n) == "walk"), key=lambda n: int(n.rsplit("_", 1)[1]))
            for name, image in zip(walk, unify_head([frames[n] for n in walk])):
                frames[name] = image
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
