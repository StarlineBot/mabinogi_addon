import cv2
import numpy as np

from mabinogi_addon.catalog import delete_buff, load_catalog, register_buff


def _png(path, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.full((16, 16, 3), color, dtype=np.uint8))


def test_register_and_delete(tmp_path):
    icon_dir = tmp_path / "icon"
    image_dir = tmp_path / "image"
    src_icon = tmp_path / "src_icon.png"
    src_img = tmp_path / "src_img.png"
    _png(src_icon, (0, 0, 255))
    _png(src_img, (0, 255, 0))

    bid = register_buff("글렌", src_icon, src_img, icon_dir=icon_dir, image_dir=image_dir)
    assert bid == "글렌"

    catalog = load_catalog(icon_dir=icon_dir, image_dir=image_dir)
    by_id = {b.id: b for b in catalog}
    assert "글렌" in by_id
    assert by_id["글렌"].display_image is not None

    delete_buff("글렌", icon_dir=icon_dir, image_dir=image_dir)
    catalog = load_catalog(icon_dir=icon_dir, image_dir=image_dir)
    assert "글렌" not in {b.id for b in catalog}


def test_register_without_display(tmp_path):
    icon_dir = tmp_path / "icon"
    image_dir = tmp_path / "image"
    src_icon = tmp_path / "s.png"
    _png(src_icon, (1, 2, 3))
    register_buff("쿤", src_icon, None, icon_dir=icon_dir, image_dir=image_dir)
    by_id = {b.id: b for b in load_catalog(icon_dir=icon_dir, image_dir=image_dir)}
    assert by_id["쿤"].display_image is None


def test_register_empty_name_raises(tmp_path):
    src = tmp_path / "s.png"
    _png(src, (0, 0, 0))
    try:
        register_buff("  ", src, None, icon_dir=tmp_path / "i", image_dir=tmp_path / "m")
        raised = False
    except ValueError:
        raised = True
    assert raised
