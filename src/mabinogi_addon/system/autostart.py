"""Windows 시작 시 자동 실행 (기획서 5.3 / 4.x).

사용자 단위 레지스트리 Run 키(HKCU\\...\\CurrentVersion\\Run)에 실행 명령을 등록/
해제한다. 관리자 권한이 필요 없고(HKCU), 로그인 시 자동 실행된다.

- 배포(exe, frozen): 현재 exe 경로를 그대로 등록.
- 개발(uv): `python -m mabinogi_addon`. (개발 중 자동실행은 거의 안 쓰지만 동작은 함.)

Windows 전용. 다른 OS에선 available()=False, set/is_enabled는 no-op/False.
경로에 공백이 있을 수 있으므로 따옴표로 감싼다. exe를 옮기면 경로가 어긋나므로,
자동실행이 켜져 있으면 앱 시작 때 현재 경로로 다시 써 self-heal 한다(refresh).
"""

from __future__ import annotations

import logging
import sys

_log = logging.getLogger("mabinogi_addon.autostart")

_APP_NAME = "StarlineMabinogiAddon"  # Run 키 값 이름
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def available() -> bool:
    return sys.platform == "win32"


def _command() -> str:
    """로그인 시 실행할 명령(따옴표 포함)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # 개발: 현재 파이썬으로 패키지 실행
    return f'"{sys.executable}" -m mabinogi_addon'


def is_enabled() -> bool:
    """Run 키에 우리 항목이 등록돼 있는지."""
    if not available():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _APP_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_enabled(enabled: bool) -> bool:
    """자동 실행 등록/해제. 성공 True(변경 불가 환경은 False)."""
    if not available():
        return False
    import winreg

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _command())
                _log.info("자동 실행 등록: %s", _command())
            else:
                try:
                    winreg.DeleteValue(key, _APP_NAME)
                    _log.info("자동 실행 해제")
                except FileNotFoundError:
                    pass  # 이미 없음
        return True
    except OSError as exc:
        _log.warning("자동 실행 설정 실패: %r", exc)
        return False


def refresh() -> None:
    """자동실행이 켜져 있으면 현재 실행 경로로 갱신(exe 이동 시 self-heal)."""
    if available() and is_enabled():
        set_enabled(True)
