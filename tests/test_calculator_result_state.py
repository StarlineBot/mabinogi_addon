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
