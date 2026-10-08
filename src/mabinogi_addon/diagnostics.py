"""버그 신고 첨부용 진단 헤더.

최근 로그만으로는 원인 파악이 어렵다(어떤 버전·환경·설정에서 났는지 모름). 버그 신고
시 로그 앞에 이 헤더를 붙여 버전/OS/화면/설정 상태를 한눈에 본다. 민감정보는 넣지
않는다(실행파일명 정도만, 경로·토큰 제외).
"""

from __future__ import annotations

import platform
import sys


def _region_line(section: str) -> str:
    from . import config

    r = config.load_capture_region(section)
    return f"{r['w']}×{r['h']} @ ({r['x']},{r['y']})" if r else "미지정"


def header_text() -> str:
    from . import config, paths
    from .version import display_version

    lines: list[str] = []
    lines.append(f"앱 버전: {display_version()}")
    lines.append(f"빌드: {'배포본(exe)' if paths.is_frozen() else '개발(uv)'}")
    lines.append(f"OS: {platform.platform()}")
    lines.append(f"Python: {sys.version.split()[0]}")

    # 화면(해상도·DPI) — Qt 앱이 떠 있을 때만.
    try:
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            g = screen.geometry()
            lines.append(f"화면: {g.width()}×{g.height()} @ {screen.devicePixelRatio():.2f}x")
    except Exception:  # noqa: BLE001, S110 — 화면 정보는 있으면 좋고 없어도 그만
        pass

    # 설정 상태(원인 파악에 중요한 것들).
    try:
        exe = config.load_game_exe()
        lines.append(f"게임 창 인식: {exe or '미등록'}")
        lines.append(f"버프 영역: {_region_line('buffTracker')}")
        lines.append(f"디버프 영역: {_region_line('debuffTracker')}")
        box = config.load_tuarim().get("box")
        tuarim = f"{box['w']}×{box['h']} @ ({box['x']},{box['y']})" if box else "미지정"
        lines.append(f"투아림 영역: {tuarim}")
        lines.append(f"알림 목소리: {config.load_voice_pack() or '기본(녹음)'}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"(설정 읽기 실패: {exc!r})")

    return "===== 진단 정보 =====\n" + "\n".join(lines)
