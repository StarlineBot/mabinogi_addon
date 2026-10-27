"""버그 신고 첨부용 진단 헤더.

최근 로그만으로는 원인 파악이 어렵다(어떤 버전·환경·설정에서 났는지 모름). 버그 신고
시 로그 앞에 이 헤더를 붙여 버전/OS/화면/설정 상태를 한눈에 본다. 민감정보는 넣지
않는다(실행파일명 정도만, 경로·토큰 제외).
"""

from __future__ import annotations

import platform
import sys


# 실행 중 최근 상태 메모(2026-10-27 도르카 문의: 영역·거절 이유가 진단에 없어 원인을 몰랐음). 키 → 한 줄.
_NOTES: dict[str, str] = {}


def note(key: str, text: str) -> None:
    """진단 헤더에 붙일 최근 상태 한 줄을 기록한다(같은 키는 덮어씀)."""
    _NOTES[key] = text


def describe_dorcha(trace: dict, value) -> str:
    """도르카 판독 결과를 한 줄로: 읽은 값, 또는 거절 이유와 점수."""
    if value is not None:
        return f"읽음 {value}" + (" (장식 낮은 점수 인정)" if trace.get("soft_ornament") else "")
    reason = trace.get("rejection") or "알 수 없음"
    parts = [reason]
    if "score" in trace:
        parts.append(f"숫자 점수 {trace['score']:.3f}·차이 {trace.get('margin', 0):.3f}")
    scores = [c.get("score", 0) for c in trace.get("candidates", []) if isinstance(c, dict)]
    if scores:
        parts.append(f"장식 최고 {max(scores):.3f}")
    return "거절 · " + " · ".join(parts)


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
        dorcha = config.load_dorcha().get("box")
        lines.append(f"도르카 영역: {dorcha['w']}×{dorcha['h']} @ ({dorcha['x']},{dorcha['y']})" if dorcha else "도르카 영역: 미지정")
        lines.append(f"알림 목소리: {config.load_voice_pack() or '기본(녹음)'}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"(설정 읽기 실패: {exc!r})")

    lines.extend(f"{key}: {text}" for key, text in sorted(_NOTES.items()))
    return "===== 진단 정보 =====\n" + "\n".join(lines)
