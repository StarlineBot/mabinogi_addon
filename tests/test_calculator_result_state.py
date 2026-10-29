"""No network on input edits; results retain their exact request/input identity."""

from PySide6.QtWidgets import QApplication

from mabinogi_addon.market.fee import calc_distribution
from mabinogi_addon.ui.distribution_tab import DistributionTab
from mabinogi_addon.ui.exchange_tab import ExchangeTab


def test_distribution_edits_and_out_of_order_results(monkeypatch):
    QApplication.instance() or QApplication([])
    requests = []

    class Thread:
        def __init__(self, *, target, args, daemon):
            self.args = args

        def start(self):
            requests.append(self.args)

    monkeypatch.setattr("mabinogi_addon.ui.distribution_tab.threading.Thread", Thread)
    tab = DistributionTab()
    try:
        tab.price_spin.setValue(100)
        tab.count_spin.setValue(4)
        assert requests == []
        tab._on_calc()
        first = requests[-1]
        tab.price_spin.setValue(200)
        assert "입력이 변경됨" in tab.result_status.text()
        assert len(requests) == 1
        tab._on_calc()
        second = requests[-1]

        def payload(request):
            serial, sale, count, membership = request
            return serial, calc_distribution(sale, count, membership, {}), sale, count, membership, ""

        tab._show(payload(second))
        before = tab._result_input
        tab._show(payload(first))
        assert tab._result_input == before == (2000000, 4, True)
        assert tab.result_status.text() == "계산 완료"
        tab.count_spin.setValue(5)
        assert tab.result_status.text() == "입력 변경됨 · 아래는 이전 계산 결과"
        assert len(requests) == 2
        tab.count_spin.setValue(4)
        assert tab.result_status.text() == "계산 완료"
        tab._on_calc()
        third = requests[-1]
        tab.price_spin.setValue(0)
        tab._on_calc()
        tab._show(payload(third))
        assert tab._result_input is None
    finally:
        tab.close()


def test_exchange_failure_is_not_left_as_loading():
    QApplication.instance() or QApplication([])
    tab = ExchangeTab()
    try:
        tab._pending = "test"
        tab.asof.setText("시세 확인 중")
        tab._show_fail(("test", "읽기 실패"))
        assert tab.asof.text() == "시세 조회 실패"
        assert tab.table.item(0, 0).text() == "읽기 실패"
    finally:
        tab.close()


def test_distribution_worker_signal_keeps_request_and_input_identity(monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr("mabinogi_addon.ui.distribution_tab.config.get_nexon_api_key", lambda: None)
    tab = DistributionTab()
    try:
        tab.price_spin.setValue(100)
        tab.count_spin.setValue(2)
        tab._request_id = 7
        tab._work(7, *tab._inputs())
        assert tab._result_input == tab._inputs()
        assert tab.result_status.text() == "계산 완료"
        assert "API 키" in tab.note_lbl.text()
    finally:
        tab.close()


def test_sidebar_font_growth_and_return_preserve_selection(monkeypatch):
    from PySide6.QtGui import QFont
    from mabinogi_addon.ui.dungeon_cost_tab import DungeonCostTab

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ExchangeTab, '_work', lambda *args: None)
    cost, exchange = DungeonCostTab(), ExchangeTab()
    sidebars = (cost.dungeons, exchange.region_list)
    try:
        for widget in (cost, exchange):
            widget.resize(790, 760)
            widget.show()
        for sidebar in sidebars:
            sidebar.setCurrentRow(1)
        measurements = []
        overflow = []
        for pixels in (12, 20, 28, 12):
            for sidebar in sidebars:
                font = QFont(sidebar.font())
                font.setFamily('Noto Sans CJK KR')
                font.setPixelSize(pixels)
                sidebar.setFont(font)
            for _ in range(10):
                app.processEvents()
            widths = [s.width() for s in sidebars]
            heights = [s.visualItemRect(s.item(0)).height() for s in sidebars]
            assert widths[0] == widths[1] >= 136
            assert heights[0] == heights[1]
            for sidebar in sidebars:
                assert sidebar.currentRow() == 1
                detail = (pixels, sidebar.width(), sidebar.viewport().width(),
                          sidebar.sizeHintForColumn(0), sidebar.horizontalScrollBar().maximum())
                print('SIDEBAR_WIDTH', detail)
                if sidebar.horizontalScrollBar().maximum():
                    sidebar.grab().save('/tmp/qa-sidebar-large-font-rounding.png')
                    overflow.append(detail)
            measurements.append((pixels, widths[0], heights[0]))
        assert measurements[0] == measurements[-1]
        print('SIDEBAR_FONT_ROUNDTRIP', measurements)
        assert not overflow, overflow
    finally:
        cost.shutdown()
        for widget in (cost, exchange):
            widget.close()
            widget.deleteLater()
        app.processEvents()


def test_exchange_opens_with_first_dungeon_only_when_first_shown(monkeypatch):
    # 명세 12절(2026-10-29): 던전 입장 계산기처럼 첫 던전이 선택된 채 열린다. 시세 조회는 탭이 처음 보일 때만
    # (앱 시작·탭 생성 때 미리 조회하지 않음), 사용자가 고른 던전은 그대로 둔다.
    calls = []
    monkeypatch.setattr(ExchangeTab, '_work', lambda self, region: calls.append(region))
    monkeypatch.setattr('mabinogi_addon.ui.exchange_tab.threading.Thread',
                        lambda target, args, daemon: type('T', (), {'start': lambda self: target(*args)})())
    tab = ExchangeTab()
    assert calls == [] and tab.region_list.currentItem() is None
    tab.show()
    first = tab.region_list.item(0).text()
    assert tab.region_list.currentItem().text() == first and calls == [first] and tab.title.text() == first
    tab.region_list.setCurrentRow(2)
    tab.hide()
    tab.show()
    assert tab.region_list.currentRow() == 2 and calls == [first, tab.region_list.item(2).text()]
    tab.close()
