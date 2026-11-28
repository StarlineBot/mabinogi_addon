"""다래 영상판 프레임(기획 11-28 — docs/status.md '다래 영상판 원본크기·DEV 넘김', 사용자 지시 '다래 레나까지 한번에').

실행: uv run python -m scripts.build_dare_video
- 소스: docs/characters/assets/다래/영상/원본크기/ — 기획이 Starline 원본크기와 같은 px 체계로 만든 투명 PNG(서 있기 상자 키 412 =
  Starline × 0.787), 0.1초 간격. 동작 폴더마다 30장이 같은 상자(카메라 고정) — 장마다 다시 맞추지 않고 상자째 놓음.
- 그림은 원본 그대로(WebP 화질 90, 말하기 장만 무손실). 말하기만 Starline처럼 입 다문 몸(0번)에 작은 입(25번)·큰 입(26번)을 얼굴로 맞춰 붙임.
- 놓는 자리(anchors.json, 저장 px): 그 동작의 기준 장(서 있는 장) 발이 서 있기(stand_00) 발 자리에 오게. 엎드려 자기는 첫 장이
  구석 졸기 끝 장과 같은 자세 → 그 장 자리에 겹치게(알파 겹침이 가장 큰 자리).
- 기본 옷만 영상판. 착장(outfits/) 그림·card.png·frame.png·frame.json·lines.json은 그대로 두고, 예전 기본 옷 PNG는 지움.
"""
from __future__ import annotations

import json

import cv2
import numpy as np

from scripts.build_dare_frames import imread
from scripts.build_outfit_frames import APP_ROOT, ASSETS

SRC = ASSETS / "다래" / "영상" / "원본크기"
OUT = APP_ROOT / "다래"
KEEP = {"card.png", "frame.png", "frame.json", "lines.json"}
WEBP_QUALITY = 90
# 앱 이름 앞부분 → (소스 폴더, 쓸 장 번호, 기준 장 — 그 장 발을 서 있기 발 자리에)
FOLDERS = {
    "walk": ("W_걷기", range(15, 29), None),          # 오른쪽 보는 옆모습(왼쪽은 창이 뒤집음), 15~28 반복
    "surprise": ("1_놀람", range(30), 0),
    "pet": ("2_쓰다듬기", range(30), 0),
    "drag": ("3_끌기", range(30), 0),
    "land": ("4_착지", range(3, 30), 29),             # 3 = 떨어지는 한 장(1·2번은 머리·헤일로가 화면 위로 잘림)
    "crouch": ("5_구석졸기", range(28), 0),           # 0~20 웅크리기, 21~27 졸기 반복
    "sleep": ("6_엎드려자기", range(28), "crouch"),   # 첫 장 = 구석 졸기 끝 장 자세 → 그 장 자리에
    "sleepup": ("7B_엎드려깨기", range(30), 29),
    "wake": ("7_깨기", range(30), 29),                # 앉아 졸다 깨기·일어나기 모두 0~29
    "motion_sheep_doll": ("9_양인형", range(30), 0),
    "motion_bubbles": ("10_비눗방울", range(30), 0),
}
# 그리기 배율(그림 파일은 그대로 — Starline 착지와 같은 방식): 원본크기는 서 있는 장 머리로 맞춰 앉은 자세에선 7_깨기가 5_구석졸기보다
# 약 3.5% 크게 찍힘(뿔·헤일로 폭 223 → 231) → 깨기·일어나기를 0.98로: 졸기 → 깨기 첫 장 0.97~0.98, 깨기 끝 → 서기 머리 0.98·키 0.973
# (두 끝 다 통과하는 값은 0.98뿐 — 기획 11-28 DEV 질문 답)
DRAW_SCALE = {"wake": 0.98}
CROUCH_END = 29                 # 구석 졸기 끝 장(엎드려 자기 첫 장과 같은 자세)
TALK = "8_말하기"
TALK_BODY = 0                   # 입 다문 장 = talk_base(몸)
TALK_MOUTH = {"m1": 25, "m2": 26}   # 작은 입·큰 입
TALK_PICK = {"mid": 3, "emph": 11, "emph2": 8}   # 사이(팔 내리는 중)·강조(손 올려 입 벌림)·완화(손 가슴)
MOUTH_BOX = (146, 194, 32, 24)  # (x, y, w, h) 0번 입 둘레(저장 px)
EYES_BOX = (115, 172, 90, 26)   # 얼굴 맞춤 기준(눈 줄)


def _src(folder: str, index: int) -> np.ndarray:
    image = imread(SRC / folder / f"{index:02d}.png", cv2.IMREAD_UNCHANGED)
    if image is None:
        raise SystemExit(f"{folder}/{index:02d}.png가 없어요")
    return image


def _shift(src: np.ndarray, base: np.ndarray, eyes_box=None) -> tuple[int, int]:
    """src 눈 줄을 base에서 찾아 (dx, dy) — src 좌표 + 이 값 = base 좌표."""
    x, y, w, h = eyes_box or EYES_BOX
    g = lambda im: cv2.cvtColor(np.ascontiguousarray(im[..., :3]), cv2.COLOR_BGR2GRAY)   # noqa: E731
    t = g(src)[y:y + h, x:x + w]
    pad = 12
    area = g(base)[y - pad:y + h + pad, x - pad:x + w + pad]
    _, _, _, (bx, by) = cv2.minMaxLoc(cv2.matchTemplate(area, t, cv2.TM_CCOEFF_NORMED))
    return bx - pad, by - pad


def mouth_on(base: np.ndarray, src: np.ndarray, mouth_box=None, eyes_box=None) -> np.ndarray:
    """base 몸에 src 입만 — 입 둘레 타원(가장자리 흐림)으로 섞음(Starline build_starline_video.mouth_on과 같은 방식).
    상자는 이 모듈 값(다래), 다른 캐릭터(레나 build_lena_video)는 넘겨서."""
    dx, dy = _shift(src, base, eyes_box)
    x, y, w, h = mouth_box or MOUTH_BOX
    sx, sy = x - dx, y - dy             # src에서 base 입 자리에 해당하는 곳
    patch = src[sy:sy + h, sx:sx + w].astype(np.float32)
    mask = np.zeros((h, w), np.float32)
    cv2.ellipse(mask, (w // 2, h // 2), (w // 2 - 4, h // 2 - 4), 0, 0, 360, 1.0, -1)
    mask = cv2.GaussianBlur(mask, (7, 7), 0)[..., None]
    out = base.astype(np.float32)
    region = out[y:y + h, x:x + w]
    out[y:y + h, x:x + w] = region * (1 - mask) + patch * mask
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def foot(image: np.ndarray) -> tuple[float, float]:
    """(그림 아래 → 알파 바닥 줄 px, 바닥 띠(아래 10%) 가운데 − 그림 가운데) — scripts.qa_frame_check.shape와 같은 잼."""
    alpha = image[..., 3] > 128
    rows = np.where(alpha.any(1))[0]
    h, w = alpha.shape
    top, bottom = rows[0], rows[-1]
    band = alpha[max(top, bottom - max(2, (bottom - top) // 10)):bottom + 1]
    xs = np.where(band.any(0))[0]
    return float(h - 1 - bottom), float(xs.mean() - w / 2)


def _overlap_anchor(image: np.ndarray, ref: np.ndarray, ref_anchor: tuple[int, int]) -> tuple[int, int]:
    """image를 ref(ref_anchor로 놓인)에 알파가 가장 많이 겹치는 자리 — 둘 다 아래 가운데 기준 오프셋."""
    a = (image[..., 3] > 128).astype(np.uint8)
    b = (ref[..., 3] > 128).astype(np.uint8)
    best, where = -1.0, (0, 0)
    pad = 60
    hb, wb = b.shape
    canvas = np.zeros((hb + 2 * pad + 200, wb + 2 * pad + 200), np.uint8)
    H, W = canvas.shape
    # ref를 바닥 가운데(W/2, H-pad) + ref_anchor에 놓음
    rx, ry = W // 2 - wb // 2 + ref_anchor[0], H - pad - hb + ref_anchor[1]
    canvas[ry:ry + hb, rx:rx + wb] = b
    ha, wa = a.shape
    for dy in range(-40, 41, 2):
        for dx in range(-40, 41, 2):
            x0, y0 = W // 2 - wa // 2 + dx, H - pad - ha + dy
            inter = float((canvas[y0:y0 + ha, x0:x0 + wa] & a).sum())
            union = float(a.sum() + b.sum() - inter)
            if inter / union > best:
                best, where = inter / union, (dx, dy)
    return where


def frames() -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {f"stand_{i}": imread(SRC / f"stand_{i:02d}.png", cv2.IMREAD_UNCHANGED) for i in range(30)}
    for prefix, (folder, indices, _ref) in FOLDERS.items():
        out.update({f"{prefix}_{i}": _src(folder, i) for i in indices})
    body = _src(TALK, TALK_BODY)
    out["talk_base_0"] = body
    out["talk_blink_0"] = body   # 영상에 말하며 깜빡이는 장이 없음 — base 그대로(Starline과 같음)
    for key, index in TALK_MOUTH.items():
        out[f"talk_{key}_0"] = mouth_on(body, _src(TALK, index))
    out.update({f"talk_{key}_0": _src(TALK, index) for key, index in TALK_PICK.items()})
    missing = [n for n, im in out.items() if im is None]
    if missing:
        raise SystemExit(f"소스가 없어요: {missing}")
    return out


def anchors(made: dict[str, np.ndarray]) -> dict[str, tuple[int, int]]:
    """동작 앞부분 → 놓는 오프셋(저장 px)."""
    sy, sx = foot(made["stand_0"])
    out: dict[str, tuple[int, int]] = {}

    def to_stand(image: np.ndarray) -> tuple[int, int]:
        fy, fx = foot(image)
        return round(sx - fx), round(fy - sy)

    for prefix, (folder, indices, ref) in FOLDERS.items():
        if isinstance(ref, int):
            out[prefix] = to_stand(_src(folder, ref))
        elif ref is None:   # 걷기: 기준 장이 없음 — 14장 발 평균을 서 있기 발 자리에
            feet = [foot(_src(folder, i)) for i in indices]
            fy, fx = float(np.mean([f[0] for f in feet])), float(np.mean([f[1] for f in feet]))
            out[prefix] = (round(sx - fx), round(fy - sy))
    out["talk"] = to_stand(made["talk_base_0"])
    end = _src(FOLDERS["crouch"][0], CROUCH_END)
    out["sleep"] = _overlap_anchor(_src(FOLDERS["sleep"][0], 0), end, out["crouch"])
    return out


def main() -> None:
    made = frames()
    for old in [*OUT.glob("*.png"), *OUT.glob("*.webp")]:
        if old.name not in KEEP:
            old.unlink()
    for name, image in sorted(made.items()):
        # 말하기 장은 무손실(101) — 입만 바뀌는 장끼리 몸 픽셀이 똑같아야 말할 때 몸이 지글거리지 않음
        quality = 101 if name.startswith("talk_") else WEBP_QUALITY
        ok, data = cv2.imencode(".webp", image, [cv2.IMWRITE_WEBP_QUALITY, quality])
        if not ok:
            raise SystemExit(f"{name} WebP로 못 바꿨어요")
        (OUT / f"{name}.webp").write_bytes(data.tobytes())
    by_prefix = anchors(made)
    table = {}
    for name in sorted(made):
        prefix = name.rsplit("_", 1)[0]
        key = "talk" if prefix.startswith("talk_") else prefix
        if key in by_prefix and by_prefix[key] != (0, 0):
            table[name] = list(by_prefix[key])
    (OUT / "anchors.json").write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    stand_h = int(made["stand_0"].shape[0])   # 저장 그림 서 있는 키 — 앱(ui/pet_window)이 여기서 한 번만 줄임
    (OUT / "frames.json").write_text(json.dumps({"standH": stand_h, "drawScale": DRAW_SCALE}) + "\n", encoding="utf-8")
    print("다래", len(made), "anchors", {k: v for k, v in by_prefix.items()})


if __name__ == "__main__":
    main()
