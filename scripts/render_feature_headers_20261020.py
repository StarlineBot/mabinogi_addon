"""Capture approved shared headers on actual app widgets without external I/O."""
import argparse
import json
import os
import time
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from test_support.qt_runtime import configure_offscreen_fonts
configure_offscreen_fonts()
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QFontInfo, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QWidget
from mabinogi_addon import config
from mabinogi_addon.ui.main_window import MainWindow
from mabinogi_addon.ui.theme import apply_theme
from mabinogi_addon.ui.widgets import FeatureHeader
from test_support.boundaries import ExternalBoundaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all-pages', action='store_true', help='Include every combat page and the nested halo page')
    parser.add_argument('--native-font', action='store_true', help='Keep actual first-show fonts; do not refit titles')
    parser.add_argument('--sample-calculators', action='store_true', help='Inject in-memory sample prices without I/O')
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
                if not args.native_font:
                    font = widget.font()
                    font.setPixelSize(args.font_size)
                    widget.setFont(font)
            if not args.native_font:
                for header in w.findChildren(FeatureHeader):
                    header._fit_title()
            if args.sample_calculators:
                market = w.dungeon_cost_tab
                market._cache = (market._clock(), 10000, "조회 예시 · 경매 시세는 약 10분 지연됩니다.")
                market.dungeons.setCurrentRow(2)
                exchange = w.exchange_tab
                region = exchange.region_list.item(0).text()
                exchange._cache[region] = (time.time(), [{"name": "재료 예시", "per_unit": 100000, "coin": 10, "efficiency": 10000}])
                exchange.region_list.setCurrentRow(0)
            w.show()
            shots = {}
            measurements = {}
            pages = [('buff', 0, 0), ('boss', 0, 2), ('resource', 0, 4), ('custom', 0, 5), ('distribution', 2, 0), ('bead', 2, 1), ('exchange', 2, 2), ('dungeon', 2, 3), ('party', 1, 0)]
            if args.all_pages:
                pages += [('debuff', 0, 1), ('stat-bars', 0, 3), ('skillbar', 0, 6), ('memo', 0, 7), ('halo', 0, 2)]
            for name, main, sub in pages:
                w._tabs.setCurrentIndex(main)
                (w._tracker_tabs if main == 0 else w._convenience_tabs).setCurrentIndex(sub)
                if name in ("boss", "halo"):
                    w.boss_tab.pattern_tabs.setCurrentIndex(int(name == "halo"))
                w.setFixedSize(790, args.height)
                app.processEvents()
                shots[name] = w.grab(QRect(0, 0, 790, 330))
                assert w.grab().save(str(out / f'{name}.png'))
                measurements[name] = []
                for header in w.findChildren(FeatureHeader):
                    if not header.isVisible():
                        continue
                    font = QFontInfo(header.title.font())
                    measurements[name].append(dict(title=header.title.text(), family=font.family(),
                        pixels=font.pixelSize(), weight=font.weight(), title_height=header.title.height(),
                        metrics_height=header.title.fontMetrics().height(), description_y=header.description.y(),
                        divider_y=header.divider.y(), header_height=header.height(),
                        device_pixel_ratio=w.devicePixelRatioF()))
            for group, names in [('combat', ['buff', 'boss', 'resource', 'custom']), ('convenience', ['distribution', 'bead', 'exchange', 'dungeon'])]:
                sheet = QPixmap(1580, 660)
                painter = QPainter(sheet)
                for i, name in enumerate(names):
                    painter.drawPixmap((i % 2) * 790, (i // 2) * 330, shots[name])
                painter.end()
                assert sheet.save(str(out / f'{group}-comparison.png'))
            (out / 'headers.json').write_text(json.dumps(dict(theme=args.theme, native_font=args.native_font,
                pages=measurements), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        finally:
            w._force_quit = True
            w.close()
            app.processEvents()
        assert not boundary.violations


if __name__ == '__main__':
    main()
