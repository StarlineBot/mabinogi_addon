"""설정 안내 그림(2026-10-25 사용자 결정): 연습 모드 화면에 설정할 영역을 점선으로 표시한 예시.

원본: tests/data/스크린샷 2026-10-25 233749.png(2560×1440, 레넨의 미미르 100%). 사용자가 정한 여섯 곳만 표시한다
(왼쪽 위 아이콘 줄은 단축키, 오른쪽 아이콘 칸은 추가 단축바라 표시하지 않음). 각 탭 도움말에는 그 탭 영역만, 첫 사용 안내에는
여섯 곳 전체. 영역 밖은 어둡게 하고 칸만 잘라 넣지 않는다. 그림은 미리 만들어 assets/guide에 넣는다(scripts/build_guide_images.py).
"""
from __future__ import annotations

import cv2
import numpy as np

SOURCE_SIZE = (2560, 1440)
# (번호, 이름, (x, y, 너비, 높이)) — 원본 좌표
AREAS = {
    'buff': (1, '버프 목록', (2, 604, 300, 318)),  # 상태목록창의 고정 즐겨찾기 칸을 뺀 아래 목록만
    'halo_timer': (2, '전투 제한 시간', (1226, 108, 134, 66)),
    'debuff': (3, '디버프', (1016, 1206, 522, 38)),  # 보스 체력바 바로 위
    'boss': (4, '보스 체력바', (1016, 1244, 522, 46)),
    'stat_bars': (5, '하단 체력바', (914, 1398, 140, 42)),
    'dorcha_tuarim': (6, '도르카·투아림', (1226, 36, 82, 64)),  # 전투 제한 시간 바로 위 게이지(숫자)와 옆 ▲ 100%를 함께(0.21.0 후속)
}
# 그림별 표시 영역(탭 도움말은 그 탭 영역만, 보스 패턴 알림은 같은 탭의 1분 헤일로용 전투 제한 시간 포함)
IMAGES = {
    'buff': ('buff',),
    'debuff': ('debuff',),
    'boss': ('boss', 'halo_timer'),
    'stat_bars': ('stat_bars',),
    'dorcha_tuarim': ('dorcha_tuarim',),
    'all': ('buff', 'halo_timer', 'debuff', 'boss', 'stat_bars', 'dorcha_tuarim'),
}
OUTPUT_WIDTH = 1200  # 큰 창 크기. 도움말 안에는 약 420px로 줄여 보인다
OUTLINE = (148, 184, 0)  # BGR 민트(#00B894)
LEFT_BADGE = {'debuff'}  # 디버프·보스 체력바가 위아래로 붙어 번호가 겹치지 않게 디버프 번호는 왼쪽
DIM = 0.35  # 영역 밖 밝기


def _dashed_rectangle(image, x, y, w, h, color, thickness=2, dash=10, gap=6):
    for (x0, y0, x1, y1) in ((x, y, x + w, y), (x, y + h, x + w, y + h), (x, y, x, y + h), (x + w, y, x + w, y + h)):
        length = max(abs(x1 - x0), abs(y1 - y0))
        steps = max(1, length // (dash + gap) + 1)
        for i in range(steps):
            start = i * (dash + gap)
            end = min(start + dash, length)
            if start >= length:
                break
            if y0 == y1:
                cv2.line(image, (x0 + start, y0), (x0 + end, y0), color, thickness, cv2.LINE_AA)
            else:
                cv2.line(image, (x0, y0 + start), (x0, y0 + end), color, thickness, cv2.LINE_AA)


def _badge(image, number, x, y):
    """번호 원(민트 바탕·검은 숫자). 한글은 OpenCV로 그릴 수 없어 이름은 그림 밖 글로 적는다."""
    cv2.circle(image, (x, y), 15, OUTLINE, -1, cv2.LINE_AA)
    cv2.circle(image, (x, y), 15, (255, 255, 255), 2, cv2.LINE_AA)
    text = str(number)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.putText(image, text, (x - tw // 2, y + th // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 2, cv2.LINE_AA)


def render(source: np.ndarray, name: str, *, numbered: bool | None = None) -> np.ndarray:
    """원본(2560×1440 BGR)에서 name 그림을 만든다: 영역 밖 어둡게 + 점선 테두리(+ 여러 영역이면 번호)."""
    if source.shape[1::-1] != SOURCE_SIZE:
        raise ValueError(f'원본은 {SOURCE_SIZE[0]}×{SOURCE_SIZE[1]}이어야 해요({source.shape[1]}×{source.shape[0]})')
    keys = IMAGES[name]
    numbered = len(keys) > 2 if numbered is None else numbered
    scale = OUTPUT_WIDTH / SOURCE_SIZE[0]
    image = cv2.resize(source, (OUTPUT_WIDTH, round(SOURCE_SIZE[1] * scale)), interpolation=cv2.INTER_AREA)
    mask = np.zeros(image.shape[:2], bool)
    boxes = []
    for key in keys:
        number, _label, (x, y, w, h) = AREAS[key]
        box = (round(x * scale) - 2, round(y * scale) - 2, round(w * scale) + 4, round(h * scale) + 4)
        bx, by, bw, bh = box
        mask[max(0, by):by + bh, max(0, bx):bx + bw] = True
        boxes.append((number, key, box))
    dimmed = (image.astype(np.float32) * DIM).astype(np.uint8)
    image = np.where(mask[..., None], image, dimmed)
    for number, key, (bx, by, bw, bh) in boxes:
        _dashed_rectangle(image, max(0, bx), max(0, by), min(bw, image.shape[1] - bx - 1), min(bh, image.shape[0] - by - 1), OUTLINE)
        if numbered:
            x = bx - 20 if key in LEFT_BADGE else bx + bw + 20
            _badge(image, number, min(image.shape[1] - 18, max(18, x)), min(image.shape[0] - 18, max(18, by + bh // 2)))
    return image


def caption(name: str) -> str:
    """그림 아래 글: 표시한 곳 이름(번호 그림은 번호와 함께)."""
    keys = IMAGES[name]
    if len(keys) > 2:
        return ' · '.join(f"{'①②③④⑤⑥'[AREAS[k][0] - 1]} {AREAS[k][1]}" for k in keys)
    return ' · '.join(AREAS[k][1] for k in keys)
