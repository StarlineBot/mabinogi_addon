"""0.32.0 QA: 추적을 끈(예전 '오버레이에 표시' 끔, config hidden) 버프가 다시 실행하면 목록에서 사라지던 문제.

BuffTab._load_state가 hidden 버프를 목록 순서에서 빼, 재시작(업데이트) 뒤 목록 = 기준 버프 1줄이 되고 다시 켤 방법이 없었다
(제보 설정: 기준 버프 외 31개 모두 hidden). 사용자 결정: 끔 = 추적 안 함(탐지·알림 없음), 목록에는 남기고 흐리게 + '추적 안 함'.
"""
import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config
from mabinogi_addon.catalog import available_catalog
from mabinogi_addon.ui.buff_tab import ANCHOR_ID, BuffTab
from mabinogi_addon.ui.palette import color
from test_navigation import window  # noqa: F401  (픽스처)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _ids(widget):
    return [widget.item(row).data(Qt.ItemDataRole.UserRole) for row in range(widget.count())]


def _hide(ids):
    """저장 순서는 카탈로그 순서를 뒤집은 것으로, ids는 hidden:true."""
    first = BuffTab()
    order = list(reversed(first._order))
    for bid in ids:
        first._settings[bid].hidden = True
    first._order = order
    first._save()
    first.deleteLater()
    return order


def test_hidden_buffs_stay_in_list_dimmed_and_unchecked(app):
    probe = BuffTab()
    every = list(probe._order)
    probe.deleteLater()
    hidden = every[::2]
    order = _hide(hidden)
    tab = BuffTab()  # 다시 실행
    assert _ids(tab.buff_list) == [ANCHOR_ID, *order]  # 저장 순서 그대로, 끈 버프도 목록에(기준 맨 위)
    muted = color("muted").lower()
    for row, bid in enumerate(_ids(tab.buff_list)):
        item = tab.buff_list.item(row)
        off = bid in hidden
        assert (item.foreground().color().name().lower() == muted) == off, bid  # 끈 버프만 흐리게
        assert item.text().endswith("· 추적 안 함") == off, bid
        tab.buff_list.setCurrentRow(row)
        if bid != ANCHOR_ID:
            assert tab.display_check.isChecked() == (not off)
            assert tab.show_duration.isEnabled() == (not off) and tab._alert_box.isEnabled() == (not off)  # 끈 동안 아래 설정 흐리게
    tab.deleteLater()


def test_all_hidden_like_report_keeps_full_list(app):
    probe = BuffTab()
    every = list(probe._order)
    probe.deleteLater()
    _hide(every)  # 제보: 기준 버프 외 모두 hidden
    tab = BuffTab()
    assert len(_ids(tab.buff_list)) == 1 + len(every)  # 예전: 기준 버프 1줄
    # 다시 켜면 흐림이 풀리고 저장된다
    tab.buff_list.setCurrentRow(1)
    tab.display_check.setChecked(True)
    item = tab.buff_list.item(1)
    assert item.foreground().color().name().lower() != color("muted").lower()
    assert not next(s for s in config.load_buff_settings() if s.id == _ids(tab.buff_list)[1]).hidden
    tab.deleteLater()


def test_hidden_excluded_from_tracking_and_kept_through_reorder(window):
    w, app = window
    every = list(w.buff_tab._order)
    hidden = every[1::3]
    order = _hide(hidden)
    tracked = w._compute_tracking(available_catalog())[0]
    assert all(b not in tracked for b in hidden) and tracked == [b for b in order if b not in hidden]
    tab = BuffTab()
    # ▲▼: 끈 버프를 위로 한 칸
    target = hidden[0]
    tab.buff_list.setCurrentRow(_ids(tab.buff_list).index(target))
    tab._move(-1)
    # 끌기: 둘째 줄을 넷째 자리로
    assert tab.buff_list.model().moveRow(QModelIndex(), 1, QModelIndex(), 4)
    app.processEvents()
    saved = config.load_buff_settings()
    assert [s.id for s in saved if s.id != ANCHOR_ID] == tab._order  # 끈 버프 포함 순서 그대로 저장
    assert {s.id for s in saved if s.hidden} == set(hidden)  # 끔 설정 보존
    again = BuffTab()
    assert again._order == tab._order
    assert w._compute_tracking(available_catalog())[0] == [b for b in tab._order if b not in hidden]
    tab.deleteLater()
    again.deleteLater()
