"""DWM 썸네일 미러의 비-Windows 안전성과 매니저 폴백 테스트.

실제 DWM 합성은 Windows에서만 되므로(여기선 검증 불가), 다른 OS에서 import·호출이
안전하고(no-op/0), MirrorManager가 DWM 불가 시 mss 경로로 폴백하는지만 본다.
"""

import sys

import numpy as np
import pytest

from mabinogi_addon.system import dwm_thumbnail


def test_available_false_off_windows():
    if sys.platform != "win32":
        assert dwm_thumbnail.available() is False


def test_find_game_window_safe_off_windows():
    if sys.platform != "win32":
        assert dwm_thumbnail.find_game_window("client.exe", ("mabinogi",)) == 0
        assert dwm_thumbnail.window_rect(0) is None


def test_thumbnail_register_fails_without_hwnd():
    t = dwm_thumbnail.Thumbnail()
    assert t.register(0, 0) is False
    # 미등록 상태에서 update/unregister는 조용히 실패/무시
    assert t.update((0, 0, 10, 10), (0, 0, 10, 10)) is False
    t.unregister()  # 예외 없이 통과


@pytest.mark.skipif(sys.platform == "win32", reason="DWM 모드는 Windows에서 활성")
def test_manager_falls_back_to_mss_off_windows(qtbot_unused=None):
    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui.mirror_manager import MirrorManager

    app = QApplication.instance() or QApplication([])
    assert app is not None

    frames = {"n": 0}

    def fake_grab():
        frames["n"] += 1
        # 20x20 BGRA 가상 화면, left/top 0
        return np.zeros((20, 20, 4), dtype=np.uint8), 0, 0

    # source_hwnd를 줘도 Windows가 아니면 DWM 비활성 → mss 경로
    mgr = MirrorManager(fps=30, grab=fake_grab, source_hwnd=lambda: 12345)
    assert mgr._dwm is False
    overlay = mgr.add({"x": 0, "y": 0, "w": 10, "h": 10})
    assert overlay.thumbnail_active is False  # 썸네일 안 씀
    mgr._tick()  # mss grab 경로가 돌아야 함
    assert frames["n"] >= 1
    mgr.shutdown()
