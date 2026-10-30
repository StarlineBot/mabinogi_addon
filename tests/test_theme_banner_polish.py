"""0.31.1 QA: 잠금 테두리 강조색, 배너 ✕ 호버 색, 홈 위 업데이트 배너(시안 A)."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

from mabinogi_addon.ui import palette
from mabinogi_addon.ui.settings_layout import lock_style
from test_navigation import window  # noqa: F401  (픽스처)


def _pump(app, times=4):
    for _ in range(times):
        app.processEvents()


def _theme(w, app, name, accent=None):
    values = {"background": "#1B1E24", "accent": accent, "content": "auto"} if name == "custom" else None
    w.settings_tab._apply_theme(name, values, save=False)
    _pump(app)


def _rule(sheet, selector):
    start = sheet.index(selector + " {")
    return sheet[start:sheet.index("}", start) + 1]


def test_lock_border_follows_accent_in_every_theme(window):
    w, app = window
    try:
        for name, accent in (("dark", None), ("light", None), ("custom", "#F59E7B"), ("custom", "#5B8DEF")):
            _theme(w, app, name, accent)
            assert "#00856b" not in lock_style().lower()
            assert f"border-color:{palette.color('accent')}" in lock_style()
            # 이미 만들어진 잠금 버튼도 즉시 같은 값으로 다시 칠해진다
            locks = [b for b in w.findChildren(QPushButton) if "QPushButton:checked:enabled" in b.styleSheet()]
            assert locks and all(b.styleSheet() == lock_style() for b in locks)
    finally:
        _theme(w, app, "dark")


def test_banner_close_hover_stays_white_across_theme_switches(window):
    w, app = window
    banner = w._update_banner
    try:
        for name, accent in (("system", None), ("custom", "#F59E7B"), ("dark", None), ("custom", "#5B8DEF")):
            _theme(w, app, name, accent)
            sheet = banner.styleSheet()
            assert "#ffffff" in _rule(sheet, "#updateClose:hover").lower()  # 예전: 강조 위 글자(검정)로 바뀜
            assert palette.color("on-accent").lower() in _rule(sheet, "#updateBtn").lower()
            assert palette.color("accent").lower() in _rule(sheet, "#updateBtn").lower()
    finally:
        _theme(w, app, "dark")


def test_restyle_swaps_on_accent_only_inside_accent_block():
    from PySide6.QtWidgets import QLabel
    label = QLabel()
    label.setStyleSheet("#a { background:#00C9A2; color:#062F28; } #b { color:#062F28; }")
    before = {**{n: palette.color(n, dark=True) for n in palette.COLORS}}
    after = {**before, "accent": "#5B8DEF", "on-accent": "#FFFFFF"}
    palette.restyle(before, after, [label])
    assert label.styleSheet() == "#a { background:#5B8DEF; color:#FFFFFF; } #b { color:#062F28; }"


def test_home_leaves_room_for_update_banner_and_banner_is_clickable(window):
    w, app = window
    w._show_home()
    _pump(app)
    full = w.centralWidget().rect()
    assert w.home_page.geometry() == full
    w.show_update_banner("9.9.9")
    _pump(app)
    banner = w._update_banner
    assert banner.isVisible() and banner.height() > 0
    assert w.home_page.geometry().top() == banner.geometry().bottom() + 1
    assert w.home_page.geometry().bottom() == full.bottom()
    # 배너 버튼이 홈에 가리지 않고 눌린다
    clicked = []
    btn = banner.findChild(QPushButton, "updateBtn")
    btn.clicked.disconnect()
    btn.clicked.connect(lambda: clicked.append(1))
    center = btn.mapTo(w.centralWidget(), btn.rect().center())
    assert w.centralWidget().childAt(center) is btn
    QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
    assert clicked
    # 창 크기를 바꿔도 배너 아래 유지
    w.resize(w.width(), w.height() + 40)
    _pump(app)
    assert w.home_page.geometry().top() == banner.geometry().bottom() + 1
    assert w.home_page.geometry().bottom() == w.centralWidget().rect().bottom()
    # ✕로 숨기면 홈이 다시 창 전체
    close = banner.findChild(QPushButton, "updateClose")
    QTest.mouseClick(close, Qt.MouseButton.LeftButton)
    _pump(app)
    assert not banner.isVisible()
    assert w.home_page.geometry() == w.centralWidget().rect()


def test_home_800_with_banner_and_three_setup_rows_has_no_scroll(window):
    from mabinogi_addon import config, setup_state
    from test_home_page import _all_regions
    w, app = window
    _all_regions()
    raw = config._read_local_config()
    for key in ("haloTimer", "skillbar", "memoTracker"):
        raw.pop(key)
    config._write_local_config(raw)
    for key in ("halo_timer", "skillbar", "memo"):
        setup_state.save_selection(key, True)
    w.creator_dialogue.enabled = False  # 잡담 꺼짐 = 기준 창 790×800
    w.show_update_banner("9.9.9")
    w._show_home()
    w.creator_dialogue.refresh()
    _pump(app, 8)
    assert w.height() == 800 and len(w._home_state()["needs"]) == 3
    assert w.home_page.geometry().top() > 0
    assert w.home_page.scroll.verticalScrollBar().maximum() == 0
    w._update_banner_hide()
    _pump(app)
    assert w.home_page.geometry() == w.centralWidget().rect()
    assert w.home_page.scroll.verticalScrollBar().maximum() == 0
