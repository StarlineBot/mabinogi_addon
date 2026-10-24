"""Windows 지정 단축키 관찰·세션/절전 메시지. 입력을 생성하거나 소비하지 않는다."""
import ctypes as C
import sys

from ..blackbox_native import target_identity
from .blackbox_hotkey import HotkeyObserver


class WindowsEvents:
    ID = 0xB10C
    def __init__(self, hwnd, modifiers, vk):
        if sys.platform != 'win32':
            raise OSError('Windows events unavailable')
        if type(modifiers) is not int or modifiers & ~0xF or type(vk) is not int or not 1 <= vk <= 254:
            raise ValueError('explicit valid hotkey required')
        from ctypes import wintypes as W
        self.hwnd = hwnd
        self.locked = self.suspended = False
        self.foreground = False  # 마지막 sample 기준 게임 창이 앞에 있는지(단축키 저장 조건)
        self.wts = C.WinDLL('wtsapi32', use_last_error=True)
        self.wts.WTSRegisterSessionNotification.argtypes = [W.HWND, W.DWORD]
        self.wts.WTSRegisterSessionNotification.restype = W.BOOL
        self.wts.WTSUnRegisterSessionNotification.argtypes = [W.HWND]
        self.observer = None
        self.notified = False
        try:
            if not self.wts.WTSRegisterSessionNotification(hwnd, 0):
                raise C.WinError(C.get_last_error())
            self.notified = True
            self.observer = HotkeyObserver(modifiers, vk)
        except BaseException:
            self.close()
            raise

    def message(self, kind, wparam):
        if kind == 0x2B1:
            if wparam == 7:
                self.locked = True
            elif wparam == 8:
                self.locked = False
        elif kind == 0x218:
            if wparam == 4:
                self.suspended = True
            elif wparam in (7, 18):
                self.suspended = False
        if kind in (0x2B1, 0x218) and self.observer is not None:
            self.observer.discard()
        return False

    def set_hotkey(self, modifiers, vk):
        if type(modifiers) is not int or modifiers & ~0xF or type(vk) is not int or not 1 <= vk <= 254:
            raise ValueError('explicit valid hotkey required')
        self.observer.set_chord(modifiers, vk)

    def consume_hotkey(self):
        event = self.observer.consume()
        return None if self.locked or self.suspended else event

    def sample(self):
        import win32gui
        from .. import config
        from .window_capture import registered_game_target
        from .window_watcher import _exe_basename_of_pid
        found = registered_game_target()
        if not found:
            return None, False
        hwnd, pid = found[:2]
        # 제목 일치만으로 대상을 받아들이지 않는다.
        if _exe_basename_of_pid(pid) != (config.load_game_exe() or '').lower():
            return None, False
        target = target_identity(hwnd, pid)
        # 녹화는 게임 창이 뒤에 있어도(최소화 아님) 계속한다(2026-10-23 사용자 결정). 단축키 저장은 앞에 있을 때만.
        self.foreground = win32gui.GetForegroundWindow() == hwnd
        active = not self.locked and not self.suspended and not win32gui.IsIconic(hwnd)
        return target, active

    def close(self):
        try:
            if self.observer is not None:
                self.observer.close()
        finally:
            if self.notified:
                self.wts.WTSUnRegisterSessionNotification(self.hwnd)
                self.notified = False


def window_rect(hwnd):
    """게임 창 화면 좌표 (left, top, right, bottom). 실패하면 None(저장 반응 오버레이 위치용)."""
    try:
        import win32gui
        return win32gui.GetWindowRect(int(hwnd))
    except Exception:
        return None
