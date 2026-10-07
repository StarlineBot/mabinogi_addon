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
