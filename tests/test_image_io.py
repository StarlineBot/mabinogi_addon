"""유니코드 경로 이미지 로더 테스트(Windows 한글 경로 대응)."""

import cv2
import numpy as np

from mabinogi_addon.image_io import imread


def test_imread_korean_filename(tmp_path):
    img = np.zeros((6, 8, 3), np.uint8)
    img[:, :, 2] = 255  # 빨강(BGR)
    path = tmp_path / "공격력 감소.png"
    ok, buf = cv2.imencode(".png", img)  # 인코딩 후 유니코드 경로에 바이트로 기록
    assert ok
    path.write_bytes(buf.tobytes())

    loaded = imread(path, cv2.IMREAD_COLOR)
    assert loaded is not None
    assert loaded.shape == (6, 8, 3)
    assert int(loaded[0, 0, 2]) == 255


def test_imread_missing_returns_none(tmp_path):
    assert imread(tmp_path / "없음.png") is None
