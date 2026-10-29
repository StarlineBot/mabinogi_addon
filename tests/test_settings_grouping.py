from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint,Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGroupBox,QPushButton,QMessageBox

from test_navigation import window
from mabinogi_addon import config
from mabinogi_addon.ui import region_registration as reg


def test_groups_and_lock_controls_follow_approved_layout(window):
    w,app = window
    # 0.27.0(안내·도움말 명세 11.2): 보스 '화면 표시' 하나로, 도르카·투아림 '화면 표시'·'투아림 알림', 영역은 '영역 지정' 상자
    for tab,titles in ((w.boss_tab,{"영역 지정","판독 미리보기","화면 표시"}),
                       (w.stat_bars_tab,{"영역 지정","판독 미리보기","표시","낮은 수치 알림 · 보스전"}),
                       (w.resource_tab,{"영역 지정","화면 표시","투아림 알림"}),
                       (w.custom_overlay_tab,{"오버레이","프리셋"}),
                       (w.skillbar_tab,{"표시"}),(w.memo_tab,{"표시","메모 내용"})):
        assert titles <= {box.title() for box in tab.findChildren(QGroupBox)}
    for button in (w.boss_tab.warn_lock_btn,w.boss_tab.upcoming_lock_btn,w.dorcha_tab.lock_chk,w.memo_tab.lock_btn):
        assert isinstance(button,QPushButton) and button.isCheckable()
    assert not hasattr(w.memo_tab,"enable_chk")


@pytest.mark.parametrize("key",["boss","stat_bars","dorcha","skillbar","memo"])
def test_registration_status_always_precedes_commands(window,key):
    w,app = window
    w._open_setup_feature(key)
    app.processEvents()
    tab = w.resource_tab if key=="dorcha" else getattr(w,{"stat_bars":"stat_bars_tab"}.get(key,key+"_tab"))
    # 0.27.0(명세 11절): 지정 전 정보 줄은 '영역 지정' 상자의 '● 아직 지정 안 됨' 줄
    status = (tab.anchor_label if key=="skillbar" else tab.region_hint if key=="memo"
              else tab.region_section.unset_label)
    button = tab.region_btn if key!="skillbar" else tab.anchor_btn
    assert status.mapTo(tab,QPoint()).y()+status.height() <= button.mapTo(tab,QPoint()).y()


def test_memo_legacy_off_is_not_a_hidden_gate_and_clear_keeps_content(window,monkeypatch):
    w,app = window
    monkeypatch.setattr(w._watcher,"is_game_active",lambda:True)
    config.save_memo("## 남길 내용",True,18,False)
    w.memo_overlay.set_markdown("## 남길 내용")
    config.save_capture_region(100,120,300,90,"memoTracker")
    w._restore_memo()
    w._memo_timer.stop()
    assert w.memo_overlay.isVisible() and w.memo_overlay.locked
    before = deepcopy(config._read_local_config())
    monkeypatch.setattr(reg,"confirm_clear",lambda *args:QMessageBox.StandardButton.Yes)
    w.memo_tab.clear_region_btn.click()
    assert config.load_capture_region("memoTracker") is None
    assert not w.memo_overlay.isVisible()
    assert config._read_local_config()["memo"] == before["memo"]
    w._on_memo_moved()
    w._restore_memo()
    w._memo_timer.stop()
    assert config.load_capture_region("memoTracker") is None
    assert not w.memo_overlay.isVisible()
    assert w.memo_overlay.locked


def test_memo_registration_does_not_resume_global_pause(window,monkeypatch):
    w,app = window
    monkeypatch.setattr(w._watcher,"is_game_active",lambda:True)
    w._paused = True
    config.save_capture_region(10,20,200,80,"memoTracker")
    w._apply_memo_region()
    assert not w.memo_overlay.isVisible()
    w._paused = False
    w._tick_memo_visibility()
    assert w.memo_overlay.isVisible()


@pytest.mark.parametrize("large",[False,True])
def test_actual_grouped_pages_render_without_horizontal_overflow(window,tmp_path,large):
    from PySide6.QtWidgets import QWidget
    from mabinogi_addon.ui.theme import apply_theme
    w,app = window
    apply_theme("dark")
    w.resource_tab.percent_chk.setChecked(True)
    w.dorcha_tab.enable.setChecked(True)
    w.dorcha_tab.preview.set_elements(True,True)
    w.dorcha_tab.preview.set_value(7)
    w.dorcha_tab.preview.set_percent(19)
    w.stat_bars_tab.preview.setPixmap(QPixmap("tests/data/stat_bar_shots/hp070_mp100_sta100_004.png"))
    w.memo_tab.editor.setPlainText("## 던전 패턴\n\n- 포션 확인\n- 재료 체크리스트")
    w.memo_tab.preview_btn.setChecked(True)
    if large:
        for widget in w.findChildren(QWidget):
            font = widget.font()
            font.setPixelSize(20)
            widget.setFont(font)
    before = deepcopy(config._read_local_config())
    for key in ("boss","stat_bars","dorcha","custom","skillbar","memo"):
        w._open_setup_feature(key)
        for _ in range(4): app.processEvents()
        scroll = w._combat_pages[key]
        assert scroll.horizontalScrollBar().maximum() == 0,key
        assert w.grab().save(str(tmp_path/(key+("-large" if large else "")+".png")))
    assert config._read_local_config() == before
