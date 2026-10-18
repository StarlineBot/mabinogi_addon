"""Input desktop query failures are diagnosed and acquired handles are closed."""

import ctypes
from types import SimpleNamespace
import pytest
from mabinogi_addon.system import dialogue_visibility as visibility


@pytest.mark.parametrize("failure", [None, "OpenInputDesktop", "GetUserObjectInformationW", "locked"])
def test_desktop_failure_records_api_and_releases_handle(monkeypatch, failure):
    closed = []
    def open_desktop(*args):
        return 0 if failure == "OpenInputDesktop" else 55
    def close_desktop(handle):
        closed.append(handle)
        return True
    def information(handle, key, name, size, needed):
        name.value = "Winlogon" if failure == "locked" else "Default"
        return failure != "GetUserObjectInformationW"
    def win_error():
        error = OSError("not logged")
        error.winerror = 5
        return error
    monkeypatch.setattr(ctypes, "WinError", win_error, raising=False)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=SimpleNamespace(
        OpenInputDesktop=open_desktop, CloseDesktop=close_desktop,
        GetUserObjectInformationW=information)), raising=False)
    if failure in {"OpenInputDesktop", "GetUserObjectInformationW"}:
        with pytest.raises(OSError) as caught:
            visibility.desktop_unlocked()
        assert caught.value.native_api == failure
        assert caught.value.winerror == 5
    else:
        assert visibility.desktop_unlocked() is (failure is None)
    assert closed == ([] if failure == "OpenInputDesktop" else [55])
