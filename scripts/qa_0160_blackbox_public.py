"""0.16.0 블랙박스 탭 QA 재현: 오류 줄이 다음 틱에 지워지는지, 마우스 휠로 보관 시간이 줄어 영상이 잘리는지.

실행: QT_QPA_PLATFORM=offscreen uv run python -m scripts.qa_0160_blackbox_public
1) 오류 줄: 컨트롤러가 직접 띄운 오류(단축키 변경 실패·지난 실행 임시 자료 정리 실패 안내)가 녹화 오류가 없는
   다음 틱(0.1초)에 사라지는지. 실제 BlackboxController._tick + 실제 BlackboxTab.
2) 휠: 포커스 없는 보관 시간 칸 위에서 탭을 스크롤하듯 휠을 굴리면 값이 바뀌는지(valueChanged → 즉시 저장·적용),
   보관 시간을 줄이면 실제 ReplayBuffer에서 오래된 영상이 지워지는지.
재현되면 REPRODUCED, 종료 코드 1.
"""
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mabinogi_addon.blackbox import ReplayBuffer, Segment  # noqa: E402
from mabinogi_addon.blackbox_combat import CombatGate  # noqa: E402
from mabinogi_addon.ui import blackbox_controller as module  # noqa: E402
from mabinogi_addon.ui.blackbox_tab import BlackboxTab  # noqa: E402


def controller():
    c = module.BlackboxController.__new__(module.BlackboxController)
    c._react = lambda *a, **k: None
    c._action = lambda op: op()
    c._update_badge = lambda d: None
    c._show_mode_notice = lambda: None
    c._combat_record = lambda active: active
    c._allowed = lambda: True
    c._mode, c._gate = 'always', CombatGate()
    c._last_target, c._toasted_failures, c._recovery_dialog = None, set(), None
    c._capturing_hotkey, c._logged_error, c._save_started = False, None, None
    c.events = NS(sample=lambda: (None, False), consume_hotkey=lambda: None)
    c.panel = BlackboxTab()
    c.service = NS(tick=lambda *a, **k: None, current=None, completed=[], status='recording', enabled=True,
                   error=None, producer=None, recoveries=lambda: [], _retention=300_000_000,
                   settings=NS(output_folder=Path('C:/Videos')), codec=None)
    return c


def error_line():
    found = []
    for label, show in (('단축키 변경 실패', lambda c: c._show_error('단축키를 바꾸지 못했어요: 설정 파일 쓰기 실패')),
                        ('지난 실행 임시 자료 안내', lambda c: c.panel.show_error(
                            '지난 실행에서 남은 블랙박스 임시 자료 2건을 지우지 못했어요. 다음 실행 때 다시 정리해요.'))):
        c = controller()
        show(c)
        before = c.panel.error.text()
        c._tick()
        after = c.panel.error.text() if not c.panel.error.isHidden() else '(숨김)'
        print(f'[오류 줄 · {label}] 표시 직후 "{before[:30]}…" → 0.1초 틱 1번 뒤 "{after[:30]}"')
        if after == '(숨김)':
            found.append(label)
    return found


def wheel():
    tab = BlackboxTab()
    tab.retention.setEnabled(True)
    tab.resize(760, 900)
    tab.show()
    changes = []
    tab.retention.valueChanged.connect(changes.append)
    tab.setFocus()
    pos = QPointF(tab.retention.rect().center())
    for _ in range(4):  # 탭을 아래로 스크롤하는 휠 4칸이 마침 보관 시간 칸 위를 지나감
        event = QWheelEvent(pos, QPointF(tab.retention.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, -120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(tab.retention, event)
    print(f'[휠] 포커스 {tab.retention.hasFocus()} · 휠 4칸 → 보관 시간 5분 → {tab.retention.value()}분 · valueChanged {changes}')
    # 보관 시간 줄이기가 실제로 영상을 지우는지: 5분 분량(0.25초 조각 1200개)을 넣고 1분으로 줄인다.
    replay = ReplayBuffer('s', max_bytes=1 << 40, max_segments=4096, max_saves=2, retention_us=300_000_000)
    for i in range(1200):
        replay.append(Segment('s', f'c{i}', i * 250_000, (i + 1) * 250_000, 1, 'h264'))
    before = replay.available_us
    retired = replay.set_retention(60_000_000)
    print(f'[보관 줄임] 5분 → 1분: 확보 {before / 1e6:.0f}초 → {replay.available_us / 1e6:.0f}초 · 지운 조각 {len(retired)}개'
          ' (다시 5분으로 올려도 돌아오지 않음)')
    return bool(changes) and len(retired) > 0


if __name__ == '__main__':
    app = QApplication.instance() or QApplication([])
    lost = error_line()
    trimmed = wheel()
    if lost:
        print('REPRODUCED(오류 줄): ' + ', '.join(lost) + ' — 녹화 오류가 없으면 다음 틱에 오류 줄이 지워짐')
    if trimmed:
        print('REPRODUCED(휠): 포커스 없는 보관 시간 칸에서 휠로 값이 바뀌고, 줄이면 보관 영상이 즉시 지워짐')
    sys.exit(1 if lost or trimmed else 0)
