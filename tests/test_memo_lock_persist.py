"""회귀: 메모 잠금이 재시작 후에도 유지된다.

부팅(생성~복원) 중 파생 신호가 _save_memo를 불러 '기본 해제 상태'로 저장된 잠금을
덮어쓰면, 복원이 false를 읽어 항상 해제로 시작하던 버그. 부팅 가드로 차단한다.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from mabinogi_addon import config


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _tmp_config(monkeypatch) -> Path:
    tmp = Path(tempfile.mkdtemp()) / "c.json"
    tmp.write_text(
        json.dumps(
            {
                "memo": {"text": "메모", "locked": True, "fontSize": 18},
                "memoTracker": {
                    "captureRegion": {"x": 1032, "y": 72, "w": 300, "h": 249}
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        config, "_read_local_config",
        lambda path=None: json.loads(tmp.read_text(encoding="utf-8")),
    )
    monkeypatch.setattr(
        config, "_write_local_config",
        lambda data, path=None: tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8"),
    )
    return tmp


def test_memo_lock_survives_boot_clobber(monkeypatch) -> None:
    _app()
    tmp = _tmp_config(monkeypatch)
    from mabinogi_addon.ui.main_window import MainWindow

    w = MainWindow()
    # 부팅 중 파생 저장(기본 해제 오버레이)이 잠금을 덮어쓰면 안 된다.
    w._save_memo()
    assert json.loads(tmp.read_text(encoding="utf-8"))["memo"]["locked"] is True

    w.start()
    assert w.memo_overlay.locked is True  # 복원이 잠금을 적용
    assert json.loads(tmp.read_text(encoding="utf-8"))["memo"]["locked"] is True

    # 부팅 후엔 사용자 변경이 정상 저장된다.
    w.memo_tab.lock_btn.click()  # 해제
    assert json.loads(tmp.read_text(encoding="utf-8"))["memo"]["locked"] is False

    # start()가 띄운 워커(파티 폴링)를 정리한다 — 안 하면 프로세스 종료 시 '실행 중 QThread
    # 파괴'로 abort(rc=134). _force_quit로 트레이 최소화 조기 반환을 건너뛰고 완전 종료 경로로.
    w._force_quit = True
    w.close()
