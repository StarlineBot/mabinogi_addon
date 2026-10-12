"""미러 크롭 + 커스텀 오버레이 프리셋 config 테스트."""

import numpy as np

from mabinogi_addon import config
from mabinogi_addon.ui.mirror_manager import crop_region


def test_crop_region_basic():
    frame = np.zeros((100, 120, 4), dtype=np.uint8)
    frame[20:36, 30:46] = 255  # 관심 영역에 값
    sub = crop_region(frame, 0, 0, {"x": 30, "y": 20, "w": 16, "h": 16})
    assert sub is not None
    assert sub.shape == (16, 16, 4)
    assert int(sub.mean()) == 255


def test_crop_region_with_monitor_offset():
    frame = np.zeros((100, 120, 4), dtype=np.uint8)
    # 가상 데스크톱 좌상단이 (-10, -5)인 경우
    sub = crop_region(frame, -10, -5, {"x": 0, "y": 0, "w": 5, "h": 5})
    assert sub is not None and sub.shape == (5, 5, 4)


def test_crop_region_out_of_bounds():
    frame = np.zeros((50, 50, 4), dtype=np.uint8)
    assert crop_region(frame, 0, 0, {"x": 40, "y": 40, "w": 20, "h": 20}) is None


def test_tick_skips_capture_when_inactive():
    """게임 비활성이면 grab을 호출하지 않는다(캡처 쉼)."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui.mirror_manager import MirrorManager

    QApplication.instance() or QApplication([])
    calls = {"n": 0}

    def fake_grab():
        calls["n"] += 1

    active = {"v": False}
    mgr = MirrorManager(grab=fake_grab, is_active=lambda: active["v"])
    mgr._tick()  # 비활성 → grab 호출 안 함
    assert calls["n"] == 0
    active["v"] = True
    mgr._tick()  # 활성 → grab 호출
    assert calls["n"] == 1


def test_custom_preset_roundtrip(tmp_path):
    p = tmp_path / "config.local.json"
    items = [{"x": 1, "y": 2, "w": 3, "h": 4, "posX": 5, "posY": 6, "locked": True, "name": "a.exe"}]
    config.save_custom_preset("프리셋1", items, p)
    config.save_custom_preset("프리셋2", [], p)
    presets = config.load_custom_presets(p)
    assert set(presets) == {"프리셋1", "프리셋2"}
    assert presets["프리셋1"][0]["name"] == "a.exe"

    config.delete_custom_preset("프리셋1", p)
    assert set(config.load_custom_presets(p)) == {"프리셋2"}


def test_custom_overlays_roundtrip(tmp_path):
    p = tmp_path / "config.local.json"
    assert config.load_custom_overlays(p) == []
    config.save_custom_overlays([{"x": 0, "y": 0, "w": 10, "h": 10}], p)
    assert len(config.load_custom_overlays(p)) == 1


def test_auto_preset_roundtrip_and_clear(tmp_path):
    p = tmp_path / "config.local.json"
    assert config.load_auto_preset(p) is None
    config.save_auto_preset("프리셋1", p)
    assert config.load_auto_preset(p) == "프리셋1"
    config.save_auto_preset(None, p)  # 해제
    assert config.load_auto_preset(p) is None


def test_deleting_auto_preset_clears_it(tmp_path):
    p = tmp_path / "config.local.json"
    config.save_custom_preset("프리셋1", [], p)
    config.save_auto_preset("프리셋1", p)
    config.delete_custom_preset("프리셋1", p)  # 자동 지정 프리셋 삭제
    assert config.load_auto_preset(p) is None


def _mgr(hwnd=123):
    """_desired_dwm 판정용 매니저(게임창 HWND 주입)."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui.mirror_manager import MirrorManager

    QApplication.instance() or QApplication([])
    mgr = MirrorManager(source_hwnd=lambda: hwnd)
    mgr._dwm_cap = True  # DWM 가능 환경으로 가정(비Windows 테스트에서도 로직 검증)
    return mgr


def test_desired_dwm_window_found_uses_dwm():
    """게임 창을 찾으면 DWM 썸네일(저부하)을 쓴다 — 전체창 여부로 가르지 않는다."""
    assert _mgr(hwnd=123)._desired_dwm() is True


def test_desired_dwm_no_window_falls_back():
    """게임 창을 못 찾으면(0) 붙을 소스가 없어 캡처(mss)로 폴백."""
    assert _mgr(hwnd=0)._desired_dwm() is False


def test_desired_dwm_force_capture_falls_back():
    """호환 캡처 모드 ON이면 창을 찾아도 항상 캡처(mss)로."""
    mgr = _mgr(hwnd=123)
    mgr._force_capture = True
    assert mgr._desired_dwm() is False


def test_custom_overlay_tab_constructs_without_crash():
    """실제 CustomOverlayTab 생성 경로(MirrorManager가 소스 공급자를 호출)에서
    __init__ 중 게임창 탐지로 크래시하지 않는지. (유닛 테스트의 lambda가 못 잡는 경로)"""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui.custom_overlay_tab import CustomOverlayTab

    QApplication.instance() or QApplication([])

    class _W:
        def is_game_active(self):
            return False

        def is_self_active(self):
            return True

    tab = CustomOverlayTab(_W())
    tab._mgr._tick()  # 첫 틱(_maybe_switch_mode 경로)도 안전해야 함
