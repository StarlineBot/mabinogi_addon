"""새 말하기 프레임(사용자 11-24 '말할 때 모션이 어색' — docs/character-pet-spec.md '말하기 모션 어색함'·'새 말하기 시트').

각 캐릭터 빌드 스크립트(build_dare/aria/ian_frames)가 talk_frames(캐릭터)를 불러 결과에 합친다.
- 반복 시트 6장: 0 기준(입 다묾) · 1 입 조금 · 2 입 크게 · 3 강조 손짓 · 4 강조 완화 · 5 눈 깜빡임.
- 입만 바꾸기(빌드 때 미리 합성): 0번을 몸으로 두고 1·2번의 입 부분만 덧그림 → talk_base·talk_m1·talk_m2.
  입 대략 위치(0번 원본 좌표) → R = 원본 키×0.035 → 얼굴 창(입 위 3R~아래 R, 좌우 3R)에서 cv2.phaseCorrelate로
  1·2번을 0번에 맞춤 → 창(±R) 안 차이 최댓값 40% 이상 픽셀 중심으로 입 중심 보정 → 타원(1.1R×0.8R),
  가장자리 GaussianBlur(σ=0.25R) 마스크로 덧그림(1/255 아래는 0 — 입 밖 픽셀은 0번과 똑같음).
- 강조(3·4)·깜빡임(5)·사이 프레임(전환 시트 0번)은 통째 그림 — 앱이 덮기 전환으로 바꿈.
- 크기: 서 있는 키 285(0번 키 기준, 반복 시트 모두 같은 배율).
이름: 다래·이안 talk_base/m1/m2/emph/emph2/blink/mid, 아리아는 반복 A·B 두 벌 → talk_a_* / talk_b_*.
"""
from __future__ import annotations

import cv2
import numpy as np

from scripts.build_aria_frames import clean
from scripts.build_dare_frames import ROOT, head_width, imread, scaled, split

STAND_H = 285
ASSETS = ROOT / "docs/characters/assets"
# (반복 시트, 사이 프레임 시트, 0번 원본 입 대략 위치, 이름 앞붙임)
SETS = {
    "다래": [("다래/SD/다래_말하기_반복.png", "다래/SD/다래_말하기_전환2.png", (240, 286), "talk_")],
    "아리아": [("아리아/SD/아리아_말하기_반복A.png", "아리아/SD/아리아_말하기_전환A.png", (155, 208), "talk_a_"),
             ("아리아/SD/아리아_말하기_반복B.png", "아리아/SD/아리아_말하기_전환B.png", (145, 208), "talk_b_")],
    "이안": [("이안/SD/v2/이안_말하기_반복.png", "이안/SD/v2/이안_말하기_시작.png", (142, 222), "talk_")],  # v2(11-24) 시작 0번 = 사이
    "레나": [("레나/SD/레나_말하기_반복.png", "레나/SD/레나_말하기_시작.png", (200, 198), "talk_")],  # 시작 0번 = 사이
}


def _sheet(rel: str) -> list[np.ndarray]:
    return split(clean(imread(ASSETS / rel, cv2.IMREAD_UNCHANGED)))


def _on(frame: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """프레임을 (높이, 폭) 캔버스 왼쪽 위에 놓음(크기가 1~3px 다른 프레임 맞추기)."""
    out = np.zeros((size[0], size[1], 4), np.uint8)
    h, w = min(size[0], frame.shape[0]), min(size[1], frame.shape[1])
    out[:h, :w] = frame[:h, :w]
    return out


def _gray(frame: np.ndarray) -> np.ndarray:
    a = frame[..., 3:].astype(np.float32) / 255
    return (cv2.cvtColor(frame[..., :3], cv2.COLOR_BGR2GRAY).astype(np.float32)[..., None] * a)[..., 0]


def _shift(base, other, box, r, hann=False):
    """phaseCorrelate 이동량 — 신뢰도 0.2 미만이거나 2R보다 크면 None(엉뚱한 자리로 옮겨 입이 번지는 것 막음,
    아리아 A 2번에서 신뢰도 −0.002·85px로 실측 11-24)."""
    y0, y1, x0, x1 = box
    win_b = _gray(base)[y0:y1, x0:x1].astype(np.float64)
    win_o = _gray(other)[y0:y1, x0:x1].astype(np.float64)
    window = cv2.createHanningWindow((win_b.shape[1], win_b.shape[0]), cv2.CV_64F) if hann else None
    (dx, dy), response = cv2.phaseCorrelate(win_b, win_o, window)
    if response < 0.2 or abs(dx) > 2 * r or abs(dy) > 2 * r:
        return None, None
    return dx, dy


def mouth_swap(base: np.ndarray, other: np.ndarray, mouth: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """base 몸에 other의 입만 덧그린 그림과 마스크(0~1)."""
    h, w = base.shape[:2]
    other = _on(other, (h, w))
    mx, my = mouth
    r = h * 0.035
    y0, y1 = int(max(0, my - 3 * r)), int(min(h, my + r))
    x0, x1 = int(max(0, mx - 3 * r)), int(min(w, mx + 3 * r))
    dx, dy = _shift(base, other, (y0, y1, x0, x1), r)
    if dx is None:  # 얼굴 창으로 못 맞추면(신뢰도 낮음·이동 큼) 머리 전체 창 + 창 함수로 다시
        dx, dy = _shift(base, other, (int(max(0, my - 6 * r)), int(min(h, my + 2 * r)),
                                      int(max(0, mx - 5 * r)), int(min(w, mx + 5 * r))), r, hann=True)
    dx, dy = (0.0, 0.0) if dx is None else (dx, dy)  # 그래도 안 되면 옮기지 않음(같은 시트라 거의 제자리)
    shift = np.float32([[1, 0, -dx], [0, 1, -dy]])  # other를 base에 맞춤
    aligned = cv2.warpAffine(other, shift, (w, h), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
    ry0, ry1 = int(max(0, my - r)), int(min(h, my + r))
    rx0, rx1 = int(max(0, mx - r)), int(min(w, mx + r))
    diff = np.abs(_gray(aligned)[ry0:ry1, rx0:rx1] - _gray(base)[ry0:ry1, rx0:rx1])
    if diff.max() > 0:
        ys, xs = np.where(diff >= diff.max() * 0.4)
        mx, my = rx0 + xs.mean(), ry0 + ys.mean()
    mask = np.zeros((h, w), np.float32)
    cv2.ellipse(mask, (int(round(mx)), int(round(my))), (int(round(1.1 * r)), int(round(0.8 * r))), 0, 0, 360, 1.0, -1)
    mask = cv2.GaussianBlur(mask, (0, 0), 0.25 * r)
    mask[mask < 1 / 255] = 0
    m = mask[..., None]
    out = np.clip(base.astype(np.float32) * (1 - m) + aligned.astype(np.float32) * m, 0, 255).astype(np.uint8)
    return out, mask


def talk_frames(character: str, head: float | None = None) -> dict[str, list[np.ndarray]]:
    """head(저장 크기 서 있기 머리 폭)를 주면 키 대신 머리 폭으로 배율을 맞춤(이안·아리아, 사용자 11-24)."""
    out: dict[str, list[np.ndarray]] = {}
    for loop_rel, mid_rel, mouth, prefix in SETS[character]:
        loop = _sheet(loop_rel)
        if len(loop) != 6:
            raise SystemExit(f"{loop_rel}: 프레임 {len(loop)}개(기대 6)")
        base = loop[0]
        k = head / head_width(base) if head else STAND_H / base.shape[0]
        m1, _ = mouth_swap(base, loop[1], mouth)
        m2, _ = mouth_swap(base, loop[2], mouth)
        out[f"{prefix}base"] = [scaled(base, k)]
        out[f"{prefix}m1"] = [scaled(m1, k)]
        out[f"{prefix}m2"] = [scaled(m2, k)]
        out[f"{prefix}emph"] = [scaled(loop[3], k)]
        out[f"{prefix}emph2"] = [scaled(loop[4], k)]
        out[f"{prefix}blink"] = [scaled(loop[5], k)]
        mid = _sheet(mid_rel)[0]
        out[f"{prefix}mid"] = [scaled(mid, head / head_width(mid) if head else STAND_H / mid.shape[0])]
    return out
