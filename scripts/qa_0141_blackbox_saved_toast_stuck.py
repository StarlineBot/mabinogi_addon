"""0.14.1 실사용: '영상 저장 완료' 게임 화면 알림이 사라지지 않고, 탭은 '저장 대기 1건'에 멈춤.

실행: QT_QPA_PLATFORM=offscreen uv run python -m scripts.qa_0141_blackbox_saved_toast_stuck
실제 BlackboxController._tick을 가짜 서비스·패널로 돌린다. 저장 완료(completed에 'saved')가 들어온 틱에서
단축키 반응 문구(_hotkey_note)가 이미 끝난 상태(None)면, _tick 안의 지역 `import time`(단축키 문구 분기) 때문에
`time`이 함수 지역 변수가 되어 완료 분기의 time.monotonic()이 UnboundLocalError를 낸다.
→ completed.clear()에 닿지 못해 매 틱(100ms) 완료 알림을 다시 띄워(3초 타이머 재시작) 사라지지 않고,
  탭 문구는 직전 '저장 대기 1건'에 멈춘다. 예외가 나면 REPRODUCED, 종료 코드 1.
"""
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from PySide6.QtWidgets import QApplication  # noqa: E402

from mabinogi_addon.blackbox_combat import CombatGate  # noqa: E402
from mabinogi_addon.ui import blackbox_controller as module  # noqa: E402


class Label:
    def __init__(self):
        self.value = ''

    def setText(self, text):
        self.value = text


def controller(note):
    c = module.BlackboxController.__new__(module.BlackboxController)
    toasts = []
    c._react = lambda text, kind, target=None: toasts.append(text)
    c._action = lambda op: op()
    c._update_badge = lambda d: None
    c._show_mode_notice = lambda: None
    c._combat_record = lambda active: active
    c._mode, c._gate = 'always', CombatGate()
    c._last_target, c._toasted_failures, c._recovery_dialog = None, set(), None
    c._hotkey_note = note
    c._save_started = time.monotonic() - 45  # 저장 중 진행 표시가 기록한 시작 시각
    c.events = NS(sample=lambda: (None, False), consume_hotkey=lambda: None)
    c.panel = NS(**{k: Label() for k in ('status', 'capture_info', 'available', 'folder', 'recent')},
                 show_error=lambda text: None)  # 0.16.0 패널: 최근 저장 줄(recent)과 오류 줄이 분리됨
    c.panel.recent.value = '최근 저장: 저장 대기 1건 · 앞 작업이 끝나면 시작해요'
    c._logged_error, c._capturing_hotkey = None, False
    result = NS(output=Path('C:/Videos/clip.mp4'), duration_us=109_000_000, cleanup_error=None, completed=True)
    c.service = NS(tick=lambda *a, **k: None, current=None, completed=[('saved', result)], status='recording',
                   enabled=True, error=None, producer=None, recoveries=lambda: [],
                   _retention=300_000_000, settings=NS(output_folder=Path('C:/Videos')), codec=None)
    return c, toasts


def run(label, note):
    c, toasts = controller(note)
    errors = []
    for _ in range(5):  # 100ms 틱 5번
        try:
            c._tick()
        except Exception as exc:  # Qt 타이머 슬롯에서는 예외가 출력만 되고 다음 틱이 계속 돈다
            errors.append(type(exc).__name__ + ': ' + str(exc))
    print(f'[{label}] 틱 5번 · 완료 알림 {len(toasts)}번 · 남은 completed {len(c.service.completed)}개 · '
          f'탭 문구 "{c.panel.recent.value}" · 예외 {errors[:1] or "없음"}')
    return errors


if __name__ == '__main__':
    app = QApplication.instance() or QApplication([])
    stuck = run('단축키 문구 끝난 뒤 완료(실사용)', None)
    fresh = run('단축키 문구 표시 중 완료', ('저장 요청 접수', time.monotonic() + 60))
    print('REPRODUCED: 저장 완료 틱에서 UnboundLocalError → 완료 알림 매 틱 재표시(안 사라짐)·탭 문구 멈춤'
          if stuck else 'not reproduced')
    sys.exit(1 if stuck else 0)
