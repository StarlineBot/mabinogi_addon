"""단축바(상단 스킬바) 미러 — 그룹(4칸) 단위 청크.

게임 상단 단축바는 **아이콘 4칸이 한 그룹**으로 붙어 있고, 그룹 사이·블록 사이엔 넓은
간격이 있다. 그 넓은 간격까지 통째로 복제하면 지저분하므로, **그룹(4칸)을 하나의 청크**로
떼어 각각 원하는 위치로 옮긴다(간격은 복제하지 않음 → 투명). 청크 안의 4칸은 원본과 같은
간격으로 두되, 칸 사이도 복제 안 한 투명이라 배경이 비쳐 깔끔하다.

좌표 체계(100% UI 배율 기준, 해상도 무관 고정 픽셀):
- 소스 앵커 = 단축바 **첫 아이콘(블록1·윗줄·1번째)의 좌상단**. 사용자가 영역 지정으로 맞춘다.
- 블록 시작 x: 0, 620   그룹 간격: 188   아이콘 피치: 44   아이콘 크기: 40   행 피치: 49
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

# 고정 격자(앵커=첫 아이콘 좌상단 기준, 단위 px @100% 배율)
ICON = 40
IPITCH = 44  # 그룹 내 아이콘 간격
GROUP_DX = (0, 188, 376)  # 한 블록 안 3그룹의 x 시작
BLOCK_X = (0, 620)  # 두 블록의 x 시작
ROW_Y = (0, 49)  # 두 줄의 y 시작
CELLS = 4  # 그룹당 아이콘 수
GROUP_W = (CELLS - 1) * IPITCH + ICON  # 그룹 폭(=172)
# 앵커(첫 아이콘 좌상단) 기준 전체 소스 영역 크기(두 블록·두 줄 모두 덮는 사각형).
SRC_W = BLOCK_X[-1] + GROUP_DX[-1] + GROUP_W  # =1168
SRC_H = ROW_Y[-1] + ICON  # =89


@dataclass(frozen=True)
class GroupDef:
    """한 그룹(청크)의 식별자 + 소스 앵커 기준 좌상단 오프셋."""

    block: int  # 0,1
    row: int  # 0,1
    col: int  # 0,1,2
    x: int  # 앵커 기준 x
    y: int  # 앵커 기준 y

    @property
    def key(self) -> str:
        return f"b{self.block}r{self.row}c{self.col}"


def group_defs() -> list[GroupDef]:
    out: list[GroupDef] = []
    for bi, bx in enumerate(BLOCK_X):
        for ri, ry in enumerate(ROW_Y):
            for ci, dx in enumerate(GROUP_DX):
                out.append(GroupDef(bi, ri, ci, bx + dx, ry))
    return out


@dataclass
class ChunkState:
    """청크의 표시 상태(설정 저장용)."""

    show: bool = True
    locked: bool = False
    pos: tuple[int, int] | None = None  # 화면 위치(없으면 기본 배치)
    cells: list[bool] = field(default_factory=lambda: [True] * CELLS)  # 칸별 표시


def _np_to_pixmap(bgr: np.ndarray) -> QPixmap:
    h, w = bgr.shape[:2]
    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    img = QImage(rgb.tobytes(), w, h, 3 * w, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(img.copy())


class ChunkOverlay(QWidget):
    """그룹 한 개(최대 4칸)를 간격 투명으로 그리는 이동 가능한 오버레이."""

    moved = Signal()
    cell_toggled = Signal(int)  # 우클릭으로 i번째 칸 표시/숨김 토글(빈칸 숨기기)

    def __init__(self, gdef: GroupDef, scale: float = 1.0) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._gdef = gdef
        self._scale = scale
        self._cells: list[QPixmap | None] = [None] * CELLS  # 각 칸 아이콘(없으면 숨김)
        self._locked = False
        self._drag_offset = None

    @property
    def gdef(self) -> GroupDef:
        return self._gdef

    def set_cells(self, cells: list[QPixmap | None]) -> None:
        self._cells = cells
        self._relayout()

    def set_scale(self, scale: float) -> None:
        self._scale = max(0.3, min(3.0, scale))
        self._relayout()

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, locked)
        from ..system.clickthrough import set_click_through

        set_click_through(self, locked)
        self.update()

    @property
    def locked(self) -> bool:
        return self._locked

    def _relayout(self) -> None:
        s = self._scale
        w = round(GROUP_W * s)
        h = round(ICON * s)
        self.resize(max(1, w), max(1, h))
        self.update()

    # ---- 이동 ----
    def mousePressEvent(self, event) -> None:
        if self._locked:
            return
        if event.button() == Qt.MouseButton.RightButton:
            # 우클릭한 칸 표시/숨김 토글(빈 슬롯 돌바닥 숨기기용).
            i = int(event.position().x() / max(1, IPITCH * self._scale))
            if 0 <= i < CELLS:
                self.cell_toggled.emit(i)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._locked and self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self.moved.emit()

    # ---- 그리기 ----
    def paintEvent(self, _event) -> None:
        s = self._scale
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        isz = round(ICON * s)
        for i, pm in enumerate(self._cells):
            if pm is None:
                continue  # 숨김/빈 칸 → 투명
            x = round(i * IPITCH * s)
            scaled = pm.scaled(
                isz, isz,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            painter.drawPixmap(x, 0, scaled)
        # 고정 해제 시 옅은 테두리(드래그 가능 안내)
        if not self._locked:
            from PySide6.QtGui import QColor, QPen

            painter.setPen(QPen(QColor(0, 209, 167), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()


def slice_group(source_bgr: np.ndarray, gdef: GroupDef, cells_on: list[bool]) -> list[QPixmap | None]:
    """소스 영역(앵커 기준 BGR)에서 한 그룹의 4칸 아이콘을 잘라 QPixmap 리스트로.

    cells_on[i]가 False면 그 칸은 None(투명). 영역을 벗어나면 None.
    """
    out: list[QPixmap | None] = []
    H, W = source_bgr.shape[:2]
    for i in range(CELLS):
        if not cells_on[i]:
            out.append(None)
            continue
        x = gdef.x + i * IPITCH
        y = gdef.y
        if x + ICON > W or y + ICON > H or x < 0 or y < 0:
            out.append(None)
            continue
        out.append(_np_to_pixmap(source_bgr[y : y + ICON, x : x + ICON]))
    return out
