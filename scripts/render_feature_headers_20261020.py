"""Capture approved shared headers on actual app widgets without external I/O."""
import argparse
import os
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from test_support.qt_runtime import configure_offscreen_fonts
configure_offscreen_fonts()
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QWidget
from mabinogi_addon import config
from mabinogi_addon.ui.main_window import MainWindow
from mabinogi_addon.ui.theme import apply_theme
from mabinogi_addon.ui.widgets import FeatureHeader
from test_support.boundaries import ExternalBoundaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--theme', choices=['light', 'dark'], default='light')
    parser.add_argument('--font-size', type=int, default=12)
    parser.add_argument('--height', type=int, default=800)
    parser.add_argument('--output', type=Path, default=Path('docs/qa/assets/feature_headers_20261020'))
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    apply_theme(args.theme)
    palette = QPalette(app.style().standardPalette())
    if args.theme == 'dark':
        # Offscreen Qt does not necessarily implement OS color-scheme changes.
        for role, color in ((QPalette.Window, '#202020'), (QPalette.WindowText, '#eeeeee'),
                            (QPalette.Base, '#272727'), (QPalette.Text, '#eeeeee'),
                            (QPalette.Button, '#333333'), (QPalette.ButtonText, '#eeeeee'),
                            (QPalette.PlaceholderText, '#aaaaaa'), (QPalette.Mid, '#555555')):
            palette.setColor(role, QColor(color))
    app.setPalette(palette)
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    with ExternalBoundaries() as boundary, patch.object(config, '_read_local_config', side_effect=lambda *a, **k: deepcopy({'general': {'skipSetup': True}})), patch.object(config, '_write_local_config'), patch.object(config, 'load_discord_user', return_value=None), patch.object(QApplication, 'quit'), patch('os._exit'):
        w = MainWindow()
        try:
            for widget in [w] + w.findChildren(QWidget):
                widget.setPalette(palette)
                font = widget.font()
                font.setPixelSize(args.font_size)
                widget.setFont(font)
            for header in w.findChildren(FeatureHeader):
                header._fit_title()
            w.show()
            shots = {}
            pages = [('buff', 0, 0), ('boss', 0, 2), ('resource', 0, 4), ('custom', 0, 5), ('distribution', 2, 0), ('bead', 2, 1), ('exchange', 2, 2), ('dungeon', 2, 3), ('party', 1, 0)]
            for name, main, sub in pages:
                w._tabs.setCurrentIndex(main)
                (w._tracker_tabs if main == 0 else w._convenience_tabs).setCurrentIndex(sub)
                w.setFixedSize(790, args.height)
                app.processEvents()
                shots[name] = w.grab(QRect(0, 0, 790, 330))
                assert w.grab().save(str(out / f'{name}.png'))
            for group, names in [('combat', ['buff', 'boss', 'resource', 'custom']), ('convenience', ['distribution', 'bead', 'exchange', 'dungeon'])]:
                sheet = QPixmap(1580, 660)
                painter = QPainter(sheet)
                for i, name in enumerate(names):
                    painter.drawPixmap((i % 2) * 790, (i // 2) * 330, shots[name])
                painter.end()
                assert sheet.save(str(out / f'{group}-comparison.png'))
        finally:
            w._force_quit = True
            w.close()
            app.processEvents()
        assert not boundary.violations


if __name__ == '__main__':
    main()
