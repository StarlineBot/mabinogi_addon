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

from .. import perf_meter

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


BLOCK_NAMES = ("왼쪽", "오른쪽")
ROW_NAMES = ("윗줄", "아랫줄")


def group_name(gdef: "GroupDef") -> str:
    """사람이 알아볼 이름(0.49.0): 게임 단축바 번호와 같게 — '왼쪽 윗줄 1~4' · '오른쪽 아랫줄 9~12'."""
    first = gdef.col * CELLS + 1
    return f"{BLOCK_NAMES[gdef.block]} {ROW_NAMES[gdef.row]} {first}~{first + CELLS - 1}"


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
        from . import overlay_capture
        overlay_capture.watch(self)  # 0.37.1: 뜰 때마다 판독 캡처에서 빼기(이 창에만 필터)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._gdef = gdef
        self._scale = scale
        self._cells: list[QPixmap | None] = [None] * CELLS  # 각 칸 아이콘(없으면 빈 칸)
        self._hidden: list[bool] = [False] * CELLS  # 숨긴 칸(0.49.0: 잠금 해제면 흐린 자리로 그려 우클릭이 먹게)
        self._locked = False
        self._drag_offset = None

    @property
    def gdef(self) -> GroupDef:
        return self._gdef

    def set_cells(self, cells: list[QPixmap | None]) -> None:
        self._cells = cells
        self._relayout()

    def set_hidden(self, cells_on: list[bool]) -> None:
        """칸별 표시 값(설정 chunks.<key>.cells) — False인 칸은 숨김."""
        hidden = [not bool(on) for on in cells_on]
        if hidden != self._hidden:
            self._hidden = hidden
            self.update()

    @property
    def hidden(self) -> list[bool]:
        return list(self._hidden)

    def set_scale(self, scale: float) -> None:
        self._scale = max(0.3, min(3.0, scale))
        self._relayout()

    def set_locked(self, locked: bool) -> None:
        if locked:  # 끄던 중 고정되면 격자 안내선도 바로 숨긴다(공용 — grid.owner_locked)
            from . import grid as _grid
            _grid.owner_locked(self)
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
            # 우클릭한 칸 표시/숨김 토글(빈 슬롯 돌바닥 숨기기용). 숨긴 칸은 잠금 해제 때 흐린 자리라 다시 우클릭으로 되살린다.
            i = int(event.position().x() / max(1, IPITCH * self._scale))
            if 0 <= i < CELLS:
                self.cell_toggled.emit(i)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            # 다른 오버레이와 같은 격자 맞춤(mirror_overlay와 같은 방식, 0.36.1 사용자 제보)
            from . import grid

            self._snap = grid.enabled()
            self._grid_size = grid.size() if self._snap else None
            if self._snap:
                grid.show_guide(self)
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._locked and self._drag_offset is not None:
            target = event.globalPosition().toPoint() - self._drag_offset
            if getattr(self, "_snap", False):
                from . import grid

                target = grid.snap(target, getattr(self, "_grid_size", None))
            self.move(target)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            from . import grid

            grid.hide_guide()
            self.moved.emit()

    # ---- 그리기 ----
    @perf_meter.timed("그리기·단축바")  # 꼬리 끊김 조사: 오버레이 그리기 시간도 기능별 처리 시간에
    def paintEvent(self, _event) -> None:
        s = self._scale
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        isz = round(ICON * s)
        for i, pm in enumerate(self._cells):
            x = round(i * IPITCH * s)
            if self._hidden[i]:
                if self._locked:
                    continue  # 잠금: 숨긴 칸은 투명(지금처럼)
                # 잠금 해제: 흐린 자리로 그려 우클릭이 먹게(완전 투명이면 Windows가 클릭을 게임으로 넘긴다)
                from PySide6.QtGui import QColor
                painter.fillRect(x, 0, isz, isz, QColor(0, 0, 0, 90))
                if pm is not None:
                    painter.setOpacity(0.25)
                    painter.drawPixmap(x, 0, pm.scaled(isz, isz, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                       Qt.TransformationMode.FastTransformation))
                    painter.setOpacity(1.0)
                painter.setPen(QColor(255, 255, 255, 170))
                painter.drawLine(x + 4, 4, x + isz - 5, isz - 5)
                continue
            if pm is None:
                continue  # 빈 칸 → 투명

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


def slice_group_np(source_bgr: np.ndarray, gdef: GroupDef, cells_on: list[bool]) -> list[np.ndarray | None]:
    """한 그룹 4칸을 numpy로 자른다(작업 스레드에서 — 공유 캡처). 꺼진 칸·영역 밖은 None."""
    out: list[np.ndarray | None] = []
    H, W = source_bgr.shape[:2]
    for i in range(CELLS):
        x = gdef.x + i * IPITCH
        y = gdef.y
        if not cells_on[i] or x + ICON > W or y + ICON > H or x < 0 or y < 0:
            out.append(None)
            continue
        out.append(np.ascontiguousarray(source_bgr[y : y + ICON, x : x + ICON]))
    return out


def slice_group(source_bgr: np.ndarray, gdef: GroupDef, cells_on: list[bool]) -> list[QPixmap | None]:
    """소스 영역(앵커 기준 BGR)에서 한 그룹의 4칸 아이콘을 잘라 QPixmap 리스트로.

    cells_on[i]가 False면 그 칸은 None(투명). 영역을 벗어나면 None.
    """
    return [None if c is None else _np_to_pixmap(c) for c in slice_group_np(source_bgr, gdef, cells_on)]
