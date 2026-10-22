"""0.11.2 실사용 제보: 블랙박스 '저장 내역·복구' 창의 '선택한 실패 자료 폐기'가 반응하지 않음.

실행: QT_QPA_PLATFORM=offscreen uv run python -m scripts.qa_blackbox_recovery_click
예상(미수정): 'REPRODUCED' 출력, 종료 코드 1. 수정 후 'not reproduced', 종료 코드 0.
원인: 컨트롤러 100ms 타이머가 창이 보이는 동안 매번 refresh()를 호출하고, refresh()가 목록을 비웠다
다시 채우며 폐기 버튼을 잠깐 비활성화한다. 누르고 떼는 사이에 refresh가 끼면 Qt가 클릭을 취소한다.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


class _Spool:
    sources = ('0236988e' + 'f' * 24,)  # 사용자 화면의 '미완성 캡처 자료' 1건


class _Service:
    runtimes = {'28508:134371585343895824': object()}
    spool = _Spool()
    _closing = False

    def _allowed(self):
        return True

    def recoveries(self):
        return []

    def orphan_sources(self):
        return self.spool.sources


def main():
    app = QApplication.instance() or QApplication([])
    from mabinogi_addon.ui.blackbox_recovery import BlackboxRecovery
    dialog = BlackboxRecovery(_Service())
    dialog.show()
    clicked = []
    dialog.discard.clicked.disconnect()
    dialog.discard.clicked.connect(lambda: clicked.append(True))
    center = dialog.discard.rect().center()
    QTest.mousePress(dialog.discard, Qt.MouseButton.LeftButton, pos=center)
    dialog.refresh()  # 컨트롤러 100ms 타이머의 갱신 1회
    QTest.mouseRelease(dialog.discard, Qt.MouseButton.LeftButton, pos=center)
    dialog.close()
    app.processEvents()
    reproduced = not clicked
    print('[복구 창]', 'REPRODUCED: 누르는 중 1회 갱신으로 폐기 클릭이 사라짐' if reproduced else 'not reproduced')
    return reproduced


if __name__ == '__main__':
    sys.exit(1 if main() else 0)
