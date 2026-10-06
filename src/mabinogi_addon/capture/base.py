"""캡처 추상화 (기획서 4.1).

FrameSource 인터페이스로 캡처를 분리한다. 구현체는 지정 영역(Region)을 BGR 이미지로
돌려준다. 새 프레임이 없으면 None(라이브 캡처에서 발생).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Region:
    """화면 영역(실제 픽셀 좌표)."""

    x: int
    y: int
    w: int
    h: int

    @property
    def ltrb(self) -> tuple[int, int, int, int]:
        """(left, top, right, bottom) — dxcam/mss에서 쓰는 형태."""
        return (self.x, self.y, self.x + self.w, self.y + self.h)


class FrameSource(ABC):
    """캡처 소스. grab()은 BGR(HxWx3, uint8) 또는 None(새 프레임 없음)."""

    @abstractmethod
    def grab(self) -> np.ndarray | None: ...

    def close(self) -> None:
        """자원 해제. 필요 없는 구현은 그대로 둔다."""
