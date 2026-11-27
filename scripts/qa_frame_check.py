"""QA 그림 검증 도구(사용자 지시 11-27 — '검증 도구로 이미지 튀는 부분이 없는지 확실히 검증').

앱에 들어간 펫 그림(assets/characters/<폴더>[/outfits/<옷>])을 사람이 축소 화면으로 훑는 대신 숫자로 검사한다.

  uv run --frozen python -m scripts.qa_frame_check Starline [--outfit KEY] [--source DIR] [--base REV] [--sheet out.png]

검사
1. 튐(동작 안·동작 사이): 앱이 그리는 자리(그림 아래 가운데 + anchors.json)에서 발 위치(알파 바닥 줄·바닥 띠 가운데)가
   이어지는 두 장 사이에 크게 바뀌는지. 동작 안 이어지는 장, 반복 동작의 끝→처음, 서기→동작 첫 장·동작 끝 장→다음 상태(next_map).
   끌기·떨어지기·착지·걷기는 원래 발이 움직이므로 가로 튐만 느슨하게 본다.
2. 머리 크기 튐: 이어지는 두 장의 머리(알파 상자 위 35%) 실루엣 맞춤 배율(scripts.silhouette.best_scale)이 ±5% 넘는지.
3. 원본과 다른 곳(--source): 같은 이름의 원본 그림을 앱 크기로 줄여 겹친 뒤 12×12 칸마다 평균 색 차 —
   한 칸이라도 크게 다르면 '원본과 다른 부분(합성·보정·얼룩)'. 원본 짝은 빌드 스크립트의 FOLDERS로 찾는다(Starline).
4. 이전 판과 다른 곳(--base REV): git REV의 같은 파일과 칸 비교 — 의도하지 않은 그림 변경 찾기.

결과: 문제마다 한 줄(어느 동작·어느 장·숫자), 없으면 '통과'. 문제가 있으면 종료 코드 1.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CHARS = ROOT / "src" / "mabinogi_addon" / "assets" / "characters"
BLOCK = 12
BLOCK_LIMIT = 8.0       # 칸 평균 색 차(0~255) — 원본 그대로 WebP는 최대 6.0, 입 합성 얼룩 판(6bd27072)은 30장 중 28장이 넘음(최대 37)
FOOT_Y_LIMIT = 4        # 저장 px — 발 바닥 줄이 이어지는 장 사이에 이보다 많이 바뀌면 튐
FOOT_X_LIMIT = 6        # 저장 px — 발 가운데
HEAD_LIMIT = 0.05       # 머리 배율 ±5%
MOVING = {"walk", "drag", "fall", "land"}   # 발이 원래 움직이는 동작(가로 튐만 느슨히, 세로는 안 봄)


def read(path: Path) -> np.ndarray | None:
    data = np.fromfile(str(path), np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED) if data.size else None
    if image is None or image.ndim != 3 or image.shape[2] != 4:
        return None
    return image


def read_rev(rev: str, path: Path) -> np.ndarray | None:
    rel = path.resolve().relative_to(ROOT).as_posix()
    out = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=ROOT, capture_output=True)
    if out.returncode or not out.stdout:
        return None
    image = cv2.imdecode(np.frombuffer(out.stdout, np.uint8), cv2.IMREAD_UNCHANGED)
    return image if image is not None and image.ndim == 3 and image.shape[2] == 4 else None


def frame_path(folder: Path, name: str) -> Path | None:
    for ext in (".png", ".webp"):
        if (folder / f"{name}{ext}").is_file():
            return folder / f"{name}{ext}"
    return None


@dataclass
class Shape:
    foot_y: float     # 그림 아래에서 알파 바닥 줄까지(저장 px) — 앱은 그림 아래를 발 자리로 그림
    foot_x: float     # 바닥 띠(아래 10%) 알파 가운데 − 그림 가운데
    head: np.ndarray  # 알파 상자 위 35%(BGRA)


def shape(image: np.ndarray, anchor: tuple[float, float]) -> Shape:
    alpha = image[..., 3] > 128
    rows = np.where(alpha.any(1))[0]
    h, w = alpha.shape
    if rows.size == 0:
        return Shape(0.0, 0.0, image[:1, :1])
    top, bottom = rows[0], rows[-1]
    band = alpha[max(top, bottom - max(2, (bottom - top) // 10)):bottom + 1]
    xs = np.where(band.any(0))[0]
    cols = np.where(alpha.any(0))[0]
    tight = image[top:bottom + 1, cols[0]:cols[-1] + 1]
    return Shape(foot_y=(h - 1 - bottom) - anchor[1],
                 foot_x=(xs.mean() if xs.size else w / 2) - w / 2 + anchor[0],
                 head=tight[:max(1, round(tight.shape[0] * 0.35))])


def block_diff(a: np.ndarray, b: np.ndarray) -> tuple[float, tuple[int, int]]:
    """같은 크기 두 그림 — 둘 중 하나라도 불투명한 곳의 12×12 칸 평균 색 차 최대값과 그 칸 위치."""
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    mask = ((a[..., 3] > 128) | (b[..., 3] > 128)).astype(np.float32)
    diff = np.abs(a[..., :3].astype(np.float32) - b[..., :3].astype(np.float32)).mean(2) * mask
    diff += np.abs(a[..., 3].astype(np.float32) - b[..., 3].astype(np.float32)) * 0.5
    h, w = diff.shape
    hh, ww = h // BLOCK * BLOCK, w // BLOCK * BLOCK
    if hh == 0 or ww == 0:
        return 0.0, (0, 0)
    blocks = diff[:hh, :ww].reshape(hh // BLOCK, BLOCK, ww // BLOCK, BLOCK).mean((1, 3))
    weight = mask[:hh, :ww].reshape(hh // BLOCK, BLOCK, ww // BLOCK, BLOCK).mean((1, 3))
    blocks = np.where(weight > 0.3, blocks, 0)
    i = np.unravel_index(int(np.argmax(blocks)), blocks.shape)
    return float(blocks[i]), (int(i[1] * BLOCK), int(i[0] * BLOCK))


def source_map(folder: str) -> dict[str, Path]:
    """앱 장 이름 → 기획 원본 파일(빌드 스크립트 표 그대로). 지금은 Starline 영상판만."""
    if folder != "Starline":
        return {}
    from scripts import build_starline_video as b
    src = Path(getattr(b, "SRC"))
    out: dict[str, Path] = {}
    for i in range(30):
        out[f"stand_{i}"] = src / f"stand_{i:02d}.png"
    for prefix, (sub, indices) in b.FOLDERS.items():
        for i in indices:
            out[f"{prefix}_{i}"] = src / sub / f"{i:02d}.png"
    walk = Path(getattr(b, "WALK_SRC"))
    for i in range(14):
        out[f"walk_{i}"] = walk / f"vwalk14_{i}.png"
    return {k: v for k, v in out.items() if v.is_file()}


def check(folder: str, outfit: str = "", source: Path | None = None, base: str | None = None,
          sheet: Path | None = None) -> list[str]:
    from mabinogi_addon.character import brain as br
    from mabinogi_addon.character import motions
    from scripts.silhouette import best_scale

    base_dir = CHARS / folder
    look = [base_dir / "outfits" / outfit, base_dir] if outfit else [base_dir]
    profile = br.PROFILES[folder]
    try:
        anchors = json.loads((base_dir / "anchors.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        anchors = {}
    # 저장 px 경계는 서기 키 285 기준 — 원본 크기로 저장한 캐릭터(frames.json standH, Starline 524)는 그만큼 늘림
    try:
        unit = float(json.loads((base_dir / "frames.json").read_text(encoding="utf-8"))["standH"]) / 285
    except (OSError, ValueError, KeyError, TypeError):
        unit = 1.0
    seqs: dict[str, list[str]] = {state: list(frames) for state, (frames, _t, _l) in profile.anims.items()}
    for m in motions.of(folder):
        seqs[f"motion:{m.key}"] = list(m.names())
    loops = {state for state, (_f, _t, loop) in profile.anims.items() if loop}

    cache: dict[str, tuple[np.ndarray, Path] | None] = {}

    def get(name: str):
        if name not in cache:
            path = next((p for p in (frame_path(d, name) for d in look) if p is not None), None)
            image = read(path) if path is not None else None
            cache[name] = (image, path) if image is not None else None
        return cache[name]

    shapes: dict[str, Shape] = {}
    info: list[tuple[str, str, str]] = []   # 원본 영상 이웃 장 — 앱이 만든 튐이 아니라 검사 대상 밖(원본 비교로 따로 봄)
    problems: list[str] = []
    flagged: list[tuple[str, str]] = []
    for state, names in seqs.items():
        for name in names:
            got = get(name)
            if got is None:
                problems.append(f"{state}: {name} 그림 없음")
                continue
            shapes[name] = shape(got[0], tuple(anchors.get(name, (0, 0))))

    def neighbours(a: str, b: str) -> bool:
        """원본 영상에서 바로 이웃한 두 장(같은 앞부분, 번호 차 1) — 그 사이 움직임은 그림 자체(영상)의 것."""
        pa, _, ia = a.rpartition("_")
        pb, _, ib = b.rpartition("_")
        return pa == pb and ia.isdigit() and ib.isdigit() and abs(int(ia) - int(ib)) == 1

    def compare(label: str, a: str, b: str, moving: bool) -> None:
        if a not in shapes or b not in shapes or a == b:
            return
        if neighbours(a, b):
            info.append((label, a, b))
            return
        sa, sb = shapes[a], shapes[b]
        dy, dx = abs(sa.foot_y - sb.foot_y), abs(sa.foot_x - sb.foot_x)
        if not moving and dy > FOOT_Y_LIMIT * unit:
            problems.append(f"{label}: {a}→{b} 발 높이 {dy:.0f}px 튐")
            flagged.append((a, b))
        if dx > (FOOT_X_LIMIT * 3 if moving else FOOT_X_LIMIT) * unit:
            problems.append(f"{label}: {a}→{b} 발 가로 {dx:.0f}px 튐")
            flagged.append((a, b))
        k = best_scale(sa.head, sb.head, 0.85, 1.15, 31)
        if abs(k - 1) > HEAD_LIMIT:
            problems.append(f"{label}: {a}→{b} 머리 크기 {k:.2f}배")
            flagged.append((a, b))

    stand_first = seqs.get("stand", [None])[0]
    for state, names in seqs.items():
        moving = state in MOVING
        for a, b in zip(names, names[1:]):
            compare(state, a, b, moving)
        if state in loops and len(names) > 1:
            compare(f"{state}(반복)", names[-1], names[0], moving)
        if state.startswith("motion:") or state in profile.idle_states or state in ("pet_in", "crouch", "sneeze"):
            compare(f"서기→{state}", stand_first, names[0], False)
        nxt = "stand" if state.startswith("motion:") else profile.next_map.get(state)
        if state == "sit_notice" and getattr(profile, "notice_holds", False):
            continue   # 앉아서 클릭 동안 그때 장 그대로·끝나면 반복 멈춘 자리부터(brain notice_holds) — 정해진 장 이음이 없음
        if nxt in seqs and nxt not in MOVING:
            compare(f"{state}→{nxt}", names[-1], seqs[nxt][0], False)

    if source is not None or folder == "Starline":
        pairs = source_map(folder)
        for name, src in sorted(pairs.items()):
            got = get(name)
            original = read(src)
            if got is None or original is None:
                continue
            value, (x, y) = block_diff(got[0], original)
            if value > BLOCK_LIMIT:
                problems.append(f"원본과 다름: {name} ↔ {src.relative_to(ROOT).as_posix()} 칸({x},{y}) 차 {value:.1f}")
                flagged.append((name, name))
    if base:
        for name in sorted(shapes):
            got = get(name)
            old = read_rev(base, got[1]) if got else None
            if got is None or old is None:
                continue
            value, (x, y) = block_diff(got[0], old)
            if value > BLOCK_LIMIT:
                problems.append(f"{base}와 다름: {name} 칸({x},{y}) 차 {value:.1f}")
                flagged.append((name, name))

    if sheet is not None and flagged:
        tiles = []
        for a, b in flagged[:24]:
            row = []
            for n in (a, b):
                g = get(n)
                img = g[0] if g else np.zeros((10, 10, 4), np.uint8)
                al = img[..., 3:4] / 255.0
                flat = (img[..., :3] * al + 255 * (1 - al)).astype(np.uint8)
                canvas = np.full((320, 240, 3), 255, np.uint8)
                fh, fw = flat.shape[:2]
                s = min(1.0, 300 / fh, 230 / fw)
                flat = cv2.resize(flat, (max(1, int(fw * s)), max(1, int(fh * s))))
                fh, fw = flat.shape[:2]
                canvas[315 - fh:315, (240 - fw) // 2:(240 - fw) // 2 + fw] = flat
                cv2.putText(canvas, n, (2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 200), 1)
                row.append(canvas)
            tiles.append(np.hstack(row))
        cv2.imencode(".png", np.vstack(tiles))[1].tofile(str(sheet))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="펫 그림 튐·원본 차이 검사")
    parser.add_argument("folder")
    parser.add_argument("--outfit", default="")
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--base", default=None)
    parser.add_argument("--sheet", type=Path, default=None)
    args = parser.parse_args()
    problems = check(args.folder, args.outfit, args.source, args.base, args.sheet)
    label = args.folder + (f"/{args.outfit}" if args.outfit else "")
    if not problems:
        print(f"{label}: 통과")
        return 0
    print(f"{label}: 문제 {len(problems)}건")
    for line in problems:
        print(" -", line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
