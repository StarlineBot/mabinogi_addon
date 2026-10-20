"""Approved usability layouts rendered from actual widgets with isolated sample state."""

from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRect, QTimer
from PySide6.QtGui import QFont, QPixmap, QPainter, QColor, QPalette
from PySide6.QtWidgets import QApplication, QGroupBox, QWidget

from mabinogi_addon import config, paths, catalog
from mabinogi_addon.ui.main_window import MainWindow
from mabinogi_addon.ui.theme import apply_theme
from test_support.boundaries import ExternalBoundaries


def settle(app):
    for _ in range(12):
        app.processEvents()


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    out = Path('/tmp/usability-polish-preview')
    out.mkdir(exist_ok=True)
    raw = {'general': {'skipSetup': True, 'gameExe': 'Client.exe',
                      'setupSelection': {'buff': True, 'debuff': True, 'boss': True}},
           'buffTracker': {'enabled': False}, 'debuffTracker': {'enabled': False},
           'memo': {'text': '## 던전 메모\n- 준비물 확인\n- **보스 패턴**'},
           'haloTimer': {'enabled': False}, 'dorcha': {'showTuarim': False, 'enabled': True}}
    metrics = []
    screen_area = {"height": 900}
    light_palette = QPalette(app.palette())
    with ExitStack() as stack:
        boundary = stack.enter_context(ExternalBoundaries())
        temporary = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(patch.object(config, 'LOCAL_CONFIG_PATH', temporary/'config.json'))
        stack.enter_context(patch.object(paths, 'user_data_dir', lambda: temporary/'data'))
        load_catalog, load_debuff = catalog.load_catalog, catalog.load_debuff_catalog
        stack.enter_context(patch.object(catalog, 'load_catalog', lambda: load_catalog(
            icon_dirs=(catalog.DEFAULT_ICON_DIR,), image_dirs=(catalog.DEFAULT_IMAGE_DIR,))))
        stack.enter_context(patch.object(catalog, 'load_debuff_catalog', lambda: load_debuff(
            icon_dirs=(catalog.DEFAULT_DEBUFF_ICON_DIR,))))
        stack.enter_context(patch.object(config, '_read_local_config', lambda *a, **k: deepcopy(raw)))
        def write(data, *a, **k):
            raw.clear()
            raw.update(deepcopy(data))
        stack.enter_context(patch.object(config, '_write_local_config', write))
        stack.enter_context(patch.object(config, 'load_discord_user', lambda: None))
        stack.enter_context(patch.object(QApplication, 'quit', lambda: None))
        stack.enter_context(patch('os._exit', lambda *a: None))
        stack.enter_context(patch.object(type(app.primaryScreen()), 'availableGeometry',
                                         lambda self: QRect(0, 0, 1024, screen_area["height"])))
        window = MainWindow()
        window._post_show_done = True
        try:
            window.show()
            for timer in window.findChildren(QTimer):
                if timer is not window.setup_guide._fit_timer:
                    timer.stop()
            original = deepcopy(raw)
            for theme, pixels, height in (('dark',12,800), ('light',12,800), ('dark',20,620), ('light',28,620)):
                apply_theme(theme)
                palette = QPalette(light_palette)
                if theme == 'dark':
                    for role, color in ((QPalette.Window,'#202020'),(QPalette.WindowText,'#eeeeee'),
                        (QPalette.Base,'#272727'),(QPalette.Text,'#eeeeee'),(QPalette.Button,'#333333'),
                        (QPalette.ButtonText,'#eeeeee'),(QPalette.Mid,'#555555'),
                        (QPalette.Highlight,'#337d79'),(QPalette.HighlightedText,'#ffffff')):
                        palette.setColor(role, QColor(color))
                app.setPalette(palette)
                screen_area["height"] = height + 32
                window.creator_dialogue.refresh()
                for widget in [window] + window.findChildren(QWidget):
                    widget.setPalette(palette)
                    font = QFont(widget.font())
                    font.setPixelSize(pixels)
                    widget.setFont(font)
                window._open_guide()
                guide = window.setup_guide
                for stage in range(3):
                    guide.stage = stage
                    guide.refresh()
                    settle(app)
                    assert window.height() == height, (window.height(), height)
                    assert guide.rect().contains(guide.next_btn.mapTo(guide, guide.next_btn.rect().bottomRight()))
                    assert guide.body_scroll.horizontalScrollBar().maximum() == 0
                    assert guide.selection.horizontalScrollBar().maximum() == 0
                    assert guide.selection.verticalScrollBar().maximum() == 0
                    assert guide.manual_buttons['debuff'].isEnabled()
                    assert not guide.checks['halo_timer'].isVisible()
                    for _, group, _ in guide.groups.values():
                        if group.isVisible():
                            assert group.verticalScrollBar().maximum() == 0, (theme,pixels,stage,'result-height')
                    image = out/f'{theme}-{pixels}-guide-{stage}.png'
                    assert window.grab().save(str(image))
                    metrics.append(dict(theme=theme, pixels=pixels, stage=stage,
                                        body_scroll=guide.body_scroll.verticalScrollBar().maximum()))
                if pixels == 12:
                    raw['buffTracker']['captureRegion'] = dict(x=10,y=20,w=300,h=400)
                    guide.stage = 1
                    guide.outcomes.update(debuff='디버프 줄·보스 체력바를 찾지 못함',
                                          boss='보스 체력바를 찾지 못함')
                    guide.refresh()
                    settle(app)
                    assert window.grab().save(str(out/f'{theme}-{pixels}-guide-result.png'))
                    raw['buffTracker'].pop('captureRegion')
                guide.active = False
                window.dorcha_tab.preview.set_elements(True, False)
                window.dorcha_tab.preview.set_value(None)
                for key in ('debuff','dorcha','memo','custom'):
                    window._open_setup_feature(key)
                    settle(app)
                    scroll = window._combat_pages[key]
                    assert scroll.horizontalScrollBar().maximum() == 0, (theme,pixels,key)
                    assert window.grab().save(str(out/f'{theme}-{pixels}-{key}.png'))
                window._pages.setCurrentWidget(window._tabs)
                window._tabs.setCurrentIndex(3)
                general = next(g for g in window.settings_tab.findChildren(QGroupBox) if g.title()=='일반')
                window._tabs.currentWidget().ensureWidgetVisible(general)
                settle(app)
                assert general.grab().save(str(out/f'{theme}-{pixels}-settings-general.png'))
                assert raw == original, 'rendering must not change sample settings'
            assert not boundary.violations, boundary.violations
            (out/'metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
            contact(out, ['dark-12-guide-result.png','dark-12-debuff.png','dark-12-dorcha.png','dark-12-memo.png'], 'overview.png')
            print(out)
        finally:
            window._force_quit = True
            window.close()
            settle(app)


def contact(out, paths, name):
    images = [QPixmap(str(out/path)) for path in paths]
    width = 790
    height = max(i.height() for i in images)
    sheet = QPixmap(width*2, height*2)
    sheet.fill(QColor('#171717'))
    painter = QPainter(sheet)
    for index, image in enumerate(images):
        painter.drawPixmap((index%2)*width,(index//2)*height,image)
    painter.end()
    assert sheet.save(str(out/name))


if __name__ == '__main__':
    main()
