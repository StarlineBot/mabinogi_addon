"""남은 시간 축약 표기 (기획서 3.1).

| 남은 시간 | 표기 |
| 1일 이상 | 5d |
| 1시간 이상 | 1h46m |
| 1분 이상 | 3:28 |
| 1분 미만 | 28s |
"""

from __future__ import annotations


def format_duration(seconds: float) -> str:
    total = int(max(0, seconds))
    if total >= 86400:
        return f"{total // 86400}d"
    if total >= 3600:
        hours = total // 3600
        minutes = (total % 3600) // 60
        return f"{hours}h{minutes}m"
    if total >= 60:
        return f"{total // 60}:{total % 60:02d}"
    return f"{total}s"
