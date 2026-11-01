"""그림대화 캔버스 모델(그림대화 명세 5절).

픽셀마다 0~3(색 칸 번호)을 든 (96,256) 배열이다. 화면은 칸 번호를 4색으로 칠해서만 보여주므로
칸 색을 바꾸면 그 칸으로 그린 곳이 한꺼번에 바뀌고, 저장 때 변환이 필요 없다.
그리기는 OpenCV(선·네모·채우기)로 하고 Python 픽셀 반복문은 쓰지 않는다.
되돌리기는 동작 단위 사본(칸 배열 24KB + 팔레트)으로 최대 100단계.
"""

from __future__ import annotations

import cv2
import numpy as np

from .pngfile import HEIGHT, WIDTH

GRAY_PALETTE: list[tuple[int, int, int]] = [(0, 0, 0), (128, 128, 128), (192, 192, 192), (255, 255, 255)]
BACKGROUND = 3  # 4번 칸(흰색)으로 시작, 지우개도 4번 칸으로 칠한다
UNDO_LIMIT = 100


def _pt(p) -> tuple[int, int]:
    return int(round(p[0])), int(round(p[1]))


class SketchCanvas:
    def __init__(self) -> None:
        self.pixels = np.full((HEIGHT, WIDTH), BACKGROUND, np.uint8)
        self.palette: list[tuple[int, int, int]] = list(GRAY_PALETTE)
        self._undo: list[tuple[np.ndarray, tuple]] = []
        self._redo: list[tuple[np.ndarray, tuple]] = []

    # --- 되돌리기 ---
    def _snapshot(self) -> tuple[np.ndarray, tuple]:
        return self.pixels.copy(), tuple(self.palette)

    def checkpoint(self) -> None:
        """한 동작(획·채우기·칸 색 바꾸기 등)을 시작하기 전에 부른다."""
        self._undo.append(self._snapshot())
        if len(self._undo) > UNDO_LIMIT:
            del self._undo[0]
        self._redo.clear()

    def discard_checkpoint(self) -> None:
        """시작했지만 아무것도 바뀌지 않은 동작의 사본을 버린다(되돌리기 한 번이 헛돌지 않게)."""
        if self._undo:
            pixels, pal = self._undo[-1]
            if np.array_equal(pixels, self.pixels) and list(pal) == self.palette:
                self._undo.pop()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        pixels, pal = self._undo.pop()
        self.pixels, self.palette = pixels, list(pal)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        pixels, pal = self._redo.pop()
        self.pixels, self.palette = pixels, list(pal)
        return True

    # --- 그리기(호출 전 checkpoint) ---
    def stroke(self, p0, p1, slot: int, width: int) -> None:
        """펜·지우개 한 구간. 굵기 1은 한 픽셀 선, 그 이상은 둥근 끝 선."""
        cv2.line(self.pixels, _pt(p0), _pt(p1), int(slot), max(1, int(width)), cv2.LINE_8)

    def line(self, p0, p1, slot: int, width: int) -> None:
        self.stroke(p0, p1, slot, width)

    def rect(self, p0, p1, slot: int, width: int) -> None:
        """네모 테두리."""
        cv2.rectangle(self.pixels, _pt(p0), _pt(p1), int(slot), max(1, int(width)), cv2.LINE_8)

    def fill(self, p, slot: int) -> None:
        """같은 칸 번호로 이어진 곳(상하좌우)을 채운다."""
        x, y = _pt(p)
        if not (0 <= x < WIDTH and 0 <= y < HEIGHT) or self.pixels[y, x] == slot:
            return
        mask = np.zeros((HEIGHT + 2, WIDTH + 2), np.uint8)
        cv2.floodFill(self.pixels, mask, (x, y), int(slot), 0, 0, 4)

    def pick(self, p) -> int | None:
        """스포이드: 그 자리의 칸 번호."""
        x, y = _pt(p)
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            return int(self.pixels[y, x])
        return None

    def clear(self) -> None:
        self.pixels[:] = BACKGROUND

    def set_slot_color(self, slot: int, rgb: tuple[int, int, int]) -> None:
        self.palette[slot] = tuple(int(c) & 255 for c in rgb)

    def load(self, indices: np.ndarray, palette: list[tuple[int, int, int]]) -> None:
        """불러온 그림으로 덮어쓰기(호출 전 checkpoint — 되돌리기로 돌아갈 수 있다)."""
        a = np.asarray(indices, np.uint8)
        if a.shape != (HEIGHT, WIDTH) or len(palette) != 4:
            raise ValueError("256×96, 4색이어야 해요")
        self.pixels = (a & 3).copy()
        self.palette = [tuple(int(c) for c in p) for p in palette]

    def rgb(self) -> np.ndarray:
        """(96,256,3) RGB 표시용(팔레트 조회)."""
        return np.asarray(self.palette, np.uint8)[self.pixels]
