"""다래 SD 시트 → 펫 프레임 PNG(캐릭터 알파, docs/character-pet-spec.md 2절·docs/characters/다래.md).

실행: uv run python -m scripts.build_dare_frames
- 시트는 투명 배경이라 빈 줄·빈 칸으로 프레임을 자동 분리한다(4면도 정면만 눈금선 때문에 수동 자르기).
- 크기는 '서 있는 키'로 맞춘다(다래.md 크기 맞추기 주의): 서 있기 프레임 키 = STAND_H.
  앉은 계열(무릎베개·자다 깨기)은 웅크리기 시트의 쪼그림 폭에 맞추고, 일어나기는 쪼그림 폭→서 있는 키로 배율을 점점 바꾼다.
  착지·세 가지 자세는 같은 크기의 시트(724×2172)라 세 가지 자세의 서 있는 프레임 배율을 함께 쓴다.
- 결과: src/mabinogi_addon/assets/characters/다래/<동작>_<번호>.png (발 밑 가운데 기준으로 앱이 그림).
  저장 키 STAND_H = 285px(배율 150%에서 190px×1.5 — 100%는 앱이 줄여 그림).
"""
from __future__ import annotations

import pathlib
import sys

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from mabinogi_addon.image_io import imread  # noqa: E402
from mabinogi_addon.image_io import write_sprite as imwrite  # noqa: E402  캐릭터 그림은 작게(알파 0 RGB 0·압축 9)

SHEETS = ROOT / "docs/characters/assets/다래/SD"
OUT = ROOT / "src/mabinogi_addon/assets/characters/다래"
STAND_H = 285
ALPHA_MIN = 40


def _segments(on: np.ndarray, gap: int) -> list[tuple[int, int]]:
    segs, i, n = [], 0, len(on)
    while i < n:
        if not on[i]:
            i += 1
            continue
        j = i
        while j < n and (on[j] or on[j:j + gap].any()):
            j += 1
        if j - i >= 8:
            segs.append((i, j))
        i = j
    return segs


def split(image: np.ndarray) -> list[np.ndarray]:
    """빈 줄 → 줄마다 빈 칸으로 자른 프레임(읽는 순서). 각 프레임은 알파 경계로 꼭 맞게."""
    alpha = image[..., 3] > ALPHA_MIN
    frames = []
    for r0, r1 in _segments(alpha.sum(1) > 2, gap=6):
        for c0, c1 in _segments(alpha[r0:r1].sum(0) > 2, gap=10):
            frames.append(_tight(image[r0:r1, c0:c1]))
    return frames


def head_width(image: np.ndarray) -> int:
    """머리 폭 = 위 30% 구간의 알파 가로 폭(사용자 11-24 '이안 머리 크기가 동작마다 달라짐' — 시트마다 등신이 달라
    서 있는 키로 맞추면 머리가 커졌다 작아짐 → 이안·아리아는 시트 배율을 이 값으로 맞춤. 다래는 헤일로·뿔 때문에 안 씀)."""
    band = image[: max(1, int(image.shape[0] * 0.3)), :, 3] > ALPHA_MIN
    cols = np.where(band.any(0))[0]
    return int(cols.max() - cols.min() + 1) if cols.size else 0


def _tight(image: np.ndarray) -> np.ndarray:
    ys, xs = np.where(image[..., 3] > ALPHA_MIN)
    return image[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def front_view() -> np.ndarray:
    """4면도 정면(눈금선 102~103행·바닥선 623행부터, 정면과 45도 사이 빈 칸 655~668열 — 11-24 측정)."""
    image = imread(SHEETS / "다래 SD 캐릭터 4면도 모델 시트.png", cv2.IMREAD_UNCHANGED).copy()
    crop = image[:623, 150:660].copy()
    for y in (102, 103):  # 점선: 위·아래가 비어 있는 칸만 지운다(헤일로·머리와 겹친 곳은 그대로)
        row = crop[y]
        empty = (crop[y - 3, :, 3] <= ALPHA_MIN) & (crop[y + 3, :, 3] <= ALPHA_MIN)
        row[empty] = 0
    # 왼쪽 '2등신' 화살표(세로선)를 떼려고 가장 큰 덩어리만 남긴다
    mask = (crop[..., 3] > ALPHA_MIN).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(mask, np.ones((5, 5), np.uint8)))
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    crop[labels != biggest] = 0
    return _tight(crop)


def scaled(frame: np.ndarray, factor: float) -> np.ndarray:
    h, w = frame.shape[:2]
    size = (max(1, round(w * factor)), max(1, round(h * factor)))
    # 미리 곱한 알파로 줄여야 가장자리에 검은 테가 안 생긴다
    rgb = frame[..., :3].astype(np.float32) * (frame[..., 3:] / 255.0)
    small = cv2.resize(np.dstack([rgb, frame[..., 3:].astype(np.float32)]), size, interpolation=cv2.INTER_AREA)
    a = small[..., 3:]
    out_rgb = np.where(a > 0, small[..., :3] / np.maximum(a, 1e-6) * 255.0, 0)
    return np.dstack([np.clip(out_rgb, 0, 255), np.clip(a, 0, 255)]).astype(np.uint8)


def grid(image: np.ndarray, cols: int, rows: int) -> list[np.ndarray]:
    """같은 칸으로 자르기(읽는 순서) — 칸마다 알파 경계로 꼭 맞게. 그림끼리 닿아 빈 줄로 안 나뉘는 시트용."""
    h, w = image.shape[:2]
    out = []
    for r in range(rows):
        for c in range(cols):
            cell = image[r * h // rows:(r + 1) * h // rows, c * w // cols:(c + 1) * w // cols]
            out.append(_tight(cell))
    return out


def guide_cells(name: str, cols: int, rows: int, folder=None, size: tuple[int, int] | None = None,
                loose: bool = False) -> list[np.ndarray]:
    """가이드 방식 시트(기획 11-25 — 칸마다 기준 그림·분홍 높이선·파란 칸 테두리): 같은 칸으로 나눠(가장자리 6px 안쪽)
    분홍(R>170·B>170·G<110)·파란(R<90·G>120·B>190) 선을 지우고, 가장 큰 알파 덩어리의 2% 이상만 남겨 꼭 맞춤."""
    image = sheet_image(name, folder)
    if size is not None:   # 받은 그림이 가이드와 크기가 다르면 가이드 크기로(칸이 가이드 칸과 맞게)
        image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    b, g, r = (image[..., i].astype(np.int16) for i in range(3))
    lines = ((r > 170) & (b > 170) & (g < 110)) | ((r < 90) & (g > 120) & (b > 190))
    if loose:   # 줄인 그림은 선 가장자리가 옷 색과 섞여 옅은 자홍이 남음(Starline 말하기 시작 v2) — R·B가 G보다 크게 높은 자홍
        lines |= (r - g > 60) & (b - g > 50) & (np.abs(r - b) < 70) & (g < 150)
    image = image.copy()
    image[lines, 3] = 0
    h, w = image.shape[:2]
    out = []
    for row in range(rows):
        for col in range(cols):
            cell = image[row * h // rows + 6:(row + 1) * h // rows - 6, col * w // cols + 6:(col + 1) * w // cols - 6].copy()
            count, labels, stats, _ = cv2.connectedComponentsWithStats((cell[..., 3] > 20).astype(np.uint8))
            if count > 1:
                areas = stats[1:, cv2.CC_STAT_AREA]
                keep = np.zeros(count, bool)
                keep[1:] = areas >= areas.max() * 0.02
                cell[~keep[labels], 3] = 0
            out.append(_tight(cell) if (cell[..., 3] > 20).any() else None)   # 빈 칸 = None
    return out


def sheet_image(name: str, folder=None) -> np.ndarray:
    from scripts.build_aria_frames import clean
    return clean(imread((folder or SHEETS) / name, cv2.IMREAD_UNCHANGED))


def sheet(name: str) -> list[np.ndarray]:
    return split(imread(SHEETS / name, cv2.IMREAD_UNCHANGED))


def build() -> dict[str, list[np.ndarray]]:
    by_height = lambda frames, h: STAND_H * h / np.median([f.shape[0] for f in frames])  # noqa: E731
    out: dict[str, list[np.ndarray]] = {}
    stand = front_view()
    out["stand"] = [scaled(stand, STAND_H / stand.shape[0])]
    # 걷기·착지·일어나기 새 시트(기획 11-25 '걸을 때 머리 커짐'·'떨어진 뒤 머리가 작았다 커짐'): 가이드 방식 —
    # 시트마다 기준 칸(서 있기와 같은 그림) 키 = 서 있기 키가 되는 배율 하나
    walk = guide_cells("다래_걷기_v2.png", 4, 2)   # 0·4 = 기준, 1·2·3 → 5·6·7 = 걷기
    out["walk"] = [scaled(walk[i], STAND_H / walk[0].shape[0]) for i in (1, 2, 3, 5, 6, 7)]
    surprise = sheet("깜짝 놀란 고딕 천사 소녀 애니메이션 시트.png")
    out["surprise"] = [scaled(f, by_height(surprise, 1.0)) for f in surprise]
    pet = sheet("부끄러운 치비 천사 악마 스티커 세트.png")
    out["pet"] = [scaled(f, by_height(pet, 1.0)) for f in pet]
    drag = sheet("움직이는 꼬마 천사 드래그 포즈 시트.png")
    out["drag"] = [scaled(f, by_height(drag, 1.0)) for f in drag]
    for key, name in (("land", "다래_착지_v2.png"), ("getup", "다래_일어나기_v2.png")):
        cells = guide_cells(name, 4, 1)   # 0 = 기준, 1·2·3 = 동작
        out[key] = [scaled(f, STAND_H / cells[0].shape[0]) for f in cells[1:]]
    crouch = sheet("졸린 천사 캐릭터의 웅크리기 3단계.png")
    sc = STAND_H / crouch[0].shape[0]
    out["crouch"] = [scaled(f, sc) for f in crouch]
    crouch_w = crouch[2].shape[1] * sc
    sit = sheet("잠든 무릎베개 포즈 치비 스프라이트 시트.png")  # 읽는 순서: 졸림·알아챔·꾸벅 졸기·반쯤 뜸
    ss = crouch_w / sit[0].shape[1]
    names = ("sit_drowsy", "sit_notice", "sit_doze", "sit_half")
    for key, frame in zip(names, sit):
        out[key] = [scaled(frame, ss)]
    rise = sheet("졸린 천사 캐릭터의 상승 애니메이션.png")
    r0, r2 = crouch_w / rise[0].shape[1], STAND_H / rise[2].shape[0]
    out["rise"] = [scaled(f, r) for f, r in zip(rise, (r0, (r0 + r2) / 2, r2))]
    # 말하기(사용자 11-24 다시 만들기): 보통·설명·강조·깜빡임은 새 시트 입만 바꾸기(build_talk_frames),
    # 생각(턱에 손)·기쁨(웃음)은 예전 시트 그대로
    mood = sheet("세 가지 표정의 천사 소녀들.png")  # 가리키며 설명(안 씀)·턱에 손 생각·눈 감고 웃음
    for key, frame in zip(("talk_think", "talk_smile"), mood[1:]):
        out[key] = [scaled(frame, by_height(mood, 1.0))]
    from scripts.build_talk_frames import talk_frames
    out.update(talk_frames("다래"))
    wake = sheet("잠에서 깨어나는 꼬마 천사 악마_sprite.sheet.png")
    out["wake"] = [scaled(f, crouch_w / wake[0].shape[1]) for f in wake]
    # 구석에서 엎드려 자기(기획 11-25 기본 동작): 머리끼리 닿아 빈 줄로 안 나뉨 → 3×3 같은 칸으로 자른 뒤 칸마다 꼭 맞게.
    # 0 무릎 안고 졺(= 앉아 있기 자세) → 0번 폭을 쪼그림 폭에 맞춘 배율 하나
    sleep = grid(sheet_image("다래의 포근한 수면 루프.png", ROOT / "docs/characters/assets/다래"), 3, 3)
    from scripts.silhouette import best_scale   # 0번(무릎 안고 졺) 실루엣을 꾸벅 졸기에 맞춤(QA 11-25 — 폭 맞춤은 0.9배로 작음)
    k = crouch_w / sleep[0].shape[1]
    k *= best_scale(out["sit_doze"][0], scaled(sleep[0], k))
    out["sleep"] = [scaled(f, k) for f in sleep]
    # 시트 색 맞추기(사용자 11-24): 크림 머리·얼굴을 서 있기 색에(scripts/sheet_colors), 입만 합성은 base 차이 그대로
    from scripts.color_parts import PARTS
    from scripts.sheet_colors import harmonize
    groups = {("talk_m1", 0): ("talk_base", 0), ("talk_m2", 0): ("talk_base", 0)}
    # 색 맞추기 기준은 예전 정면 서 있기 그대로(다른 그림 색이 바뀌지 않게) — 그 뒤 서 있기를 일어나기 끝 장으로(사용자 11-25
    # '착지하고 서 있을 때가 더 이쁨' — 일어나기 v2 4번째 칸, 일어나기 끝 = 서 있기라 이어짐도 매끄러움)
    out = harmonize(out, out["stand"][0], PARTS["다래"], groups)
    out["stand"] = [out["getup"][-1].copy()]
    return out


EXPECTED = {"stand": 1, "walk": 6, "surprise": 2, "pet": 6, "drag": 4, "land": 3, "getup": 3, "crouch": 3,
            "sit_drowsy": 1, "sit_notice": 1, "sit_doze": 1, "sit_half": 1, "rise": 3, "wake": 4, "sleep": 9,
            "talk_think": 1, "talk_smile": 1, "talk_base": 1, "talk_m1": 1, "talk_m2": 1, "talk_emph": 1,
            "talk_emph2": 1, "talk_blink": 1, "talk_mid": 1}


def main() -> None:
    frames = build()
    for key, count in EXPECTED.items():
        if len(frames[key]) != count:
            raise SystemExit(f"{key}: 프레임 {len(frames[key])}개(기대 {count}) — 시트가 바뀌었나요?")
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        if old.name not in ("card.png", "frame.png"):   # 카드·카드 테두리(build_card_frames)는 남김
            old.unlink()
    for key, items in frames.items():
        for i, frame in enumerate(items):
            imwrite(OUT / f"{key}_{i}.png", frame)
            print(f"{key}_{i}: {frame.shape[1]}×{frame.shape[0]}")


if __name__ == "__main__":
    main()
