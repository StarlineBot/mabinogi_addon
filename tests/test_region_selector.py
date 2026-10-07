"""RegionSelector 크롭 저장(상태창에서 아이콘 가져오기) 테스트.

GUI는 띄우지 않고 _save_crop만 단위로 검증한다(오프스크린 QApplication).
"""


import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from mabinogi_addon.ui.region_selector import RegionSelector


@pytest.fixture(scope="module")
def _app():
    return QApplication.instance() or QApplication([])


def _shot() -> QPixmap:
    pm = QPixmap(100, 100)
    pm.fill(QColor("black"))
    p = QPainter(pm)
    p.fillRect(QRect(20, 20, 16, 16), QColor("red"))
    p.end()
    return pm


def test_save_crop_writes_png(_app, tmp_path):
    out = tmp_path / "icon.png"
    sel = RegionSelector(save_path=out)
    sel._shot = _shot()
    assert sel._save_crop(QRect(20, 20, 16, 16)) is True
    saved = QPixmap(str(out))
    assert (saved.width(), saved.height()) == (16, 16)


def test_save_crop_rejects_tiny(_app, tmp_path):
    sel = RegionSelector(save_path=tmp_path / "icon.png")
    sel._shot = _shot()
    assert sel._save_crop(QRect(0, 0, 1, 1)) is False


def test_save_crop_no_snapshot(_app, tmp_path):
    sel = RegionSelector(save_path=tmp_path / "icon.png")
    assert sel._save_crop(QRect(0, 0, 16, 16)) is False


def test_default_mode_has_no_save_path(_app):
    sel = RegionSelector()
    assert sel._save_path is None
