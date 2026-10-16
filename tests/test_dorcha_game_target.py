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


@pytest.mark.parametrize("case", ["valid","owner-changed","hidden","destroyed","exe-changed"])
def test_cached_window_is_revalidated_without_enumeration_when_still_valid(monkeypatch,case):
    from mabinogi_addon.system import window_watcher
    monkeypatch.setattr(window_capture,"sys",SimpleNamespace(platform="win32"))
    monkeypatch.setattr(config,"load_game_exe",lambda:"Client.exe")
    calls = []
    monkeypatch.setattr(dwm_thumbnail,"find_game_window",lambda *a: calls.append(1) or 99)
    monkeypatch.setattr(dwm_thumbnail,"window_rect",lambda hwnd:(-400,200,300,700))
    monkeypatch.setattr(window_watcher,"_exe_basename_of_pid",lambda pid:"other.exe" if case == "exe-changed" else "client.exe")
    monkeypatch.setitem(sys.modules,"win32gui",SimpleNamespace(
        IsWindow=lambda hwnd:case != "destroyed", IsWindowVisible=lambda hwnd:case != "hidden"))
    monkeypatch.setitem(sys.modules,"win32process",SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd:(11,20 if hwnd == 99 or case == "owner-changed" else 2)))
    result = window_capture.registered_game_target((1,2,0,0,260,180))
    assert result == ((1,2,-400,200,700,500) if case == "valid" else (99,20,-400,200,700,500))
    assert calls == ([] if case == "valid" else [1])
