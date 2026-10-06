from importlib import metadata

import pytest


def test_package_imports():
    import mabinogi_addon.capture  # noqa: F401
    import mabinogi_addon.detect  # noqa: F401
    import mabinogi_addon.tracker  # noqa: F401
    import mabinogi_addon.ui  # noqa: F401
    import mabinogi_addon.system  # noqa: F401


def test_opencv_is_headless():
    # 일반판 opencv-python은 자체 Qt를 포함해 PySide6와 충돌한다
    metadata.version("opencv-python-headless")
    with pytest.raises(metadata.PackageNotFoundError):
        metadata.version("opencv-python")
