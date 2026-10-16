from pathlib import Path

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.detect import dorcha_reader as reader

DATA = Path(__file__).parent / "data"
NEW = [(10,"210734"),(12,"210747"),(11,"210757"),(8,"210805"),(7,"210815"),
       (9,"211332"),(6,"211343"),(5,"211352"),(5,"211414"),(3,"211420"),
       (2,"211426"),(1,"211435"),(13,"211456"),(14,"211458"),(15,"211914"),(4,"212007")]
OLD = [(0,"2026-10-09 185117",708,875),(9,"2026-10-07 013118",708,875),
       (7,"2026-10-09 190901",708,875),(7,"2026-10-09 190905",708,875),
       (10,"2026-10-09 190926",708,875),(8,"2026-10-09 191035",706,873),
       (8,"2026-10-09 200715",708,875),(8,"2026-10-09 200724",708,875),
       (13,"2026-10-10 190116",708,875),(13,"2026-10-12 000512",706,873),
       (15,"2026-10-12 200511",931,929),(11,"2026-10-12 200625",931,929),
       (15,"2026-10-14 000646",933,931),(9,"2026-10-15 213313",931,929),
       (3,"2026-10-15 213734",931,929)]


def crop(stamp, x=None, y=None):
    frame = image_io.imread(DATA / f"스크린샷 {stamp}.png")
    assert frame is not None
    if x is None:
        x, y = (931,929) if frame.shape[0] == 1436 else (933,931)
    return frame[y+17:y+40, x+8:x+36].copy()


@pytest.mark.parametrize("value,stamp", NEW)
def test_new_native_words(value, stamp):
    assert reader.read_dorcha(crop("2026-10-16 " + stamp)) == value


@pytest.mark.parametrize("value,stamp,x,y", OLD)
def test_old_native_words_not_used_to_build_reference(value, stamp, x, y):
    assert reader.read_dorcha(crop(stamp,x,y)) == value


@pytest.mark.parametrize("side", ["left", "right", "top", "bottom"])
def test_partial_thirteen_cannot_become_a_single_digit(side):
    image = crop("2026-10-16 211456")
    if side == "left": image[:,:14] = 0
    elif side == "right": image[:,14:] = 0
    elif side == "top": image[:12] = 0
    else: image[12:] = 0
    assert reader.read_dorcha(image) is None


@pytest.mark.parametrize("value", [0,100,255])
def test_empty_or_uniform_is_not_zero(value):
    assert reader.read_dorcha(np.full((23,28,3),value,np.uint8)) is None


@pytest.mark.parametrize("factor", [.75,1.25,1.5,2])
def test_synthetic_rescaling_is_separate_from_native_input(factor):
    image = crop("2026-10-16 211456")
    image = cv2.resize(image,None,fx=factor,fy=factor,interpolation=cv2.INTER_NEAREST)
    result = reader.read_dorcha(image)
    assert result in (None,13), "uncertain scale must not invent another resource value"


def test_missing_references_fail_closed(monkeypatch):
    monkeypatch.setattr(reader,"_REFS",None)
    assert reader.read_dorcha(crop("2026-10-16 211456")) is None


@pytest.mark.parametrize("word",[16,17,18,19])
def test_synthetic_out_of_range_word_is_not_clamped(word):
    base = crop("2026-10-16 211456")
    source = {6:"211343",7:"210815",8:"210805",9:"211332"}[word%10]
    last = crop("2026-10-16 "+source)
    base[:,14:] = 0
    base[:,15:22] = last[:,11:18]
    assert reader.read_dorcha(base) is None


def test_corrupt_reference_file_is_safe(tmp_path,monkeypatch):
    root = tmp_path/"dorcha"
    root.mkdir()
    np.savez(root/"refs.npz",refs=np.zeros((1,330)),labels=np.zeros((1,1),dtype=int))
    monkeypatch.setattr(reader.paths,"detect_templates_dir",lambda:tmp_path)
    assert reader._load() is None
