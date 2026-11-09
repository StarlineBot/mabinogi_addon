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

from test_support.qt_runtime import configure_offscreen_fonts

# Must precede test-module imports and their first QApplication.
configure_offscreen_fonts()

pytest_plugins = ['test_support.inventory']


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
    from mabinogi_addon import autofind_regions
    autofind_regions.reset_for_tests()  # 모듈 전역(자동 찾기 켜짐·고정·사용 값)이 테스트 사이에 새지 않게
    # 0.45.0부터 앱은 자동 찾기를 늘 켠다. 저장 영역(v1) 동작을 보는 예전 창 테스트는 숨은 비상 값(autofind.disabled = 예전 동작)으로 돈다.
    # 기본 켜짐 경로를 창 단위로 보는 테스트는 @pytest.mark.autofind_default.
    autofind_default = request.node.get_closest_marker("autofind_default") is not None
    original_disabled = config.load_autofind_disabled
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
            patch.object(paths, "user_data_dir", lambda: user_dir), \
            patch.object(config, "load_autofind_disabled",
                         original_disabled if autofind_default else (lambda path=None: True)):
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
        autofind_regions.reset_for_tests()
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


@pytest.fixture(autouse=True)
def _access_recheck_immediate():
    """기존 기능 테스트는 권한 함수를 바꾼 즉시 반영되길 기대한다. 0.17.2 권한 캐시(1초 재사용)는
    tests/test_access_cache.py가 기본 간격으로 따로 확인한다. (monkeypatch를 쓰면 정리 순서가 바뀌어 직접 되돌린다.)"""
    from mabinogi_addon import feature_access
    saved, feature_access.Recheck.INTERVAL = feature_access.Recheck.INTERVAL, 0.0
    yield
    feature_access.Recheck.INTERVAL = saved


@pytest.fixture(autouse=True)
def _dorcha_inline_jobs():
    """0.38.0: 앱에서는 도르카 판독 틱·다시 읽기를 작업 스레드에서 돌린다. 기존 판정 테스트는 `_tick()` 직후
    결과를 확인하므로 같은 계산을 바로(동기로) 돌린다. 스레드 실행 자체는 tests/test_dorcha_thread.py가 확인한다."""
    from mabinogi_addon.system.window_capture import clear_target_cache
    from mabinogi_addon.ui.dorcha_tab import DorchaTab
    saved, DorchaTab.INLINE_JOBS = DorchaTab.INLINE_JOBS, True
    clear_target_cache()  # 게임 실행 파일·창 주인 캐시(몇 초)가 테스트 사이에 남지 않게
    yield
    DorchaTab.INLINE_JOBS = saved
    clear_target_cache()


@pytest.fixture(autouse=True)
def _no_startup_channel_measure():
    """0.42.0: 앱 창이 뜬 뒤 몇 초 있다 서버별 채널 상태를 실제 게임 서버로 잰다. 창을 띄우는 기존 테스트가 오래 걸려도
    외부 연결이 나가지 않게 시작 측정 대기를 아주 길게 둔다. 시작 측정 자체는 test_harp_channels가 직접 부른다."""
    from mabinogi_addon.ui import main_window
    saved, main_window.CHANNEL_STARTUP_DELAY_MS = main_window.CHANNEL_STARTUP_DELAY_MS, 24 * 3600 * 1000
    yield
    main_window.CHANNEL_STARTUP_DELAY_MS = saved


@pytest.fixture(autouse=True)
def _boss_inline_jobs():
    """꼬리 끊김 조사: 앱에서는 보스 틱 계산(캡처·이름·HP·보스바)을 작업 스레드에서 돌린다. 기존 판정 테스트는 `_tick()`
    직후 결과를 확인하므로 같은 계산을 바로(동기로) 돌린다. 스레드 실행 자체는 tests/test_boss_thread.py가 확인한다."""
    from mabinogi_addon.ui.boss_tab import BossTab
    saved, BossTab.INLINE_JOBS = BossTab.INLINE_JOBS, True
    yield
    BossTab.INLINE_JOBS = saved


@pytest.fixture(autouse=True)
def _skillbar_capture_inline():
    """쿨타임 명세 9.1: 앱에서는 단축바 공유 캡처가 작업 스레드에서 돈다. 기존 미러 테스트는 `_tick()` 직후 결과를
    보므로 같은 일을 바로(동기로) 한다. 스레드 실행 자체는 tests/test_cooldown_overlay.py가 확인한다."""
    from mabinogi_addon.ui.skillbar_capture import SkillbarCapture
    saved, SkillbarCapture.INLINE = SkillbarCapture.INLINE, True
    yield
    SkillbarCapture.INLINE = saved


def pytest_configure(config):
    config.addinivalue_line("markers", "autofind_default: 창 테스트를 앱 기본(자동 찾기 켜짐)으로 — 기본은 비상 값 꺼짐(저장 영역 v1 동작)")
