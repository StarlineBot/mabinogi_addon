"""파일 기반 캡처 (맥/CI 개발·테스트용).

폴더의 PNG들을 순서대로 돌려준다. 전체 화면 스크린샷이면 Region으로 잘라서
라이브 캡처와 같은 영역만 넘길 수 있다.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..image_io import imread
from .base import FrameSource, Region


class FileFrameSource(FrameSource):
    def __init__(
        self,
        paths: list[Path] | Path,
        *,
        region: Region | None = None,
        loop: bool = True,
    ) -> None:
        if isinstance(paths, Path):
            paths = sorted(p for p in paths.iterdir() if p.suffix.lower() == ".png")
        self._paths = list(paths)
        self._region = region
        self._loop = loop
        self._index = 0

    def grab(self) -> np.ndarray | None:
        if self._index >= len(self._paths):
            if not self._loop or not self._paths:
                return None
            self._index = 0

        image = imread(self._paths[self._index], cv2.IMREAD_COLOR)
        self._index += 1
        if image is None:
            return None

        if self._region is not None:
            r = self._region
            image = image[r.y : r.y + r.h, r.x : r.x + r.w]
        return image
