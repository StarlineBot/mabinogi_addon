import numpy as np

from mabinogi_addon import image_io
from mabinogi_addon.capture import FileFrameSource, Region


def _write_png(path, w, h, color):
    img = np.full((h, w, 3), color, dtype=np.uint8)
    assert image_io.imwrite(path, img)


def test_file_source_yields_frames_in_order(tmp_path):
    _write_png(tmp_path / "a.png", 10, 10, (0, 0, 255))
    _write_png(tmp_path / "b.png", 10, 10, (0, 255, 0))
    src = FileFrameSource(tmp_path, loop=False)

    f1 = src.grab()
    f2 = src.grab()
    assert f1 is not None and f1.shape == (10, 10, 3)
    assert f2 is not None
    assert src.grab() is None  # loop=False → 소진되면 None


def test_file_source_region_crop(tmp_path):
    _write_png(tmp_path / "full.png", 100, 80, (50, 50, 50))
    src = FileFrameSource([tmp_path / "full.png"], region=Region(10, 20, 30, 40))
    frame = src.grab()
    assert frame.shape == (40, 30, 3)  # (h, w, 3)


def test_file_source_loops(tmp_path):
    _write_png(tmp_path / "only.png", 8, 8, (1, 2, 3))
    src = FileFrameSource([tmp_path / "only.png"], loop=True)
    assert src.grab() is not None
    assert src.grab() is not None  # 반복
