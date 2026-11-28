"""Starline 영상판 프레임(사용자 11-27 '맘에 들어, 개발로 넘겨줘' — docs/characters/Starline_영상모션_작업표.md).

실행: uv run python -m scripts.build_starline_video
- 소스: docs/characters/assets/Starline/영상/앱크기/ — 기획이 배경 빼기·크기(서기 키 약 282)·높이·효과까지 끝낸 투명 PNG,
  0.1초 간격. 동작 폴더 안에서는 같은 틀 크기(아래·가운데 맞춰 그리면 위치 맞음). 색 처리 다시 하지 않음(harmonize 없음).
- 걷기: 같은 원본크기 폴더 vwalk14_0~13.png(장마다 꽉 맞춘 그림).
- 앱 폴더(assets/characters/Starline)의 예전 프레임은 지우고 쓰는 장만 넣음(card.png·frame.png·frame.json·lines.json은 그대로).
- 저장: 장마다 WebP(화질 90) — PNG 29MB → 약 6MB, 알파 그대로(차 0), 색 평균 차 ≤3.1/255, 한 장 읽기 약 1.8ms
  (사용자 11-27 '장 수 줄이기보다 다른 대안'). 앱은 OpenCV로 읽음(Qt webp 플러그인에 기대지 않음, ui/pet_window.LazyFrames).
- 말하기: 장마다 몸이 조금씩 달라 그대로 쓰면 말할 때 몸이 튐 → 입 다문 10번 몸에 작은 입(6번)·큰 입(11번)만 얼굴로 맞춰 붙임.
- 사이 모션 10(6_어깨금장·7_소매팔찌)은 기능이 아직 없어 넣지 않음.
"""
from __future__ import annotations

import cv2
import numpy as np

from scripts.build_dare_frames import imread, imwrite
from scripts.build_outfit_frames import APP_ROOT, ASSETS

# 원본 크기(사용자 11-27 '앱에 들어오니 구려짐' — 서기 키 286으로 줄여 저장한 뒤 앱이 화면배율 1.25 이상에서 다시 키워 흐림):
# 기획이 같은 처리를 원본 해상도로 다시 한 세트(앱크기 × K, 서기 키 약 518). 앱은 frames.json standH에서 한 번만 줄여 그림
SRC = ASSETS / "Starline" / "영상" / "원본크기"
WALK_SRC = SRC
K = 1.8369   # 원본크기/배율.json k — 아래 좌표(앱크기 기준 측정)를 이만큼 늘려 씀
OUT = APP_ROOT / "Starline"
KEEP = {"card.png", "frame.png"}
WEBP_QUALITY = 90
# 동작 틀마다 서 있는 발 자리가 서기 틀(아래 끝·발 가운데 +13.5)과 달라 동작이 바뀔 때 튐 → 그리기 오프셋(저장 px, anchors.json).
# 쓰다듬기·모자 마술은 몸이 왼쪽으로 7·5px(귀·모자 자리 때문에 틀이 넓음), 앉기·일어나기는 서 있는 장 발이 틀 바닥 10px 위
# (앉은 장은 공중에 떠 있는 그림이라 그대로 같이 내림), 착지는 끝 장 발이 13px 위·1.5px 왼쪽(떨어지는 4번도 같은 틀).
# 그리기 배율(그림 파일은 그대로 — 사용자 원칙): 착지 영상이 서기보다 크게 찍힘(land_29 키 1.066배·머리 1.04배 — 기획 원본부터,
# 사용자 11-28 '내려놓은 뒤 서기로 바뀔 때 작아짐') → 떨어지기·착지(land_*)를 0.95로 그림: 키 +1.3%·머리 −1.2%
DRAW_SCALE = {"land": 0.95,
              "talk_emph": 0.975}   # 손가락 튕기는 장(말하기 강조·알림) 머리가 서기보다 3% 큼(키는 같음) → 머리 1.00·키 0.975
_A = {"pet": (7, 0), "motion_hat_magic": (5, 0), "crouch": (0, 10), "rise": (0, 10), "land": (2, 13)}   # 앱크기 px
ANCHORS = {k: (round(x * K), round(y * K)) for k, (x, y) in _A.items()}
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
_s = lambda box: tuple(round(v * K) for v in box)   # noqa: E731
MOUTH_BOX = _s((88, 111, 34, 22))  # (x, y, w, h) 입 둘레 — 10번 기준 입 선 y≈118, 큰 입 y 116~125(앱크기 px)
EYES_BOX = _s((72, 95, 62, 18))    # 얼굴 맞춤 기준(눈 줄)


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
    pad = round(6 * K)
    area = g(base)[y - pad:y + h + pad, x - pad:x + w + pad]
    _, _, _, (bx, by) = cv2.minMaxLoc(cv2.matchTemplate(area, t, cv2.TM_CCOEFF_NORMED))
    return bx - pad, by - pad


def mouth_on(base: np.ndarray, src: np.ndarray) -> np.ndarray:
    """base 몸에 src 입만 — 입 둘레 타원(가장자리 3px 흐림)으로 섞음."""
    dx, dy = _shift(src, base)
    x, y, w, h = MOUTH_BOX
    patch = src[y:y + h, x:x + w].astype(np.float32)
    mask = np.zeros((h, w), np.float32)
    edge = round(3 * K)
    cv2.ellipse(mask, (w // 2, h // 2), (w // 2 - edge, h // 2 - edge), 0, 0, 360, 1.0, -1)
    blur = 2 * round(3 * K) + 1
    mask = cv2.GaussianBlur(mask, (blur, blur), 0)[..., None]
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
    import json
    anchors = {name: list(ANCHORS[name.rsplit("_", 1)[0]]) for name in sorted(made) if name.rsplit("_", 1)[0] in ANCHORS}
    (OUT / "anchors.json").write_text(json.dumps(anchors, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    stand_h = int(made["stand_0"].shape[0])   # 저장 그림 서 있는 키 — 앱(ui/pet_window)이 여기서 한 번만 줄임
    (OUT / "frames.json").write_text(json.dumps({"standH": stand_h, "drawScale": DRAW_SCALE}) + "\n", encoding="utf-8")
    print("Starline", len(made), "anchors", len(anchors))


if __name__ == "__main__":
    main()
