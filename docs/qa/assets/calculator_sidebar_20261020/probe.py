"""Measure existing calculator sidebars without network or product edits.

PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen python -m pytest
docs/qa/assets/calculator_sidebar_20261020/probe.py -q -s
"""

import json
from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'tests'))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from mabinogi_addon.ui.dungeon_cost_tab import DungeonCostTab  # noqa: E402
from mabinogi_addon.ui.exchange_tab import ExchangeTab  # noqa: E402


def test_measure_current_sidebar_difference(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ExchangeTab, '_work', lambda *args: None)
    cost, exchange = DungeonCostTab(), ExchangeTab()
    try:
        for widget in (cost, exchange):
            widget.resize(790, 760)
            widget.show()
        app.processEvents()
        results = {}
        for name, sidebar in [('entry', cost.dungeons), ('exchange', exchange.region_list)]:
            rect = sidebar.visualItemRect(sidebar.item(0))
            results[name] = {'width': sidebar.width(), 'item_height': rect.height(),
                             'local_stylesheet': sidebar.styleSheet()}
        print(json.dumps(results, ensure_ascii=True, sort_keys=True))
        assert results['entry']['width'] == 152
        assert results['exchange']['width'] == 120
        assert results['entry']['item_height'] > results['exchange']['item_height']
        assert 'padding:14px 8px' in results['entry']['local_stylesheet']
    finally:
        cost.shutdown()
        for widget in (cost, exchange):
            widget.close()
            widget.deleteLater()
        app.processEvents()
