"""Independent arithmetic, real async pagination, shutdown and actual-page layout."""

from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QWidget

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_navigation import window  # noqa: E402,F401
from mabinogi_addon import config  # noqa: E402
from mabinogi_addon.market import dungeon_cost as calc  # noqa: E402
from mabinogi_addon.ui import dungeon_cost_tab as ui  # noqa: E402


def settle(app):
    for _ in range(12):
        app.processEvents()


def pump_until(app, condition):
    deadline = time.monotonic() + 3
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.002)
    assert condition()


def test_all_approved_ticket_rows_and_material_quantities():
    expected = (
        [40, 70, 80, 60, 10, -140, -390, -840, -1490, -2440, -7390],
        [120, 230, 320, 380, 410, 340, 170, -200, -770, -1640, -6510],
        [160, 310, 440, 540, 610, 580, 450, 120, -410, -1240, -6070],
    )
    prices = [10, 20, 40, 70, 100, 200, 300, 500, 700, 1000, 5000, 5000]
    for name, profits in zip(("크롬바스 심연", "브리레흐", "탈라가흐"), expected):
        rows = calc.ticket_rows(name, 12)
        assert [r[1] for r in rows] == [p * 10000 for p in prices]
        assert [r[2] for r in rows[:11]] == [p * 10000 for p in profits]
        assert sum(r[1] for r in rows) == 129400000
    rows = calc.rift_rows(10000, 12)
    assert [r[1] for r in rows] == [1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    assert [r[3] for r in rows] == [p * 10000 for p in (1, 2, 4, 7, 11, 16, 22, 29, 37, 46, 56, 67)]


@pytest.mark.parametrize("closing", [False, True])
def test_real_worker_pagination_switch_and_main_shutdown(window, monkeypatch, closing):
    w, app = window
    tab = w.dungeon_cost_tab
    w._tabs.setCurrentWidget(w._convenience_tabs)
    w._convenience_tabs.setCurrentIndex(3)
    tab.dungeons.setCurrentRow(2)
    entered, release = threading.Event(), threading.Event()
    workers, requests = [], []
    before = deepcopy(config._read_local_config())
    monkeypatch.setattr(config, "get_nexon_api_key", lambda: "QA-not-a-real-key")

    def open_page(request, timeout):
        assert 0 < timeout <= 10
        workers.append(threading.current_thread())
        params = parse_qs(urlsplit(request.full_url).query)
        requests.append(params)
        assert params["item_name"] == ["균열의 편린"]
        if len(requests) == 1:
            entered.set()
            assert release.wait(3)
        payload = {"auction_item": [{"item_display_name": "균열의 편린",
                    "auction_price_per_unit": 20000 if len(requests) == 1 else 10000,
                    "auction_price": 999999999}],
                   "next_cursor": "next" if len(requests) == 1 else None}
        return BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(ui.urllib.request, "urlopen", open_page)
    try:
        tab.refresh.click()
        pump_until(app, entered.is_set)
        assert tab._price is None and not tab.refresh.isEnabled()
        tab._request()
        assert len(requests) == 1
        tab.dungeons.setCurrentRow(1)
        settle(app)
        assert tab.table.item(1, 2).text() == "+2,300,000"
        assert config._read_local_config() == before
        if closing:
            w._force_quit = True
            w.close()
            assert tab._cancelled.is_set()
            assert not tab._poll.isActive() and tab._pending is None
        release.set()
        if not closing:
            pump_until(app, lambda: tab._pending is None)
            assert tab.title.text() == "브리레흐"
            tab.dungeons.setCurrentRow(2)
            assert tab._price == 10000
            assert tab.table.item(10, 3).text() == "560,000"
            assert requests[1]["cursor"] == ["next"]
            assert not tab._poll.isActive()
        if not closing:
            assert config._read_local_config() == before
    finally:
        release.set()
        for worker in set(workers):
            worker.join(timeout=3)
            assert not worker.is_alive()
    if closing:
        assert len(requests) == 1


@pytest.mark.parametrize("font_size", [12, 20])
def test_actual_main_page_table_values_are_readable(window, font_size, tmp_path):
    w, app = window
    tab = w.dungeon_cost_tab
    for widget in w.findChildren(QWidget):
        font = widget.font()
        font.setPixelSize(font_size)
        widget.setFont(font)
    w._tabs.setCurrentWidget(w._convenience_tabs)
    w._convenience_tabs.setCurrentIndex(3)
    before = deepcopy(config._read_local_config())
    timers = set(w.findChildren(QTimer))
    tab._price = 10000
    tab._status = "QA sample"
    for i in range(4):
        tab.dungeons.setCurrentRow(i)
        settle(app)
        assert w.grab().save(str(tmp_path / f"dungeon-{i}-{font_size}.png"))
        page = w._convenience_tabs.currentWidget()
        assert page.horizontalScrollBar().maximum() == 0
        assert tab.table.horizontalScrollBar().maximum() == 0
        metrics = QFontMetrics(tab.table.font())
        for row in range(tab.table.rowCount()):
            for column in range(tab.table.columnCount()):
                text = tab.table.item(row, column).text()
                assert metrics.horizontalAdvance(text) + 8 <= tab.table.columnWidth(column), (
                    font_size, i, row, column, text, tab.table.columnWidth(column))
    assert config._read_local_config() == before
    assert set(w.findChildren(QTimer)) == timers
    assert not tab._poll.isActive()
