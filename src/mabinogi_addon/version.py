"""앱 버전 단일 소스.

개발 중에는 "0.0.0"(개발 빌드). 릴리스 빌드(release.yml)에서 태그(vX.Y.Z)로부터
이 파일을 덮어써 실제 버전을 넣고, 동시에 exe 파일 속성(버전 리소스)에도 반영한다.
"""

from __future__ import annotations

__version__ = "0.0.0"


def display_version() -> str:
    """사람이 보는 버전 문자열. 개발 빌드(0.0.0)는 '개발'로 표시."""
    return "개발" if __version__ == "0.0.0" else f"v{__version__}"
