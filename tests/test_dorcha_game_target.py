"""Native lookup boundary failures without querying the user's actual windows."""

import sys
from types import SimpleNamespace

import pytest

from mabinogi_addon import config
from mabinogi_addon.system import dwm_thumbnail, window_capture


@pytest.mark.parametrize("case", ["valid","unregistered","missing","bad-size","no-pid","api-error"])
def test_game_target_uses_registered_process_and_handles_native_failures(monkeypatch,case):
    monkeypatch.setattr(window_capture,"sys",SimpleNamespace(platform="win32"))
    monkeypatch.setattr(config,"load_game_exe",lambda:None if case == "unregistered" else "Client.exe")
    calls = []
    def find(exe,titles):
        calls.append(exe)
        assert exe == "Client.exe"
        return 0 if case == "missing" else 123
    monkeypatch.setattr(dwm_thumbnail,"find_game_window",find)
    monkeypatch.setattr(dwm_thumbnail,"window_rect",lambda hwnd:(-500,100,-500 if case == "bad-size" else 200,600))
    def owner(hwnd):
        assert hwnd == 123
        if case == "api-error":
            raise OSError("native failure")
        return 11, 0 if case == "no-pid" else 99
    monkeypatch.setitem(sys.modules,"win32process",SimpleNamespace(GetWindowThreadProcessId=owner))
    result = window_capture.registered_game_target()
    assert result == ((123,99,-500,100,700,500) if case == "valid" else None)
    assert calls == ([] if case == "unregistered" else ["Client.exe"])
