"""Execute the new native test against pywin32 error/ownership contracts, not Windows.

Run with PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen python -m pytest
scripts/qa_dialogue_windows_contract_20261020.py -q --tb=short.
"""

import ctypes
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import pytest
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: F401
from test_navigation import window  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
native_case = runpy.run_path(str(ROOT / 'tests/windows/test_dialogue_visibility.py'))[
    'test_real_window_region_export_and_gdi_cleanup']


@pytest.fixture
def api_model(window, monkeypatch):
    owned, deleted_while_owned = {}, []
    serial = [0]

    class Region:
        def __init__(self, shape):
            serial[0] += 1
            self.number, self.shape, self.detached = serial[0], shape, False

        def Detach(self):
            self.detached = True
            return self.number

        def __del__(self):
            if not self.detached and self.number in owned.values():
                deleted_while_owned.append(self.number)

    def set_region(hwnd, region, redraw):
        if region is None:
            owned.pop(hwnd, None)
        else:
            owned[hwnd] = region.number

    class Win32APIError(Exception):
        pass

    def no_region(hwnd, destination):
        # pywin32 int_regiontype typemap raises on Win32 ERROR (0).
        raise Win32APIError(0, 'GetWindowRgn', 'No explicit window region')

    def get_region(hwnd, destination):
        destination.shape = (0, 0, 10, 10)
        return 2

    def intersects(region, rect):
        x, y, r, b = region.shape
        return max(x, rect[0]) < min(r, rect[2]) and max(y, rect[1]) < min(b, rect[3])

    gui = SimpleNamespace(error=Win32APIError,
                          CreateRectRgnIndirect=Region, SetWindowRgn=set_region,
                          GetWindowRect=lambda hwnd: (0, 0, 200, 160),
                          GetWindowRgn=get_region, RectInRegion=intersects,
                          DeleteObject=lambda region: region.Detach())
    monkeypatch.setitem(sys.modules, 'win32gui', gui)
    kernel = SimpleNamespace(GetCurrentProcess=lambda: 1)
    user = SimpleNamespace(GetGuiResources=lambda *args: 1)
    monkeypatch.setattr(ctypes, 'WinDLL', lambda name: kernel if name == 'kernel32' else user,
                        raising=False)
    return gui, no_region, deleted_while_owned


def test_native_no_region_case_accepts_pywin32_error_semantics(api_model):
    gui, no_region, _ = api_model
    gui.GetWindowRgn = no_region
    native_case(None, None)


def test_native_shape_transfer_does_not_auto_delete_owned_handle(api_model):
    _, _, deleted_while_owned = api_model
    native_case((0, 0, 10, 10), False)
    assert deleted_while_owned == [], deleted_while_owned
