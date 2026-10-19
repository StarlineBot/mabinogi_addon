"""실제 HWND/DWM/Z-order 확인. 캡처·오디오·외부 통신은 사용하지 않는다."""

import sys
import pytest

pytestmark = [pytest.mark.windows_integration,
              pytest.mark.skipif(sys.platform != "win32", reason="Windows HWND integration")]


@pytest.mark.parametrize('shape,expected',[(None,None),((0,0,0,0),False),
                                         ((0,0,10,10),False),((0,0,200,160),True)])
def test_real_window_region_export_and_gdi_cleanup(shape,expected):
    import ctypes
    from ctypes import wintypes
    import win32gui
    from PySide6.QtWidgets import QApplication,QWidget
    from mabinogi_addon.system.dialogue_visibility import _region_overlap

    app=QApplication.instance() or QApplication([])
    owner=QWidget()
    owner.resize(200,160)
    owner.show()
    app.processEvents()
    hwnd=int(owner.winId())
    try:
        assert callable(win32gui.CreateRectRgnIndirect)
        region=win32gui.CreateRectRgnIndirect(shape) if shape is not None else None
        try:
            win32gui.SetWindowRgn(hwnd,region,False)
            if region is not None:
                region.Detach()  # The HWND now owns it; prevent PyGdiHANDLE auto-deletion.
            region=None
        finally:
            if region is not None:
                win32gui.DeleteObject(region)
        left,top,_,_=win32gui.GetWindowRect(hwnd)
        targets=[(left+20,top+20,left+68,top+68)]
        detail={}
        assert _region_overlap(win32gui,hwnd,targets,detail) is expected
        if shape is None:
            # pywin32 raises for GetWindowRgn's ERROR (no explicit region).
            assert detail.get('region_error') == win32gui.error.__name__
            assert 'region_type' not in detail
        else:
            assert 'region_error' not in detail
        assert 'region_cleanup_error' not in detail
        kernel=ctypes.WinDLL('kernel32')
        kernel.GetCurrentProcess.restype=wintypes.HANDLE
        current=kernel.GetCurrentProcess()
        get_gdi=ctypes.WinDLL('user32').GetGuiResources
        get_gdi.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        get_gdi.restype=wintypes.DWORD
        before=get_gdi(current,0)
        assert before>0
        for _ in range(100):
            assert _region_overlap(win32gui,hwnd,targets,{}) is expected
        assert get_gdi(current,0)<=before
    finally:
        win32gui.SetWindowRgn(hwnd,None,False)
        owner.close()
        owner.deleteLater()
        app.processEvents()


def test_real_process_identity_query_and_handle_cleanup():
    import ctypes
    from ctypes import wintypes
    from pathlib import Path
    import os
    from PySide6.QtWidgets import QApplication,QWidget
    from mabinogi_addon.system.dialogue_visibility import _blocker_identity

    app=QApplication.instance() or QApplication([])
    owner=QWidget()
    owner.show()
    app.processEvents()
    hwnd=int(owner.winId())
    try:
        detail={}
        _blocker_identity(None,hwnd,detail)
        assert detail.get('blocker_exe','').casefold()==Path(sys.executable).name.casefold(),detail
        assert detail['blocker_pid']==os.getpid() and 'identity_error' not in detail
        kernel=ctypes.WinDLL('kernel32')
        kernel.GetCurrentProcess.restype=wintypes.HANDLE
        current=kernel.GetCurrentProcess()
        count=kernel.GetProcessHandleCount
        count.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        count.restype=wintypes.BOOL
        def handles():
            value=wintypes.DWORD()
            assert count(current,ctypes.byref(value))
            return value.value
        before=handles()
        for _ in range(100):
            detail={}
            _blocker_identity(None,hwnd,detail)
            assert 'identity_error' not in detail and detail.get('blocker_pid')==os.getpid()
        assert handles()<=before
    finally:
        owner.close()
        owner.deleteLater()
        app.processEvents()


def test_real_window_occlusion_without_foreground_requirement():
    import ctypes
    import win32con
    import win32gui
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
    from mabinogi_addon.system.dialogue_visibility import exposed

    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    blocker = QWidget()
    try:
        area = app.primaryScreen().availableGeometry()
        owner.setGeometry(area.x() + 10, area.y() + 10, 200, 160)
        owner.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        owner.show()
        app.processEvents()
        hwnd = int(owner.winId())
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                             win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
        ctypes.windll.dwmapi.DwmFlush()
        target = [(20, 20, 60, 40)]
        assert exposed(hwnd, target, (owner.width(), owner.height()))
        point = owner.mapToGlobal(owner.rect().topLeft())
        blocker.setGeometry(point.x(), point.y(), 150, 120)
        blocker.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        blocker.show()
        app.processEvents()
        win32gui.SetWindowPos(int(blocker.winId()), win32con.HWND_TOPMOST, 0, 0, 0, 0,
                             win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
        ctypes.windll.dwmapi.DwmFlush()
        assert not exposed(hwnd, target, (owner.width(), owner.height()))
        blocker.hide()
        app.processEvents()
        ctypes.windll.dwmapi.DwmFlush()
        assert exposed(hwnd, target, (owner.width(), owner.height()))
        owner.hide()
        assert not exposed(hwnd, target, (owner.width(), owner.height()))
    finally:
        blocker.close()
        owner.close()
