"""앱 화면에 '베타'·'알파'·'제작자 테스트' 표기 없음(ui-rules 7절 — 베타는 업데이트 노트에만, 사용자 결정 11-10).

비제작자 기준으로 메인 창의 모든 글자(구역 제목·라벨·버튼·탭 이름·툴팁)와 기능 도움말을 본다.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QAbstractButton, QApplication, QGroupBox, QLabel, QTabWidget

from mabinogi_addon import config, feature_access

WORDS = ("베타", "알파", "제작자 테스트")


@pytest.mark.autofind_default
def test_no_beta_words_on_any_screen(monkeypatch):
    from mabinogi_addon.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(feature_access, "is_creator", lambda: False)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "test", "name": "테스트"})
    w = MainWindow()
    try:
        for timer in w.findChildren(QTimer):
            timer.stop()
        texts = []
        for widget in w.findChildren(QLabel):
            texts.append(widget.text())
        for widget in w.findChildren(QAbstractButton):
            texts += [widget.text(), widget.toolTip()]
        for widget in w.findChildren(QGroupBox):
            texts.append(widget.title())
        for tabs in w.findChildren(QTabWidget):
            texts += [tabs.tabText(i) for i in range(tabs.count())]
        bad = [t for t in texts if t and any(word in t for word in WORDS)]
        assert bad == []
        assert w.boss_tab.bar_section.title() == "보스바 오버레이" and not w.boss_tab.bar_section.isHidden()
        assert w.debuff_tab.display_segments is not None and w.debuff_tab.effective_display_mode() == "missing"
    finally:
        w._force_quit = True
        w.close()
        app.processEvents()


def test_no_beta_words_in_help():
    from mabinogi_addon.ui import feature_copy
    texts = list(feature_copy.HELP.values()) + [str(v) for k, v in vars(feature_copy).items()
                                                 if k.isupper() and isinstance(v, (str, dict))]
    assert not [t for t in texts if any(word in t for word in WORDS)]
