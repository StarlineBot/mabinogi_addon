"""Windows 시작 시 자동 실행 (기획서 5.3 / 4.x).

배포본 exe는 항상 관리자 권한(--uac-admin, 0.11.3 복원)으로 실행된다. 게임이 관리자 권한으로
돌기 때문에 앱이 일반 권한이면 UIPI로 블랙박스 단축키(저수준 키보드 훅)를 게임 포커스 중에 받지
못한다(0.11.2 실기 확인). 레지스트리 Run 키는 UAC 승격을 해 주지 않아 로그온 자동 실행이 안
되므로, 배포본(frozen)은 **작업 스케줄러**에 "로그온 시 / 최고 권한" 작업을 만든다 → UAC 창 없이
관리자 권한으로 자동 실행. 작업 생성/삭제엔 관리자 권한이 필요하다. 관리자 승인을 거부하는 등
권한이 부족하면 등록이 실패하며, reconcile/set_enabled가 False를 돌려 화면에서 안내한다.

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
    return _task_delete()


def _task_delete() -> bool:
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


def _reg_delete() -> None:
    """레지스트리 Run 키의 자동실행 값 제거(없으면 무시). 구버전이 Run 키로 등록해
    둔 잔재가 남아 '옛 exe가 같이 뜨는' 중복 실행을 막는다."""
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, _APP_NAME)
    except FileNotFoundError:
        pass
    except OSError as exc:  # 잔재 정리는 실패해도 치명적이지 않음(로그만)
        _log.warning("레지스트리 자동실행 잔재 제거 실패: %r", exc)


# ---- 공개 API(frozen=작업 스케줄러, dev=레지스트리) ----
def is_enabled() -> bool:
    if not available():
        return False
    return _task_enabled() if _is_frozen() else _reg_enabled()


def set_enabled(enabled: bool) -> bool:
    """자동 실행 등록/해제. 성공 True.

    현재 방식(배포본=작업 스케줄러 / 개발=레지스트리)으로 등록·해제하되, **반대 방식의
    잔재는 항상 제거**한다. 구버전이 다른 방식으로 등록해 둔 게 남아 옛 exe가 함께
    뜨던 중복 실행(예: 0.1.x가 Run 키로 등록, 현재는 작업 스케줄러)을 없앤다.
    """
    if not available():
        return False
    if _is_frozen():
        ok = _task_set(enabled)
        _reg_delete()  # 작업 스케줄러를 쓰므로 Run 키 잔재는 항상 제거
        return ok
    ok = _reg_set(enabled)
    if _task_enabled():  # 개발 실행인데 배포본이 만든 작업이 남아 있으면 정리(가능하면)
        _task_delete()
    return ok


def reconcile(intent: bool) -> bool:
    """저장된 '의도'(config)대로 작업을 현재 exe에 강제 동기화. 매 시작 호출.

    이전 refresh()는 '작업이 켜져 있나?'(schtasks 조회)가 실패하면 재지정을 통째로
    건너뛰어, 작업이 낡은(구버전) exe를 계속 가리키는 문제가 있었다. reconcile은
    조회에 의존하지 않고 의도대로 무조건 맞춘다: True면 현재 exe로 재등록(self-heal),
    False면 제거. 그래서 '신버전을 실행하면 그게 자동 실행 대상'이 항상 보장된다.
    실패(권한 부족 등)면 False — 호출자가 사용자에게 안내한다(로그에만 남기지 않음).
    """
    if not available():
        return True
    _log.info("자동실행 reconcile: 의도=%s, 현재exe=%s", intent, sys.executable)
    return set_enabled(intent)  # _task_set이 등록/삭제 경로·성패를 로그로 남긴다
