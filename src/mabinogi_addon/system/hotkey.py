"""전역 단축키(Windows RegisterHotKey). 게임이 맨 앞이어도 동작한다.

왜 RegisterHotKey인가: Qt의 QShortcut은 우리 창이 포커스일 때만 먹어 게임 중엔 안 온다.
RegisterHotKey는 조합을 OS에 등록해, 어떤 창이 앞에 있든 그 조합을 OS가 먼저 가로채
우리에게 WM_HOTKEY로 보낸다(윈도우키만 피하면 게임 키와 충돌해도 OS가 우선). 전역
키보드 훅(모든 키 가로채기)은 안티치트·개인정보 위험이라 쓰지 않는다 — RegisterHotKey는
등록한 그 조합만 받는다.

규칙: 게임에 키를 '보내지' 않는다. 사용자의 키를 '받아' 우리 오버레이를 토글할 뿐
(읽기 전용 철학 그대로). Windows 전용 — 맥/리눅스는 no-op(지원 안 함).

spec 형식: 'Ctrl+Alt+P' 처럼 '+'로 구분(QKeySequence.toString() 그대로 받는다).
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

_log = logging.getLogger(__name__)

_WM_HOTKEY = 0x0312
_HOTKEY_ID = 0xB0FF  # 우리 전용 id(임의)

# RegisterHotKey 수정자 비트
_MOD = {"alt": 0x0001, "control": 0x0002, "ctrl": 0x0002, "shift": 0x0004}
_MOD_NOREPEAT = 0x4000

# 기능키 F1~F12
_FKEYS = {f"f{i}": 0x70 + (i - 1) for i in range(1, 13)}


def is_supported() -> bool:
    return sys.platform == "win32"


def parse_spec(spec: str) -> tuple[int, int] | None:
    """'Ctrl+Alt+P' → (modifiers, vk). 모디파이어가 하나도 없거나 키가 없으면 None.

    윈도우키(Meta/Win)는 게임이 선점하므로 거부한다(None).
    """
    if not spec:
        return None
    mods = 0
    vk: int | None = None
    for raw in spec.split("+"):
        tok = raw.strip().lower()
        if not tok:
            continue
        if tok in ("meta", "win", "super"):
            return None  # 윈도우키는 지원 안 함
        if tok in _MOD:
            mods |= _MOD[tok]
        elif tok in _FKEYS:
            vk = _FKEYS[tok]
        elif len(tok) == 1 and (tok.isalpha() or tok.isdigit()):
            vk = ord(tok.upper())
        else:
            return None  # 지원하지 않는 키
    if vk is None or mods == 0:
        return None  # 모디파이어 없는 단독 키는 오발 위험 → 거부
    return mods | _MOD_NOREPEAT, vk


class _MsgFilter(QAbstractNativeEventFilter):
    """WM_HOTKEY 메시지를 잡아 신호로 바꾼다(Windows 메시지 루프에 끼어든다)."""

    def __init__(self, owner: PauseHotkey) -> None:
        super().__init__()
        self._owner = owner

    def nativeEventFilter(self, event_type, message):
        try:
            et = event_type if isinstance(event_type, str) else bytes(event_type)
            if et in (b"windows_generic_MSG", "windows_generic_MSG"):
                import ctypes
                import ctypes.wintypes

                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == _WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                    _log.debug("WM_HOTKEY 수신 → 오버레이 토글")
                    self._owner.activated.emit()
        except Exception:  # noqa: BLE001, S110 — 필터는 예외로 앱을 흔들지 않는다
            pass
        return False, 0


class PauseHotkey(QObject):
    """전역 단축키 하나(오버레이 정지/시작)를 등록/해제한다.

    activated: 등록된 조합이 눌리면 발생. Windows에서만 실제 동작(그 외 no-op).
    """

    activated = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._registered = False
        self._filter: _MsgFilter | None = None
        self._hwnd = 0  # 등록에 쓴 창 핸들(해제 때 동일해야 함)

    def _window_hwnd(self) -> int:
        """메인 창의 HWND. 여기 등록해야 Qt가 WM_HOTKEY를 네이티브 필터로 넘긴다.

        hwnd=NULL(스레드 큐)로 등록하면 Qt가 그 메시지를 필터로 안 넘기는 경우가 있어
        단축키가 조용히 안 먹는다. 부모(메인 창)의 winId()를 쓴다.
        """
        w = self.parent()
        try:
            if w is not None and hasattr(w, "window"):
                return int(w.window().winId())
        except Exception:  # noqa: BLE001, S110 — 핸들 못 구하면 NULL로 폴백
            pass
        return 0

    def set_hotkey(self, spec: str) -> bool:
        """조합을 등록한다. 성공 True. 빈 값/미지원/충돌/비Windows면 False(해제만)."""
        self.unregister()
        if not is_supported():
            return False
        parsed = parse_spec(spec)
        if parsed is None:
            return False
        mods, vk = parsed
        import ctypes

        hwnd = self._window_hwnd()
        if not ctypes.windll.user32.RegisterHotKey(hwnd, _HOTKEY_ID, mods, vk):
            _log.info("전역 단축키 등록 실패(충돌?): %s", spec)
            return False
        app = _app()
        if app is None:
            ctypes.windll.user32.UnregisterHotKey(hwnd, _HOTKEY_ID)
            return False
        self._hwnd = hwnd
        self._filter = _MsgFilter(self)
        app.installNativeEventFilter(self._filter)
        self._registered = True
        _log.info("전역 단축키 등록: %s (hwnd=%s)", spec, hwnd)
        return True

    def unregister(self) -> None:
        if not self._registered:
            return
        self._registered = False
        try:
            import ctypes

            ctypes.windll.user32.UnregisterHotKey(self._hwnd, _HOTKEY_ID)
            app = _app()
            if app is not None and self._filter is not None:
                app.removeNativeEventFilter(self._filter)
        except Exception:  # noqa: BLE001, S110 — 해제 실패는 무시(종료 경로)
            pass
        self._filter = None


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance()
