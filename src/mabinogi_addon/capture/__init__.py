"""화면 캡처: FrameSource 인터페이스와 구현체 (File / Video / Live).

작은 이미지에선 OpenCV 멀티스레드가 오히려 CPU 스파이크를 유발하므로 1스레드 고정.
"""

import cv2

cv2.setNumThreads(1)

from .base import FrameSource, Region  # noqa: E402
from .file_source import FileFrameSource  # noqa: E402

__all__ = ["FrameSource", "Region", "FileFrameSource"]


def create_live_source(region: Region) -> FrameSource:
    """Windows 라이브 캡처 소스 생성(지연 import). 맥/CI에선 호출하지 않는다."""
    from .live_source import LiveCaptureSource

    return LiveCaptureSource(region)
