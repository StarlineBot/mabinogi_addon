"""Independent opt-in QA; no real Windows settings or network calls."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QGroupBox, QPushButton

from conftest import _isolated_runtime, _no_leaked_qthreads
from test_navigation import window
from mabinogi_addon import config
from mabinogi_addon.ui import optimization_controller as module
from mabinogi_addon.ui.widgets import FeatureHeader


def test_repeated_permission_and_tab_changes_keep_one_owner(window, monkeypatch):
    w, app = window
    c = w.optimization_tools
    panel, engine, collector, timer = c.panel, c.engine, c.collector, c.timer
    timers = set(w.findChildren(QTimer))
    before = config._read_local_config()
    allowed = [False]
    monkeypatch.setattr(module, 'is_creator', lambda: allowed[0])
    for _ in range(100):
        allowed[0] = True
        c.refresh_access()
        assert w._tabs.indexOf(panel) == 3
        assert w._tabs.widget(4) is w._settings_scroll
        w._tabs.setCurrentWidget(panel)
        panel.tabs.setCurrentIndex(1)
        panel.tabs.setCurrentIndex(0)
        allowed[0] = False
        c.refresh_access()
        assert w._tabs.indexOf(panel) == -1
        assert w._tabs.currentWidget() is w._settings_scroll
    assert (c.panel, c.engine, c.collector, c.timer) == (panel, engine, collector, timer)
    assert set(w.findChildren(QTimer)) == timers
    assert not c.frames and not c.engine.busy and c._overlay is None
    assert config._read_local_config() == before


def test_real_pages_share_headers_and_fit_fixed_app_width(window, monkeypatch, tmp_path):
    w, app = window
    monkeypatch.setattr(module, 'is_creator', lambda: True)
    c = w.optimization_tools
    c.open()
    baseline = w.custom_overlay_tab.findChild(FeatureHeader)
    assert baseline is not None
    rows = []
    for index, count in ((0, 4), (1, 3)):
        c.panel.tabs.setCurrentIndex(index)
        for _ in range(8):
            app.processEvents()
        area = c.panel.tabs.currentWidget()
        page, view = area.widget(), area.viewport()
        header = page.findChild(FeatureHeader)
        assert header.title.font() == baseline.title.font()
        assert header.description.foregroundRole() == baseline.description.foregroundRole()
        assert header.divider.height() == baseline.divider.height() == 1
        assert len(page.findChildren(QGroupBox)) == count
        assert page.width() <= view.width()
        for button in page.findChildren(QPushButton):
            point = button.mapTo(page, QPoint())
            assert point.x() >= 0 and point.x() + button.width() <= page.width()
            assert button.width() >= button.minimumSizeHint().width()
        path = tmp_path / ('optimization' if index == 0 else 'fps')
        assert w.grab().save(str(path.with_suffix('.png')))
        rows.append(dict(page=index, viewport=[view.width(), view.height()],
                         content=[page.width(), page.height()], groups=count))
    print('LAYOUT_EVIDENCE', json.dumps(rows))


def test_busy_other_worker_cannot_hide_one_stuck_case(tmp_path):
    suite = tmp_path / 'suite'
    suite.mkdir()
    (suite / 'test_busy.py').write_text(
        'import threading,time,pytest\n'
        'def test_stuck(): threading.Event().wait()\n'
        '@pytest.mark.parametrize("n", range(100))\n'
        'def test_progress(n): time.sleep(.05)\n', encoding='utf-8')
    root = Path(__file__).resolve().parents[1]
    diagnostics = tmp_path / 'diagnostics'
    result = subprocess.run(
        [sys.executable, '-m', 'scripts.run_regressions',
         '--diagnostics', str(diagnostics), '--case-timeout', '2',
         '--session-timeout', '20', '--stack-interval', '.25',
         '--', '-n', '2', '-q', str(suite)],
        cwd=root, capture_output=True, text=True, timeout=25)
    assert result.returncode == 124, result.stdout + result.stderr
    assert 'case timeout' in result.stdout and 'test_stuck' in result.stdout
    records = [json.loads(line) for path in diagnostics.glob('run-*/*.jsonl')
               for line in path.read_text(encoding='utf-8').splitlines()]
    assert any(r['node'].endswith('test_progress') and r.get('outcome') == 'passed'
               for r in records)
    assert any(r['node'].endswith('test_stuck') and r['phase'] == 'call'
               for r in records)
