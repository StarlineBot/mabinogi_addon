"""이미지 판정: 아이콘 템플릿 매칭, 시간 판독."""

import cv2

cv2.setNumThreads(1)

from .binarize import binarize  # noqa: E402
from .buff_detector import Detection, detect_buffs  # noqa: E402
from .icon_matcher import DEFAULT_THRESHOLD, MatchResult, match_icon  # noqa: E402
from .time_reader import read_time  # noqa: E402

__all__ = [
    "MatchResult",
    "match_icon",
    "DEFAULT_THRESHOLD",
    "Detection",
    "detect_buffs",
    "binarize",
    "read_time",
]
