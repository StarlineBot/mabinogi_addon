import queue
import threading
import time

import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon.market import dungeon_cost as calc
from mabinogi_addon.ui import dungeon_cost_tab as ui


@pytest.mark.parametrize('name,best,profit,loss', [
    (calc.NAMES[0], 3, 800_000, 6),
    (calc.NAMES[1], 5, 4_100_000, 8),
    (calc.NAMES[3], 5, 6_100_000, 9),
])
def test_ticket_math(name, best, profit, loss):
    rows = calc.ticket_rows(name, 12)
    assert max(rows, key=lambda row: row[2]) == rows[best-1]
    assert rows[best-1][2] == profit
    assert next(n for n, _, p in rows if p < 0) == loss
    assert rows[10][1] == rows[11][1] == 50_000_000
    assert 12 * calc.REWARDS[name] - rows[11][2] == 129_400_000
    assert all(p == n * calc.REWARDS[name] - sum(r[1] for r in rows[:n]) for n, _, p in rows)


def test_rift_math_and_unknown_price():
    rows = calc.rift_rows(10_000, 6)
    assert [r[1] for r in rows] == [1, 1, 2, 3, 4, 5]
    assert [r[3] for r in rows] == [10000, 20000, 40000, 70000, 110000, 160000]
    assert all(row[2:] == (None, None) for row in calc.rift_rows(None))
    assert calc.ticket_rows(calc.NAMES[1])[1][2] == 2_300_000


@pytest.fixture
def tab():
    app = QApplication.instance() or QApplication([])
    widget = ui.DungeonCostTab()
    widget.resize(740, 650)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_no_key_keeps_quantities_unknown_cost(tab, monkeypatch):
    monkeypatch.setattr(ui.config, 'get_nexon_api_key', lambda: '')
    tab.dungeons.setCurrentRow(2)
    tab._request()
    assert 'API 키' in tab.status.text()
    assert tab.table.item(5, 1).text() == '5'
    assert tab.table.item(5, 3).text() == '—'
    assert not tab._poll.isActive()


@pytest.mark.parametrize('price,error,message', [(None,'','매물이 없습니다'), (None,'조회 실패','조회 실패'), (10000,'','조회')])
def test_result_never_overwrites_selected_dungeon(tab, price, error, message):
    tab.dungeons.setCurrentRow(2)
    tab._pending = queue.Queue()
    tab._poll.start()
    tab.dungeons.setCurrentRow(1)
    tab._pending.put((price,error))
    tab._receive()
    assert tab.title.text() == calc.NAMES[1]
    assert tab.table.item(1,2).text() == '+2,300,000'
    assert not tab._poll.isActive()
    tab.dungeons.setCurrentRow(2)
    assert message in tab.status.text()
    assert tab.table.item(0,3).text() == ('—' if price is None else '10,000')


@pytest.mark.parametrize('value', [10000, None, -1, '10000', True])
def test_worker_unit_price_and_invalid_response(monkeypatch, value):
    monkeypatch.setattr(ui.auction, 'fetch_items_by_name', lambda *a, **k: [
        {'item_display_name':calc.MATERIAL,'auction_price_per_unit':value,'auction_price':999999}])
    result = queue.Queue()
    ui._fetch(result, 'fake', threading.Event())
    price,error = result.get_nowait()
    if value is None or type(value) is int and value > 0:
        assert (price,error) == (value,'')
    else:
        assert price is None and error


def test_worker_error_and_cancel_before_network(monkeypatch):
    def fetch(*args, **kwargs):
        return kwargs['urlopen'](None, timeout=10)
    monkeypatch.setattr(ui.auction, 'fetch_items_by_name', fetch)
    monkeypatch.setattr(ui.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('network called'))
    cancelled = threading.Event()
    cancelled.set()
    result = queue.Queue()
    ui._fetch(result, 'fake', cancelled)
    assert result.get_nowait()[1]


def test_shutdown_and_duplicate_request(tab, monkeypatch):
    tab._pending = queue.Queue()
    monkeypatch.setattr(ui.config, 'get_nexon_api_key', lambda: pytest.fail('duplicate request'))
    tab._request()
    tab._poll.start()
    tab.shutdown()
    assert tab._cancelled.is_set()
    assert not tab._poll.isActive()
    assert tab._pending is None


def test_width_and_no_idle_timer(tab):
    for i in range(4):
        tab.dungeons.setCurrentRow(i)
        QApplication.processEvents()
        assert tab.table.horizontalScrollBar().maximum() == 0
        assert not tab._poll.isActive()


def test_repeated_async_refresh_and_no_old_price(tab, monkeypatch):
    monkeypatch.setattr(ui.config, 'get_nexon_api_key', lambda: 'fake')
    threads = []
    def fetch(*a, **k):
        threads.append(threading.current_thread())
        return [{'item_display_name':calc.MATERIAL,'auction_price_per_unit':len(threads)*10000}]
    monkeypatch.setattr(ui.auction, 'fetch_items_by_name', fetch)
    tab.dungeons.setCurrentRow(2)
    for n in range(1,21):
        tab._request()
        assert tab._price is None
        assert not tab.refresh.isEnabled()
        assert tab.table.item(0,3).text() == '—'
        deadline = time.monotonic()+3
        while tab._pending is not None and time.monotonic() < deadline:
            tab._receive()
            time.sleep(.001)
        assert tab._pending is None
        assert tab._price == n*10000
        assert tab.refresh.isEnabled()
        assert not tab._poll.isActive()
    for thread in threads:
        thread.join(timeout=1)
        assert not thread.is_alive()


def test_worker_network_failure_does_not_expose_exception(monkeypatch):
    def fail(*a, **k):
        raise OSError('secret-key-in-url')
    monkeypatch.setattr(ui.auction, 'fetch_items_by_name', fail)
    result = queue.Queue()
    ui._fetch(result, 'fake', threading.Event())
    price,error = result.get_nowait()
    assert price is None and '실패' in error
    assert 'secret' not in error
