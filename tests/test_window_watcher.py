"""포그라운드 감지 watcher 테스트(플랫폼 독립 부분만)."""

from mabinogi_addon.system.window_watcher import (
    AlwaysActiveWatcher,
    create_window_watcher,
)


def test_always_active_is_active():
    assert AlwaysActiveWatcher().is_active() is True


def test_factory_returns_watcher_with_is_active():
    # 비-Windows(맥/리눅스 CI)에선 AlwaysActiveWatcher가 돌아온다.
    w = create_window_watcher()
    assert hasattr(w, "is_active")
    assert isinstance(w.is_active(), bool)


import os
import sys
from types import SimpleNamespace

import pytest
from mabinogi_addon.system import window_watcher as watcher


@pytest.mark.parametrize('condition, expected', [
    ('main', True), ('same_pid_overlay', False), ('other', False), ('zero', False),
    ('invalid', False), ('other_pid', False), ('foreground_error', False),
    ('pid_error', False), ('foreground_changed', False), ('pid_reused', False),
])
def test_main_foreground_requires_current_exact_window_and_owned_pid(monkeypatch, condition, expected):
    reads = {'foreground': 0, 'pid': 0}
    def foreground():
        reads['foreground'] += 1
        if condition == 'foreground_error':
            raise OSError('foreground unavailable')
        if condition == 'zero':
            return 0
        if condition in ('same_pid_overlay', 'other') or (condition == 'foreground_changed' and reads['foreground'] > 1):
            return 33
        return 11
    def pid(hwnd):
        reads['pid'] += 1
        if condition == 'pid_error':
            raise OSError('pid unavailable')
        foreign = condition == 'other_pid' or (condition == 'pid_reused' and reads['pid'] > 1)
        return 1, os.getpid() + int(foreign)
    monkeypatch.setattr(watcher, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setitem(sys.modules, 'win32gui', SimpleNamespace(GetForegroundWindow=foreground, IsWindow=lambda hwnd: condition != 'invalid'))
    monkeypatch.setitem(sys.modules, 'win32process', SimpleNamespace(GetWindowThreadProcessId=pid))
    detail = {}
    assert watcher.is_main_window_foreground(11, diagnostic=detail) is expected
    assert (detail['foreground'] == 'main') is expected
