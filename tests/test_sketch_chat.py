"""그림대화 만들기(그림대화 명세 6절) — 파일 규격·서명·이름·캔버스·변환·탭.

시험 자료 zip에는 다른 사람의 캐릭터 이름·번호가 들어 있으므로 값은 출력하지 않고 바이트 비교만 한다.
"""

from __future__ import annotations

import os
import struct
import zipfile
import zlib
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from mabinogi_addon.sketch import convert, pngfile
from mabinogi_addon.sketch.canvas import BACKGROUND, GRAY_PALETTE, UNDO_LIMIT, SketchCanvas

ZIP = Path(__file__).parent / "data" / "chat_20250829_003739_레몬스케치.zip"


def _zip_files() -> dict[str, bytes]:
    with zipfile.ZipFile(ZIP) as z:
        return {Path(n).name: z.read(n) for n in z.namelist() if n.lower().endswith(".png")}


@pytest.fixture(scope="module")
def game_files():
    return _zip_files()


@pytest.fixture(scope="module")
def recent(game_files):
    return game_files[pngfile.RECENT_NAME]


def _kinds(data: bytes) -> list[bytes]:
    return [k for k, _, _ in pngfile.iter_chunks(data)]


def _ztxt(key: bytes, value: bytes) -> bytes:
    body = key + b"\0\0" + zlib.compress(value)
    return struct.pack(">I", len(body)) + b"zTXt" + body + struct.pack(">I", zlib.crc32(b"zTXt" + body))


def _png_with(chunks: list[bytes]) -> bytes:
    return pngfile.PNG_SIGNATURE + b"".join(chunks)


# --- 파일 규격 ---

def test_saved_file_matches_game_layout(recent):
    sig = pngfile.read_signature(recent)
    assert sig is not None
    c = SketchCanvas()
    c.stroke((3, 3), (200, 90), 0, 4)
    c.set_slot_color(1, (0x27, 0x7F, 0xFF))
    data = pngfile.encode_png(c.pixels, c.palette, sig)
    # 청크 순서가 게임 파일(recentchatimage.png)과 같다
    assert _kinds(data) == _kinds(recent) == [b"IHDR", b"PLTE", b"zTXt", b"zTXt", b"IDAT", b"IEND"]
    chunks = {k: b for k, b, _ in pngfile.iter_chunks(data) if k in (b"IHDR", b"PLTE")}
    assert struct.unpack(">IIBBBBB", chunks[b"IHDR"]) == (256, 96, 2, 3, 0, 0, 0)
    assert len(chunks[b"PLTE"]) == 12
    indices, palette = pngfile.decode_indices(data)
    assert np.array_equal(indices, c.pixels)
    assert palette == c.palette


def test_signature_chunks_are_copied_byte_for_byte(recent):
    sig = pngfile.read_signature(recent)
    data = pngfile.encode_png(np.zeros((96, 256), np.uint8), list(GRAY_PALETTE), sig)
    src = [raw for k, _, raw in pngfile.iter_chunks(recent) if k == b"zTXt"]
    out = [raw for k, _, raw in pngfile.iter_chunks(data) if k == b"zTXt"]
    assert out == src  # 길이·종류·내용·CRC까지 그대로


def test_only_recentchatimage_can_be_signature_source(tmp_path, game_files):
    """받은 그림(chat_…png)은 서명이 있어도 원본으로 고를 수 없다(사칭 방지)."""
    received = [n for n in game_files if n.startswith("chat_")]
    assert received
    for name in received:
        assert pngfile.read_signature(game_files[name]) is not None  # 서명은 들어 있지만
        path = tmp_path / name
        path.write_bytes(game_files[name])
        assert pngfile.read_signature_file(path) is None  # 원본으로는 안 된다
    path = tmp_path / pngfile.RECENT_NAME
    path.write_bytes(game_files[pngfile.RECENT_NAME])
    assert pngfile.read_signature_file(path) is not None


@pytest.mark.parametrize("chunks", [
    [],  # 서명 없음
    [_ztxt(b"author", "잡곡".encode("cp949"))],  # 번호 없음
    [_ztxt(b"authid", b"0"), _ztxt(b"author", "잡곡".encode("cp949"))],  # 가짜 번호 0
    [_ztxt(b"authid", b"12a"), _ztxt(b"author", "잡곡".encode("cp949"))],
    [_ztxt(b"authid", b"123"), _ztxt(b"author", b"")],
])
def test_missing_or_fake_signature_is_rejected(chunks):
    assert pngfile.read_signature(_png_with(chunks)) is None


def test_signature_name_is_cp949():
    sig = pngfile.read_signature(_png_with([_ztxt(b"authid", b"-598887370"), _ztxt(b"author", "잡곡".encode("cp949"))]))
    assert sig is not None and sig.author == "잡곡"


def test_not_png_is_rejected():
    assert pngfile.read_signature(b"hello") is None


# --- 파일 이름 ---

def test_filename_rule_and_collision():
    when = datetime(2026, 10, 31, 13, 0, 0, 123456)
    assert pngfile.chat_filename("잡곡", when) == "chat_20261031_130000_잡곡.png"
    taken = {"chat_20261031_130000_잡곡.png", "chat_20261031_130001_잡곡.png"}
    assert pngfile.chat_filename("잡곡", when, taken.__contains__) == "chat_20261031_130002_잡곡.png"
    assert pngfile.chat_filename('a/b:c', when) == "chat_20261031_130000_a_b_c.png"


# --- 캔버스 ---

def test_canvas_starts_white_slot4_and_fill():
    c = SketchCanvas()
    assert (c.pixels == BACKGROUND).all() and c.palette == GRAY_PALETTE
    c.rect((10, 10), (50, 40), 0, 1)
    c.fill((30, 25), 1)  # 네모 안만
    assert c.pixels[25, 30] == 1 and c.pixels[0, 0] == BACKGROUND and c.pixels[10, 10] == 0
    c.fill((0, 0), 2)  # 바깥만
    assert c.pixels[0, 0] == 2 and c.pixels[25, 30] == 1


def test_undo_redo_and_limit():
    c = SketchCanvas()
    c.checkpoint()
    c.stroke((0, 0), (255, 95), 0, 2)
    drawn = c.pixels.copy()
    assert c.undo() and (c.pixels == BACKGROUND).all()
    assert c.redo() and np.array_equal(c.pixels, drawn)
    for i in range(UNDO_LIMIT + 20):
        c.checkpoint()
        c.stroke((i % 256, 0), (i % 256, 95), i % 3, 1)
    undone = 0
    while c.undo():
        undone += 1
    assert undone == UNDO_LIMIT


def test_empty_action_does_not_leave_undo_step():
    c = SketchCanvas()
    c.checkpoint()
    c.fill((5, 5), BACKGROUND)  # 같은 색 채우기 = 바뀐 것 없음
    c.discard_checkpoint()
    assert not c.can_undo()


def test_slot_color_change_recolors_everything_drawn_with_it():
    c = SketchCanvas()
    c.stroke((0, 0), (100, 0), 1, 1)
    before = c.pixels.copy()
    c.checkpoint()
    c.set_slot_color(1, (255, 0, 0))
    assert np.array_equal(c.pixels, before)  # 칸 번호는 그대로
    assert tuple(c.rgb()[0, 50]) == (255, 0, 0)  # 그 칸으로 그린 곳은 모두 새 색
    assert c.undo() and c.palette == GRAY_PALETTE


def test_picker_reads_slot():
    c = SketchCanvas()
    c.stroke((7, 7), (7, 7), 2, 1)
    assert c.pick((7, 7)) == 2 and c.pick((300, 7)) is None


# --- 변환 ---

def _gradient() -> np.ndarray:
    x = np.linspace(0, 255, 256, dtype=np.float32)
    img = np.zeros((96, 256, 3), np.float32)
    img[..., 0] = x
    img[..., 1] = x[::-1]
    img[..., 2] = 128
    return img


def test_fit_box_is_8_by_3():
    x, y, w, h = convert.fit_box(1000, 1000)
    assert (w, round(h / 3 * 8)) == (1000, 1000) and y == (1000 - h) // 2


@pytest.mark.parametrize("mode", convert.MODES)
@pytest.mark.parametrize("dither", [False, True])
def test_convert_shapes_and_palette_order(mode, dither):
    indices, palette = convert.convert(_gradient(), mode, dither)
    assert indices.shape == (96, 256) and indices.dtype == np.uint8 and indices.max() <= 3
    assert len(palette) == 4
    lum = [r * 0.299 + g * 0.587 + b * 0.114 for r, g, b in palette]
    assert lum == sorted(lum)  # 어두운 색 → 밝은 색(4번 칸 = 가장 밝음 = 지우개)
    if mode == "gray":
        assert palette == GRAY_PALETTE


def test_dither_mixes_neighbouring_slots():
    flat = np.full((96, 256, 3), 160, np.float32)  # 회색 128과 192 사이
    plain = convert.quantize(flat, GRAY_PALETTE, dither=False, gray=True)
    dots = convert.quantize(flat, GRAY_PALETTE, dither=True, gray=True)
    assert len(np.unique(plain)) == 1
    assert set(np.unique(dots)) == {1, 2}


def test_convert_is_deterministic():
    a = convert.convert(_gradient(), "vivid", False)
    b = convert.convert(_gradient(), "vivid", False)
    assert np.array_equal(a[0], b[0]) and a[1] == b[1]


# --- 탭 ---

@pytest.fixture
def tab(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from mabinogi_addon.ui import sketch_tab as st

    folder = tmp_path / "문서" / "마비노기" / "그림대화"
    monkeypatch.setattr(st, "default_sketch_dir", lambda: folder)
    t = st.SketchTab()
    yield t, folder
    t.close()


def test_save_disabled_without_signature(tab):
    t, _ = tab
    t.refresh_signature()
    assert not t.save_btn.isEnabled()
    assert "게임에서 그림대화를 한 번 그리면 서명을 가져올 수 있어요" in t.signature_label.text()


def test_save_writes_game_file_with_signature(tab, recent, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    t, folder = tab
    folder.mkdir(parents=True)
    (folder / pngfile.RECENT_NAME).write_bytes(recent)
    t.refresh_signature()
    assert t.save_btn.isEnabled() and "recentchatimage.png" in t.signature_label.text()
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda _p, _t, text, *a: asked.append(text) or QMessageBox.StandardButton.Yes)
    path = t.save()
    assert asked == [f"이 서명으로 저장해요: {t.signature.author}"]
    assert path is not None and path.parent == folder
    assert path.name.startswith("chat_") and path.name.endswith(f"_{t.signature.author}.png")
    data = path.read_bytes()
    assert _kinds(data) == _kinds(recent)
    assert [r for k, _, r in pngfile.iter_chunks(data) if k == b"zTXt"] == \
        [r for k, _, r in pngfile.iter_chunks(recent) if k == b"zTXt"]


def test_cancelled_confirm_writes_nothing(tab, recent, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    t, folder = tab
    folder.mkdir(parents=True)
    (folder / pngfile.RECENT_NAME).write_bytes(recent)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    assert t.save() is None
    assert [p.name for p in folder.iterdir()] == [pngfile.RECENT_NAME]


def test_tab_drawing_tools_and_undo(tab):
    from PySide6.QtCore import QPointF

    t, _ = tab
    t.set_slot(0)
    t.set_tool("line")
    t.press(QPointF(0, 10))
    t.drag(QPointF(255, 50))
    t.release(QPointF(10, 10))  # 직선은 마지막 위치 기준으로만 남는다
    assert (t.canvas.pixels[10, 0:11] == 0).all() and t.canvas.pixels[50, 255] == BACKGROUND
    t.set_tool("picker")
    t.press(QPointF(5, 10))
    assert t.slot == 0 and t.tool == "pen"
    t.undo()
    assert (t.canvas.pixels == BACKGROUND).all() and t.redo_btn.isEnabled()


def test_import_overwrites_canvas_and_is_undoable(tab):
    from PySide6.QtGui import QColor, QImage
    from mabinogi_addon.ui.sketch_import_dialog import SketchImportDialog

    t, _ = tab
    img = QImage(800, 300, QImage.Format.Format_RGB32)
    img.fill(QColor("black"))
    dlg = SketchImportDialog(img, t.canvas.palette, t)
    dlg.refresh()
    t.apply_import(dlg)
    dlg.close()
    assert (t.canvas.pixels == 0).mean() > 0.9
    assert t.palette_combo.currentData() == "gray"
    t.undo()
    assert (t.canvas.pixels == BACKGROUND).all()


def test_long_save_folder_does_not_widen_tab(tab, monkeypatch, tmp_path):
    """QA 0.35.0: 바꾼 저장 위치(긴 경로)를 그대로 넣어 탭 최소 폭이 930이 되고 오른쪽(실제 크기·[변경])이 잘렸다."""
    from PySide6.QtWidgets import QApplication
    from mabinogi_addon import config

    t, _ = tab
    long_dir = tmp_path / ("아주긴폴더이름" * 20)[:120]
    assert len(str(long_dir)) >= 120
    config.save_sketch_dir(str(long_dir))
    t.refresh_signature()
    assert t.folder_label.full_text() == str(long_dir) and t.folder_label.toolTip() == str(long_dir)
    assert t.minimumSizeHint().width() <= 790
    t.resize(790, 900)
    t.show()
    QApplication.processEvents()
    btn = t.folder_btn.geometry()
    btn.moveTopLeft(t.folder_btn.mapTo(t, btn.topLeft() - btn.topLeft()))
    assert t.rect().contains(btn)
    assert t.save_btn.mapTo(t, t.save_btn.rect().bottomRight()).x() <= t.width()
    shown = t.folder_label.text()
    assert "…" in shown and len(shown) < len(str(long_dir))
