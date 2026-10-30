"""확인 창 버튼 한글화(QA 0.29.0): 사용자에게 보이는 표준 버튼에 영어 글자가 남지 않는다."""
import re
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from mabinogi_addon.ui.dialogs import BUTTON_TEXT, install_korean_buttons

B = QMessageBox.StandardButton
ALL = [B.Ok, B.Save, B.SaveAll, B.Open, B.Yes, B.YesToAll, B.No, B.NoToAll, B.Abort, B.Retry, B.Ignore,
       B.Close, B.Cancel, B.Discard, B.Help, B.Apply, B.Reset, B.RestoreDefaults]


@pytest.fixture
def app():
    app = QApplication.instance() or QApplication([])
    install_korean_buttons(app)
    return app


def test_main_buttons_read_korean(app):
    box = QMessageBox()
    box.setStandardButtons(B.Yes | B.No | B.Ok | B.Cancel)
    assert [box.button(b).text() for b in (B.Yes, B.No, B.Ok, B.Cancel)] == ["예", "아니요", "확인", "취소"]
    box.deleteLater()


def test_no_standard_button_keeps_english_letters(app):
    box = QMessageBox()
    mask = B.NoButton
    for button in ALL:
        mask |= button
    box.setStandardButtons(mask)
    texts = {box.standardButton(b).name: b.text() for b in box.buttons()}
    assert len(texts) == len(BUTTON_TEXT)
    assert all(text and not re.search(r"[A-Za-z&]", text) for text in texts.values()), texts
    box.deleteLater()


def test_static_question_and_information_show_korean(app):
    seen = []

    def read_and_close():
        box = next(w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible())
        seen.append(sorted(b.text() for b in box.buttons()))
        box.button(box.standardButtons() & B.No and B.No or B.Ok).click()

    QTimer.singleShot(0, read_and_close)
    assert QMessageBox.question(None, "확인", "할까요?", B.Yes | B.No, B.No) == B.No
    QTimer.singleShot(0, read_and_close)
    QMessageBox.information(None, "알림", "끝났어요.")
    assert seen == [["아니요", "예"], ["확인"]]


def test_own_button_text_is_kept(app):
    box = QMessageBox()  # setup_flow처럼 직접 글자를 넣은 곳은 그대로
    box.setStandardButtons(B.Yes | B.No)
    box.button(B.Yes).setText("이 영역으로 등록")
    assert box.button(B.Yes).text() == "이 영역으로 등록" and box.button(B.No).text() == "아니요"
    box.deleteLater()


def test_app_entry_installs_korean_buttons():
    source = (Path(__file__).parents[1] / "src/mabinogi_addon/__init__.py").read_text(encoding="utf-8")
    assert "install_korean_buttons(app)" in source
