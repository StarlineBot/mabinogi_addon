"""등록한 게임의 프로세스 식별값(PID, 시작 시각). 추적기 초기화(tracker/game_session.py)에 쓴다. Windows 전용."""
from __future__ import annotations

import sys


class GameProcessProbe:
    def __init__(self) -> None:
        from .optimization import WindowsOptimization
        self._backend = WindowsOptimization()
        self._last = None

    def identity(self):
        """지금 게임 프로세스 (pid, 시작 시각) 또는 None. 창이 잠깐 안 잡혀도(최소화·창 재생성) 같은 프로세스가
        살아 있으면 그 프로세스를 돌려준다. Windows가 아니면 항상 None(초기화하지 않음)."""
        if sys.platform != 'win32':
            return None
        try:
            game = self._backend.game()
        except PermissionError:
            game = None  # 열 수 없는 프로세스: 창으로 찾은 PID만으로는 판단하지 않고 아래 생존 확인
        except Exception:
            game = None
        if game is not None:
            self._last = (game['pid'], game['birth'])
            return self._last
        if self._last is not None:
            try:
                if self._backend.alive({'pid': self._last[0], 'birth': self._last[1]}):
                    return self._last
            except Exception:
                return self._last  # 확인 실패는 종료의 증거가 아니다
            self._last = None
        return None
