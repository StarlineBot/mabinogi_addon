"""Reproduce missing pywin32 exports; not a live Windows compositor test.

Run: PYTHONPATH=src:.:tests python -m pytest scripts/qa_dialogue_native_api_contract_20261020.py -q
"""

import sys
from types import SimpleNamespace

from mabinogi_addon.system import dialogue_visibility as visibility


def test_region_check_uses_exported_creation_api():
    calls = []
    gui = SimpleNamespace(
        CreateRectRgnIndirect=lambda rect: calls.append(rect) or 1,
        GetWindowRgn=lambda hwnd, handle: 1,
        DeleteObject=lambda handle: None,
    )
    detail = {}
    result = visibility._region_overlap(gui, 22, [(20, 20, 68, 68)], detail)
    assert result is False, detail
    assert calls


def test_identity_diagnostic_does_not_call_missing_process_export(monkeypatch):
    closed = []
    monkeypatch.setitem(sys.modules, "win32api", SimpleNamespace(
        OpenProcess=lambda *args: SimpleNamespace(Close=lambda: closed.append(True))))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (1, 123)))
    detail = {}
    visibility._blocker_identity(None, 22, detail)
    assert closed == [True]
    assert detail.get("identity_error") != "AttributeError", detail
