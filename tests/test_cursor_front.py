"""0.38.1 마우스 커서: 반짝이 더 잘 보이게(채도·굵기 섞기) + 커서 창이 미러링·오버레이 뒤로 숨지 않게."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget

from mabinogi_addon.ui import cursor_paint, overlay_capture
from test_cursor_fx import _run, fx  # noqa: F401  (픽스처)


# ---- 1) 반짝이 -----------------------------------------------------------------------------------
def test_sparkle_color_saturation_and_chosen_color_kept():
    for i in range(12):
        c = cursor_paint.sparkle_color(i, True, "#FFFFFF")
        assert c.hsvSaturationF() == pytest.approx(0.85, abs=0.01) and c.valueF() == pytest.approx(1.0)
    assert cursor_paint.sparkle_color(4, False, "#1DD3B0") == QColor("#1DD3B0")  # 고른 색은 그대로


def test_sparkle_bold_every_third_piece():
    assert [cursor_paint.sparkle_stroke(i) for i in range(6)] == [
        (2.6, 0.8), (1.5, 0.0), (1.5, 0.0), (2.6, 0.8), (1.5, 0.0), (1.5, 0.0)]


class _Rec:
    """그리기 기록용 가짜 QPainter(펜 굵기·+ 팔 길이)."""

    def __init__(self):
        self.pens, self.lines = [], []

    def setRenderHint(self, *a):
        pass

    def setPen(self, pen):
        self.pens.append((round(pen.widthF(), 2), pen.color()))

    def drawLine(self, a, b):
        self.lines.append(max(abs(b.x() - a.x()), abs(b.y() - a.y())) / 2)


@pytest.mark.parametrize("multicolor", [True, False])
def test_particles_mix_bold_and_thin(multicolor):
    p = _Rec()
    parts = [SimpleNamespace(x=50.0, y=50.0, age=0.0, index=i, radius=4.0) for i in range(6)]
    cursor_paint.paint_particles(p, parts, "sparkle", "#FF5A5F", 1.0, multicolor=multicolor)
    assert [w for w, _ in p.pens] == [2.6, 1.5, 1.5, 2.6, 1.5, 1.5]
    arms = p.lines[::2]  # 조각마다 가로·세로 2줄
    assert arms[0] == pytest.approx(arms[1] + 0.8)  # 굵은 조각은 팔 +0.8px(크기·수명은 그대로)
    if not multicolor:
        assert {c.name() for _, c in p.pens} == {"#ff5a5f"}


# ---- 2) 커서 창이 항상 앞 -------------------------------------------------------------------------
class MirrorOverlay(QWidget):  # 이름으로 오버레이 판정(overlay_capture.OVERLAYS)
    def __init__(self):
        super().__init__()
        overlay_capture.watch(self)


@pytest.fixture
def order(monkeypatch):
    """창 순서 기록: 오버레이가 뜨거나 올려지면 'overlay', 커서 창을 맨 앞으로 올리면 그 창."""
    from mabinogi_addon.system import zorder
    seq = []
    monkeypatch.setattr(zorder, "bring_to_front", lambda w: seq.append(w))
    return seq


def test_cursor_returns_to_front_after_overlay_show_and_raise(fx, order, monkeypatch):
    f, clock, pos, watcher = fx
    app = QApplication.instance()
    f.update_settings(enabled=True)
    _run(f, clock, 0.2)
    assert f._ring.isVisible()
    app.processEvents()
    order.clear()
    mirror = MirrorOverlay()
    monkeypatch.setattr(mirror, "raise_", lambda: order.append("overlay"))
    try:
        mirror.show()  # 게임 창 전환 등으로 다시 뜸
        order.append("overlay")
        app.processEvents()
        assert order == ["overlay", f._ring]  # 보이는 커서 창만(숨은 선·꼬리 창은 안 건드림)
        overlay_capture.raise_overlay(mirror)  # 보스 패턴 알림·예고 목록의 raise_ 경로
        overlay_capture.raise_overlay(mirror)
        app.processEvents()
        assert order[-1] is f._ring and order[2:] == ["overlay", "overlay", f._ring]  # 여러 번 올려도 한 번에 묶음
        mirror.hide()
        mirror.show()
        app.processEvents()
        assert order[-1] is f._ring
    finally:
        mirror.close()
        mirror.deleteLater()


def test_cursor_tick_never_changes_window_order(fx, order):
    f, clock, pos, watcher = fx
    f.update_settings(enabled=True, tail="sparkle")
    QApplication.instance().processEvents()
    order.clear()
    step = [0]

    def move():
        step[0] += 1
        pos[0] = (400 + step[0] * 7, 300 + step[0] % 5)
    _run(f, clock, 0.5, move=move)  # 커서 틱은 이동·다시 그리기만(0.36~0.37 성능 작업)
    QApplication.instance().processEvents()
    assert order == []


def test_pattern_and_upcoming_overlays_raise_through_helper():
    from pathlib import Path
    root = Path(cursor_paint.__file__).parent
    for name in ("pattern_overlay.py", "boss_tab.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert ".raise_()" not in text, name  # 커서 창을 다시 앞으로 올리는 raise_overlay를 쓴다


# ---- 3) 기본색으로 되돌리기(0.38.1 버그 수정) ---------------------------------------------------------
def test_yellow_swatch_returns_to_default_colors(fx):
    """예전엔 견본을 한 번 누르면 colorChosen=True가 계속 남아 노랑을 다시 눌러도 반짝이 노랑 단색·불꽃 노랑 계열이었다."""
    from mabinogi_addon import config
    from mabinogi_addon.cursor_fx import clean_settings, fire_stops, sparkle_multicolor, FIRE_STOPS
    from mabinogi_addon.ui.cursor_tab import CursorTab, _Swatch

    f, *_ = fx
    tab = CursorTab(f)
    try:
        sw = {w.hex: w for w in tab.findChildren(_Swatch)}
        tab.settings["tail"] = "sparkle"
        seen = []
        for hex_color in ("#FFD43B", "#1DD3B0", "#FFD43B"):
            sw[hex_color].click()
            saved = clean_settings(config.load_cursor_fx())
            seen.append((saved["color"], saved["colorChosen"], sparkle_multicolor(saved)))
        assert seen == [("#FFD43B", False, True), ("#1DD3B0", True, False), ("#FFD43B", False, True)]
        # 불꽃: 기본 상태면 기본 불꽃색(fire_stops(None)), 고른 색이면 그 색 계열
        assert fire_stops(None) == FIRE_STOPS and fire_stops("#1DD3B0") != FIRE_STOPS
        # '+'(직접 고르기)로 정확히 노랑을 골라도 같은 규칙(대소문자 무관)
        tab._choose_color("#A78BFA")
        assert f.settings["colorChosen"] is True
        tab._choose_color("#ffd43b")
        assert f.settings["colorChosen"] is False and f.settings["color"] == "#FFD43B"
        assert tab.color_note.text() == "노랑(기본)을 고르면 반짝이는 여러 색, 불꽃은 기본 불꽃색으로 보여요."
    finally:
        tab.deleteLater()
