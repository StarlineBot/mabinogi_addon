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


def _mgr_for_mode(monkeypatch, win_size, screen_size):
    """_desired_dwm 판정용 매니저(게임창 크기·화면크기 주입)."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui.mirror_manager import MirrorManager

    QApplication.instance() or QApplication([])
    mgr = MirrorManager(source_hwnd=lambda: 123)
    mgr._dwm_cap = True  # DWM 가능 환경으로 가정(비Windows 테스트에서도 로직 검증)
    ww, wh = win_size
    monkeypatch.setattr(
        "mabinogi_addon.system.dwm_thumbnail.window_rect",
        lambda hwnd: (0, 0, ww, wh),
    )
    monkeypatch.setattr(MirrorManager, "_screen_size", staticmethod(lambda: screen_size))
    return mgr


def test_desired_dwm_windowed_uses_dwm(monkeypatch):
    """창 모드(화면보다 작은 창)면 DWM 썸네일을 쓴다."""
    mgr = _mgr_for_mode(monkeypatch, win_size=(1280, 720), screen_size=(3840, 2160))
    assert mgr._desired_dwm() is True


def test_desired_dwm_fullscreen_falls_back(monkeypatch):
    """전체 창(화면 95%+ 덮음)이면 DWM 불가로 보고 mss/dxcam 폴백."""
    mgr = _mgr_for_mode(monkeypatch, win_size=(3840, 2160), screen_size=(3840, 2160))
    assert mgr._desired_dwm() is False


def test_desired_dwm_no_window_falls_back(monkeypatch):
    """게임 창을 못 찾으면(0) DWM 불가 → mss/dxcam 폴백."""
    mgr = _mgr_for_mode(monkeypatch, win_size=(1280, 720), screen_size=(3840, 2160))
    mgr._source_hwnd = lambda: 0
    assert mgr._desired_dwm() is False
