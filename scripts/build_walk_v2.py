"""걷기 다시 그리기(기획 11-26, docs/characters/걷기_다시그리기.md) → 다섯 캐릭터 walk_0~7 + 착장 2벌 걷기 8장.

실행: uv run python -m scripts.build_walk_v2
- 원본: GPT 워크 묶음 zip의 칸별 PNG 8장(512×512, 진짜 투명, 바닥 y=480, 앱 걷기와 같은 오른쪽 보기 — 뒤집지 않음).
- 정리: 알파 ≥235 → 255, ≤20 → 0, 불투명 영역에서 2px 넘게 떨어진 반투명 → 0, 가장 큰 덩어리(+면적 2% 이상)만, 알파 경계로 꼭 맞춤.
- 배율('걷기 배율 규칙' 표): 지금 걷기 키 중앙값에 맞춘 뒤 머리(위 42%) 실루엣을 지금 walk_0에 맞춘 값 — 미리 곱한 알파로 축소(scaled).
- 색: 머리·피부는 다른 동작처럼 시트 색 맞추기(scripts/sheet_colors, 서 있기 기준). Starline은 옷 톤도 match_tones
  (대표색 거리가 지금 걷기보다 큼 9.0 vs 3.6).
- 착장(아리아 티셔츠·이안 넥타이 조끼): 기획이 앱 크기로 정리해 둔 docs/.../걷기_v2/walk_0~7.png를 그대로 복사.
"""
from __future__ import annotations

import zipfile

import cv2
import numpy as np

from scripts.build_dare_frames import ROOT, _tight, imread, imwrite, scaled

ASSETS = ROOT / "docs/characters/assets"
OUT = ROOT / "src/mabinogi_addon/assets/characters"
COMMON = ASSETS / "공용/걷기_GPT워크v2_세캐릭터.zip"
WALKS = {   # 캐릭터: (묶음 zip, zip 안 칸 폴더, 최종 배율)
    "아리아": (COMMON, "aria-walk-side-v2/frames", 0.7505),
    "다래": (COMMON, "darae-walk-side-v2/frames", 0.7117),
    "레나": (COMMON, "lena-walk-side-v2/frames", 0.7427),
    "Starline": (ASSETS / "Starline/SD/Starline_걷기_주머니_묶음.zip", "starline-pocket-walk/frames", 0.6819),
    "이안": (ASSETS / "이안/SD/이안_걷기_GPT워크_묶음.zip", "ian-walk-side/frames", 0.7073),
}
MATCH_COLORS = {"Starline"}
OUTFIT_WALKS = {
    ("이안", "vest_tie"): ASSETS / "이안/의상/넥타이 조끼/걷기_v2",
}
FRAMES = 8


def clean(cell: np.ndarray) -> np.ndarray:
    out = cell.copy()
    a = out[..., 3]
    a[a >= 235] = 255
    a[a <= 20] = 0
    solid = (a == 255).astype(np.uint8)
    near = cv2.dilate(solid, np.ones((5, 5), np.uint8)) > 0   # 불투명 영역에서 2px 안
    a[(a < 255) & ~near] = 0
    n, labels, stats, _ = cv2.connectedComponentsWithStats((a > 0).astype(np.uint8), connectivity=8)
    if n > 2:
        areas = stats[1:, cv2.CC_STAT_AREA]
        keep = 1 + np.flatnonzero(areas >= areas.max() * 0.02)
        a[~np.isin(labels, keep)] = 0
    out[a == 0, :3] = 0
    return _tight(out)


def read_frames(zip_path, folder: str) -> list[np.ndarray]:
    with zipfile.ZipFile(zip_path) as z:
        names = [f"{folder}/walk-{i:02d}.png" for i in range(1, FRAMES + 1)]
        return [cv2.imdecode(np.frombuffer(z.read(n), np.uint8), cv2.IMREAD_UNCHANGED) for n in names]


def build(name: str) -> list[np.ndarray]:
    zip_path, folder, factor = WALKS[name]
    frames = [scaled(clean(f), factor) for f in read_frames(zip_path, folder)]
    stand = imread(OUT / name / "stand_0.png", cv2.IMREAD_UNCHANGED)
    if name in MATCH_COLORS:   # 옷·망토 톤(채도·어두운·중간 Lab)을 서 있기에
        from scripts.build_starline_frames import match_tones
        frames = [match_tones(f, stand) for f in frames]
    from scripts.color_parts import PARTS
    if name in PARTS:   # 머리·피부는 다른 동작과 같은 시트 색 맞추기(서 있기 대비 ΔE<3)
        from scripts.sheet_colors import harmonize
        frames = harmonize({"walk": frames}, stand, PARTS[name])["walk"]
    return frames


def main() -> None:
    for name in WALKS:
        for i, frame in enumerate(build(name)):
            imwrite(OUT / name / f"walk_{i}.png", frame)
        print(name, [f.shape[0] for f in (imread(OUT / name / f"walk_{i}.png", cv2.IMREAD_UNCHANGED) for i in range(FRAMES))])
    for (name, outfit), src in OUTFIT_WALKS.items():
        dst = OUT / name / "outfits" / outfit
        for old in dst.glob("walk_*.png"):
            old.unlink()
        for i in range(FRAMES):
            imwrite(dst / f"walk_{i}.png", imread(src / f"walk_{i}.png", cv2.IMREAD_UNCHANGED))   # 그림 그대로(알파 0 RGB 0·압축만)
        print(name, outfit, "copied", FRAMES)


if __name__ == "__main__":
    main()
