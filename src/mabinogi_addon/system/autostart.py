"""Windows 시작 시 자동 실행 (기획서 5.3 / 4.x).

exe는 관리자 권한(--uac-admin)으로 실행되므로, 레지스트리 Run 키로는 로그온 시
자동 실행이 안 된다(Windows가 Run 키 항목을 UAC 승격해 주지 않음). 그래서 배포본
(frozen)은 **작업 스케줄러**에 "로그온 시 / 최고 권한" 작업을 만든다 → UAC 창 없이
관리자 권한으로 자동 실행. 작업 생성/삭제엔 관리자 권한이 필요한데, 앱이 이미 관리자라
가능하다.

개발(uv)은 수동 실행이라 자동 실행이 필요 없지만, 동작은 유지하려고 기존 레지스트리
Run 키 방식을 그대로 쓴다(관리자 아님).

Windows 전용. 다른 OS에선 available()=False, set/is_enabled는 no-op/False.
"""

from __future__ import annotations

import logging
import sys

_log = logging.getLogger("mabinogi_addon.autostart")

_APP_NAME = "StarlineMabinogiAddon"  # Run 키 값 이름 / 작업 이름 공용
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def available() -> bool:
    return sys.platform == "win32"


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


# ---- 작업 스케줄러(배포본/관리자 앱) ----
def _run(args: list[str]) -> tuple[int, str]:
    import subprocess

    CREATE_NO_WINDOW = 0x08000000  # 콘솔 창 안 뜨게
    try:
        r = subprocess.run(  # 고정 명령(schtasks), 사용자 입력 없음
            args,
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as exc:  # noqa: BLE001
        _log.warning("명령 실패 %r: %r", args, exc)
        return 1, str(exc)


def _task_enabled() -> bool:
    rc, _ = _run(["schtasks", "/Query", "/TN", _APP_NAME])
    return rc == 0


def _task_set(enabled: bool) -> bool:
    if enabled:
        rc, out = _run([
            "schtasks", "/Create", "/TN", _APP_NAME,
            "/TR", f'"{sys.executable}"',  # 로그온 시 실행할 exe(공백 대비 따옴표)
            "/SC", "ONLOGON", "/RL", "HIGHEST", "/F",
        ])
        if rc == 0:
            _log.info("작업 스케줄러 자동 실행 등록: %s", sys.executable)
        else:
            _log.warning("작업 등록 실패: %s", out)
        return rc == 0
    rc, out = _run(["schtasks", "/Delete", "/TN", _APP_NAME, "/F"])
    if rc != 0 and ("cannot find" in out.lower() or "없" in out):
        rc = 0  # 이미 없음 → 성공 취급
    return rc == 0


# ---- 레지스트리 Run(개발/비관리자) ----
def _reg_command() -> str:
    if _is_frozen():
        return f'"{sys.executable}"'
    return f'"{sys.executable}" -m mabinogi_addon'


def _reg_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _APP_NAME)
            return bool(value)
    except OSError:
        return False


def _reg_set(enabled: bool) -> bool:
    import winreg

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _reg_command())
            else:
                try:
                    winreg.DeleteValue(key, _APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError as exc:
        _log.warning("레지스트리 자동 실행 설정 실패: %r", exc)
        return False


# ---- 공개 API(frozen=작업 스케줄러, dev=레지스트리) ----
def is_enabled() -> bool:
    if not available():
        return False
    return _task_enabled() if _is_frozen() else _reg_enabled()


def set_enabled(enabled: bool) -> bool:
    """자동 실행 등록/해제. 성공 True."""
    if not available():
        return False
    return _task_set(enabled) if _is_frozen() else _reg_set(enabled)


def refresh() -> None:
    """자동실행이 켜져 있으면 현재 실행 경로로 갱신(exe 이동/교체 시 self-heal).

    진단: 켜짐 여부와 현재 exe를 남겨, '구버전이 부팅마다 뜨는' 증상의 원인(작업
    감지 실패로 재지정이 통째로 건너뛰어졌는지)이 로그에 보이게 한다.
    """
    if not available():
        return
    enabled = is_enabled()
    _log.info("자동실행 self-heal: 켜짐=%s, 현재exe=%s", enabled, sys.executable)
    if enabled:
        set_enabled(True)  # _task_set이 등록 경로/성패를 로그로 남긴다
