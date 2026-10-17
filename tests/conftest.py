"""테스트 공통 설정 + 누수 QThread 사전 검출.

앱이 종료·재시작할 때 '실행 중인 QThread'가 남아 파괴되면 Qt가 프로세스를 abort(rc=134)시킨다.
테스트도 똑같이 — 워커를 정리하지 않고 끝내면 프로세스 teardown에서 같은 abort가 난다
(pytest는 'passed'를 찍은 뒤 rc=134로 죽어, CI·릴리즈 게이트에서야 드러난다).

그래서 **각 테스트가 끝날 때 실행 중인 QThread가 있으면 그 테스트를 실패**시켜, 워커 정리
누락을 그 자리에서 잡는다(앱의 실제 종료 크래시와 같은 뿌리). 테스트는 끝에 컨트롤러.stop()
/ stop_polling() / 창.close() 등으로 워커를 정리해야 한다.
"""

from __future__ import annotations

import gc
from pathlib import Path
import sys

import pytest


@pytest.fixture
def tuarim_width_diagnostics(monkeypatch):
    """Capture real geometry at the width assertion, without changing its result."""
    import json
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QFontInfo
    from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QComboBox
    from mabinogi_addon.ui.main_window import _VScroll

    original = _VScroll.horizontalScrollBar
    snapshot = {}

    def measured(scroll):
        bar = original(scroll)
        tab = scroll.widget()
        pages = getattr(tab.window(), "_combat_pages", {}) if tab is not None else {}
        if tab is not None and scroll in pages.values() and tab.isVisible():
            view = scroll.viewport()
            font = QFontInfo(tab.font())
            controls = {}
            names = {id(value): name for name,value in vars(tab).items()}
            widgets = [widget for widget in tab.findChildren(QAbstractButton)
                       + tab.findChildren(QAbstractSpinBox) + tab.findChildren(QComboBox) if widget.isVisible()]
            for index,widget in enumerate(widgets):
                name = names.get(id(widget), f"{type(widget).__name__}_{index}")
                point = widget.mapTo(view, QPoint())
                control_font = QFontInfo(widget.font())
                controls[name] = {"rect": [point.x(),point.y(),widget.width(),widget.height()],
                                  "minimum_hint": widget.minimumSizeHint().width(),
                                  "font": {"family":control_font.family(),"pixel_size":control_font.pixelSize()}}
            snapshot[type(tab).__name__] = dict(viewport=[view.width(),view.height()], content=[tab.width(),tab.height()],
                            minimum_hint=tab.minimumSizeHint().width(), horizontal_range=bar.maximum(),
                            font={"family":font.family(),"pixel_size":font.pixelSize()},
                            path=str(getattr(tab,"_shot_dir","")), controls=controls)
        return bar

    monkeypatch.setattr(_VScroll, "horizontalScrollBar", measured)
    yield snapshot
    if snapshot:
        print("NAVIGATION_WIDTH_DIAGNOSTICS " + json.dumps(snapshot, ensure_ascii=False))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _isolated_runtime(request, tmp_path):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from shiboken6 import isValid
    from unittest.mock import patch
    from mabinogi_addon import config, paths
    from test_support.boundaries import ExternalBoundaries

    app = QApplication.instance()
    before = set(app.topLevelWidgets()) if app is not None else set()
    native = request.node.get_closest_marker("windows_integration") is not None
    original_path = config.LOCAL_CONFIG_PATH
    read, write = config._read_local_config, config._write_local_config
    target = tmp_path / "app" / "config.local.json"
    user_dir = tmp_path / "app" / "data"
    user_dir.mkdir(parents=True)

    def redirect(path):
        return target if path == original_path else path

    with ExternalBoundaries(devices=not native) as boundary, \
            patch.object(config, "LOCAL_CONFIG_PATH", target), \
            patch.object(config, "ENV_PATH", tmp_path / ".env"), \
            patch.object(config, "_read_local_config", lambda path=original_path: read(redirect(path))), \
            patch.object(config, "_write_local_config", lambda data, path=original_path: write(data, redirect(path))), \
            patch.object(paths, "user_data_dir", lambda: user_dir):
        yield boundary
        app = QApplication.instance()
        if app is not None:
            # 누수 검사는 먼저 실행된다. 이후 소유한 창을 정리해 다음 테스트 오염을 막는다.
            for widget in set(app.topLevelWidgets()) - before:
                if not isValid(widget):
                    continue
                if hasattr(widget, "_force_quit"):
                    widget._force_quit = True
                if hasattr(widget, "shutdown"):
                    widget.shutdown()
                if hasattr(widget, "dismiss"):
                    widget.dismiss()
                else:
                    widget.close()
                for timer in widget.findChildren(QTimer):
                    timer.stop()
                widget.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
        assert not boundary.violations, f"unisolated external operations: {boundary.violations}"


def _running_qthreads() -> list[str]:
    try:
        from PySide6.QtCore import QThread
    except Exception:  # noqa: BLE001 — Qt 없으면 검사 불가(그냥 통과)
        return []
    gc.collect()
    names: list[str] = []
    for obj in gc.get_objects():
        if isinstance(obj, QThread):
            try:
                if obj.isRunning():
                    names.append(type(obj).__name__)
            except Exception:  # noqa: BLE001 — 이미 파괴된 래퍼 등은 건너뜀
                pass
    return names


@pytest.fixture(autouse=True)
def _no_leaked_qthreads(_isolated_runtime):
    """테스트 종료 시 실행 중인 QThread가 남아 있으면 실패(이름 표시)."""
    yield
    leaked = _running_qthreads()
    assert not leaked, (
        f"테스트가 실행 중인 QThread를 정리하지 않았습니다: {leaked} "
        "(끝에서 워커를 stop()/close() 하세요 — 안 하면 종료 시 abort rc=134)"
    )
