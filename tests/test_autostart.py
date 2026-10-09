"""자동 실행(레지스트리 Run 키)의 비-Windows 안전성 테스트.

실제 레지스트리 등록은 Windows에서만 되므로, 다른 OS에서 호출이 안전한지만 본다.
"""

import sys

from mabinogi_addon.system import autostart


def test_available_matches_platform():
    assert autostart.available() == (sys.platform == "win32")


def test_safe_noop_off_windows():
    if sys.platform != "win32":
        assert autostart.is_enabled() is False
        assert autostart.set_enabled(True) is False
        assert autostart.set_enabled(False) is False
        autostart.reconcile(True)  # 예외 없이 통과(비Windows no-op)
        autostart.reconcile(False)
