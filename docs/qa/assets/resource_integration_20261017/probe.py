"""Independent actual-pixel integration and large-font control geometry."""

from itertools import product
from pathlib import Path, PureWindowsPath
import sys
from types import SimpleNamespace
from zipfile import ZipFile

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QAbstractButton, QWidget

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads
from test_navigation import window
from mabinogi_addon.detect.tuarim_reader import read_percent


def png(archive, name):
    with ZipFile(ROOT / "tests/data" / archive) as source:
        image = cv2.imdecode(np.frombuffer(source.read(name), np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return image


@pytest.mark.parametrize("dorcha,percent,alert", list(product((False, True), repeat=3)))
def test_real_source_pixels_share_one_percent_reader(window, monkeypatch, dorcha, percent, alert):
    w, app = window
    d, t, r = w.dorcha_tab, w.tuarim_tab, w.resource_tab
    high = png("투아림게이지 샘플 모음.zip", "새 폴더 (2)/v04_5789.png")
    hundred = png("투아림게이지 샘플 모음.zip", "새 폴더 (2)/v04_5845.png")
    game = png("autofind_20261016T192204168176Z_e70b6c5c.zip", "input.png")
    assert read_percent(high) == 95 and read_percent(hundred) is None
    watcher = SimpleNamespace(is_game_active=lambda: True, is_self_active=lambda: False)
    d._watcher = t._watcher = watcher
    target = (101, 202, 0, 0, 3840, 2160)
    monkeypatch.setattr(d, "_search_target", lambda: target)
    sample = {"percent": high}
    calls = {"percent": 0, "dorcha": 0}
    fired = []

    def capture_percent(*args):
        calls["percent"] += 1
        return sample["percent"].copy()

    def capture_dorcha(x, y, width, height):
        calls["dorcha"] += 1
        return game[y:y + height, x:x + width].copy()

    monkeypatch.setattr(t, "_grab_rect", capture_percent)
    monkeypatch.setattr(d, "_grab_rect", capture_dorcha)
    monkeypatch.setattr(t, "_play", fired.append)
    t._apply_region(560, 150, 58, 28)
    d.enable.setChecked(dorcha)
    r.percent_chk.setChecked(percent)
    t.enable.setChecked(alert)
    d._apply_region(534, 122, 28, 23)

    def pump(count=4):
        for _ in range(count):
            t._tick_enabled()
            d._tick()

    pump()
    assert calls == {"percent": 4 if percent or alert else 0, "dorcha": 4 if dorcha else 0}
    assert fired == ([90, 95] if alert else [])
    if dorcha or percent:
        assert d._overlay.isVisible()
        assert d._overlay.percent == (95 if percent else None)
        assert d._overlay.value == (0 if dorcha else None)
    else:
        assert d._overlay is None or not d._overlay.isVisible()
    sample["percent"] = hundred
    pump()
    if percent:
        assert d._overlay.percent is None
    if dorcha:
        assert d._overlay.value == 0
    sample["percent"] = high
    pump()
    if percent:
        assert d._overlay.percent == 95
    assert fired == ([90, 95] if alert else [])
    for _ in range(3):
        r.percent_chk.setChecked(not percent)
        pump()
        r.percent_chk.setChecked(percent)
        pump()
    assert fired == ([90, 95] if alert else [])
    d.enable.setChecked(False)
    r.percent_chk.setChecked(False)
    t.enable.setChecked(False)
    before = dict(calls)
    pump()
    assert calls == before
    assert d._overlay is None or not d._overlay.isVisible()


@pytest.mark.parametrize("font_size", [13, 20])
@pytest.mark.parametrize("expanded", [False, True])
def test_integrated_controls_fit_with_expanded_diagnostics(window, font_size, expanded):
    w, app = window
    t, d, r = w.tuarim_tab, w.dorcha_tab, w.resource_tab
    t._shot_dir = PureWindowsPath("C:/Users/runneradmin/AppData/Local/Temp") / ("긴 경로" * 25) / "tuarim_shots"
    t._update_collect_label()
    for widget in w.findChildren(QWidget):
        font = widget.font()
        font.setPixelSize(font_size)
        widget.setFont(font)
    w._open_setup_feature("dorcha")
    r.diagnostics_btn.setChecked(expanded)
    for _ in range(10):
        app.processEvents()
    scroll = w._combat_pages["dorcha"]
    assert w._combat_pages["tuarim"] is scroll
    assert w._tracker_tabs.count() == 8
    assert scroll.horizontalScrollBar().maximum() == 0
    failures = []
    for button in r.findChildren(QAbstractButton):
        if not button.isVisible():
            continue
        scroll.ensureWidgetVisible(button)
        for _ in range(3):
            app.processEvents()
        rectangle = QRect(button.mapTo(scroll.viewport(), QPoint()), button.size())
        if not scroll.viewport().rect().contains(rectangle):
            failures.append((button.text(), str(rectangle)))
    assert not failures, failures
    scroll.verticalScrollBar().setValue(0)
    for _ in range(5):
        app.processEvents()
    assert w.grab().save(f"/tmp/qa-resource-integration-{font_size}-{int(expanded)}.png")


def test_actual_overlay_modes_render_without_layout_changes(window):
    from mabinogi_addon.ui.dorcha_overlay import DorchaOverlay
    _, app = window
    overlay = DorchaOverlay(1.5)
    size = overlay.size()
    board = QImage(size.width() * 2 + 30, (size.height() + 12) * 4,
                   QImage.Format.Format_ARGB32)
    board.fill(QColor(24, 26, 28))
    painter = QPainter(board)
    try:
        for row, (show_d, show_t) in enumerate(((True, False), (False, True), (True, True), (True, True))):
            overlay.set_elements(show_d, show_t)
            for column, valid in enumerate((True, False)):
                overlay.set_value((0 if row == 3 else 13) if valid else None)
                overlay.set_percent((0 if row == 3 else 95) if valid else None)
                assert overlay.size() == size
                overlay.render(painter, QPoint(column * (size.width() + 15), row * (size.height() + 12)))
        assert board.save("/tmp/qa-resource-overlay-modes.png")
    finally:
        painter.end()
        overlay.close()
        overlay.deleteLater()
        app.processEvents()
