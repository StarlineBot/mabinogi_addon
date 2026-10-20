"""Collect every combat page's geometry before reporting any width failure."""

from pathlib import PureWindowsPath
import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QAbstractButton, QWidget
from test_navigation import window
from test_support.scroll_visibility import assert_control_reachable

pytestmark = pytest.mark.usefixtures('tuarim_width_diagnostics')


@pytest.mark.parametrize('area',[(0,0,900,1000),(0,0,800,600),(-1600,120,900,700)])
def test_all_pages_and_controls_large_font(window,monkeypatch,area):
    w,app = window
    screen = type(app.primaryScreen())
    monkeypatch.setattr(screen,'availableGeometry',lambda self:QRect(*area))
    monkeypatch.setattr(screen,'geometry',lambda self:QRect(*area))
    path = PureWindowsPath('C:/Users/runneradmin/AppData/Local/Temp/pytest-of-runneradmin/pytest-0/test_seeded_navigation_and_tou3/app/data')/('긴경로'*35)/'수집 폴더'
    for tab in (w.tuarim_tab,w.boss_tab,w.stat_bars_tab):
        tab._shot_dir = path
        tab._update_collect_label()
    for widget in w.findChildren(QWidget):
        font = widget.font(); font.setPixelSize(20); widget.setFont(font)
    failures = []
    for key,scroll in w._combat_pages.items():
        w._open_setup_feature(key)
        for _ in range(10): app.processEvents()
        extent = scroll.horizontalScrollBar().maximum()
        if extent:
            failures.append((key,'horizontal_range',extent,scroll.viewport().width(),scroll.widget().minimumSizeHint().width()))
        for widget in scroll.widget().findChildren(QAbstractButton):
            if not widget.isVisible(): continue
            try:
                assert_control_reachable(widget, app, key)
            except AssertionError as exc:
                failures.append((key,widget.text(),str(exc)))
    assert not failures, failures


@pytest.mark.parametrize('theme', ['light', 'dark'])
@pytest.mark.parametrize('pixels', [12, 20])
def test_shared_headers_wrap_without_losing_controls_or_saved_state(window, theme, pixels):
    from copy import deepcopy
    from PySide6.QtGui import QColor, QFontInfo, QPalette
    from mabinogi_addon import config
    from mabinogi_addon.ui.theme import apply_theme
    from mabinogi_addon.ui.widgets import FeatureHeader
    w, app = window
    old_scheme = app.styleHints().colorScheme()
    old_palette = QPalette(app.palette())
    apply_theme(theme)
    # The offscreen plugin need not implement OS scheme switching. Exercise
    # actual dark/light palette roles as well as the requested scheme.
    palette = QPalette(app.style().standardPalette())
    if theme == 'dark':
        for role, color in ((QPalette.Window, '#202020'), (QPalette.WindowText, '#eeeeee'),
                            (QPalette.Base, '#272727'), (QPalette.Text, '#eeeeee'),
                            (QPalette.Button, '#333333'), (QPalette.ButtonText, '#eeeeee'),
                            (QPalette.PlaceholderText, '#aaaaaa'), (QPalette.Mid, '#555555')):
            palette.setColor(role, QColor(color))
    app.setPalette(palette)
    for widget in [w] + w.findChildren(QWidget):
        widget.setPalette(palette)
        font = widget.font()
        font.setPixelSize(pixels)
        widget.setFont(font)
    for header in w.findChildren(FeatureHeader):
        header._fit_title()
    before = deepcopy(config._read_local_config())
    try:
        pages = [(0, i) for i in range(w._tracker_tabs.count())]
        pages += [(2, i) for i in range(w._convenience_tabs.count())] + [(1, 0)]
        for main, sub in pages:
            w._tabs.setCurrentIndex(main)
            if main != 1:
                (w._tracker_tabs if main == 0 else w._convenience_tabs).setCurrentIndex(sub)
            app.processEvents()
            scroll = w._tabs.widget(1) if main == 1 else (w._tracker_tabs if main == 0 else w._convenience_tabs).currentWidget()
            headers = [h for h in scroll.widget().findChildren(FeatureHeader) if h.isVisible()]
            assert headers, (main, sub)
            for header in headers:
                assert QFontInfo(header.description.font()).pixelSize() == pixels
                assert QFontInfo(header.title.font()).pixelSize() > pixels
                assert header.description.foregroundRole() == QPalette.PlaceholderText
                assert header.description.palette().color(QPalette.Window).lightness() < 128 if theme == 'dark' else header.description.palette().color(QPalette.Window).lightness() >= 128
                assert header.description.y() > header.title.y() + header.title.height() - 1
                assert header.divider.y() >= header.description.y() + header.description.height()
                assert header.title.width() > 0 and header.description.width() > 0
            assert scroll.horizontalScrollBar().maximum() == 0, (main, sub)
        # Both nested boss pages use the shared path.
        w._tabs.setCurrentIndex(0)
        w._tracker_tabs.setCurrentIndex(2)
        w.boss_tab.pattern_tabs.setCurrentIndex(1)
        app.processEvents()
        assert w.boss_tab.halo_capture.findChildren(FeatureHeader)
        assert not w.settings_tab.findChildren(FeatureHeader)
        assert config._read_local_config() == before
    finally:
        app.styleHints().setColorScheme(old_scheme)
        app.setPalette(old_palette)


def test_initial_header_font_and_title_row_do_not_depend_on_help_button(window):
    from test_support.regressions.feature_header import initial_header_metrics
    observed = initial_header_metrics(window)
    resource, custom = observed['dorcha'], observed['custom']
    for key in ('pixels', 'family', 'weight', 'height'):
        assert resource['title'][key] == custom['title'][key]
    assert resource['title']['height'] >= resource['title']['metrics_height']
    assert resource['header']['height'] == custom['header']['height']
