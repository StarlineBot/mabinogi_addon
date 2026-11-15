"""단축바 묶음 목록(0.49.0, 사용자 결정 11-14) — 탭에서 12묶음 표시·잠금·칸 숨기기/되살리기, 오버레이 우클릭과 같은 값."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config
from mabinogi_addon.ui.skillbar_mirror import group_defs, group_name


class W:
    def is_game_active(self):
        return True

    def is_self_active(self):
        return False


@pytest.fixture
def tab():
    QApplication.instance() or QApplication([])
    config.save_skillbar({"anchor": {"x": 100, "y": 50}})
    from mabinogi_addon.ui.skillbar_tab import SkillbarTab
    t = SkillbarTab(W())
    t._ensure_overlays()
    yield t
    t.shutdown()


def test_group_names_match_game_numbers():
    names = [group_name(g) for g in group_defs()]
    assert len(names) == 12 and len(set(names)) == 12
    assert names[0] == "왼쪽 윗줄 1~4" and names[2] == "왼쪽 윗줄 9~12" and names[-1] == "오른쪽 아랫줄 9~12"


def test_hide_cell_in_list_hides_on_overlay_and_saves(tab):
    key = "b0r0c2"
    name, show, lock, buttons = tab.groups.rows[key]
    buttons[2].click()
    assert config.load_skillbar()["chunks"][key]["cells"] == [True, True, False, True]
    assert tab._overlays[key].hidden == [False, False, True, False]  # 오버레이 그 칸 안 그림
    assert buttons[2].hidden_cell
    buttons[2].click()  # 되살리기
    assert config.load_skillbar()["chunks"][key]["cells"] == [True] * 4 and not tab._overlays[key].hidden[2]


def test_overlay_right_click_updates_list(tab):
    key = "b1r1c0"
    tab._overlays[key].cell_toggled.emit(1)  # 오버레이 우클릭
    assert tab.groups.rows[key][3][1].hidden_cell
    assert config.load_skillbar()["chunks"][key]["cells"][1] is False


def test_show_off_hides_that_overlay_and_lock_toggle(tab):
    key = "b1r0c1"
    _name, show, lock, _ = tab.groups.rows[key]
    tab._apply_visibility()
    assert tab._overlays[key].isVisible()
    show.setChecked(False)
    assert not tab._overlays[key].isVisible() and config.load_skillbar()["chunks"][key]["show"] is False
    assert all(ov.isVisible() for k, ov in tab._overlays.items() if k != key)
    lock.setChecked(True)
    assert tab._overlays[key].locked and config.load_skillbar()["chunks"][key]["locked"] is True
    tab._set_locked_all(False)
    assert not lock.isChecked()  # 전체 잠금 해제도 목록에 반영


def test_hidden_cell_is_drawn_dim_when_unlocked_and_transparent_when_locked(tab):
    ov = tab._overlays["b0r0c0"]
    pm = QPixmap(40, 40)
    pm.fill(QColor(255, 0, 0))
    ov.set_cells([pm] * 4)
    ov.set_hidden([True, False, True, True])  # 2번째 칸 숨김
    ov.set_locked(False)
    img = ov.grab().toImage()
    x = round(44 * ov._scale) + 10
    assert img.pixelColor(x, 10).alpha() > 0  # 흐린 자리 — 우클릭이 먹힘
    ov.set_locked(True)
    img = ov.grab().toImage()
    assert img.pixelColor(x, 10).alpha() == 0  # 잠금: 지금처럼 투명
