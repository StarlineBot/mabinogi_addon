"""최적화 명세 13.12~13.14 렌더: 추천 최적화 구역·결과 요약·자세히 보기·상세 설정(연결 자동 선택). 값은 모두 샘플.

QT_QPA_PLATFORM=offscreen uv run python -m scripts.render_optimization_recommend /tmp/opt-recommend
"""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import os
import sys
import tempfile
from types import SimpleNamespace as NS
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QRect, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from mabinogi_addon import config, paths
from mabinogi_addon.optimization.session import Core, Topology
from mabinogi_addon.ui import optimization_controller as module
from mabinogi_addon.ui.main_window import MainWindow
from mabinogi_addon.ui.theme import apply_theme
from test_support.boundaries import ExternalBoundaries
from test_support.qt_runtime import configure_offscreen_fonts

X9800 = Topology('AMD Ryzen 7 9800X3D', tuple(Core(i, (2 * i, 2 * i + 1)) for i in range(8)))
WIRED = dict(Name='이더넷', InterfaceGuid='{11111111-1111-1111-1111-111111111111}', ifIndex=5, Default=True)
WIFI = dict(Name='Wi-Fi', InterfaceGuid='{22222222-2222-2222-2222-222222222222}', ifIndex=9, Default=False)


def main(out):
    out.mkdir(parents=True, exist_ok=True)
    configure_offscreen_fonts()
    app = QApplication.instance() or QApplication([]); apply_theme('light')
    raw = {'general': {'skipSetup': True}, 'buffTracker': {'enabled': False}, 'debuffTracker': {'enabled': False}}
    store = {}
    with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
        data = Path(folder) / 'data'; data.mkdir()
        boundary = stack.enter_context(ExternalBoundaries())
        stack.enter_context(patch.object(paths, 'user_data_dir', lambda: data))
        stack.enter_context(patch.object(config, '_read_local_config', lambda *a, **k: deepcopy({**raw, **store})))
        stack.enter_context(patch.object(config, '_write_local_config', lambda d, *a, **k: store.update(d)))
        stack.enter_context(patch.object(config, 'load_discord_user', lambda *a, **k: {'id': 'preview', 'name': '미리보기'}))
        stack.enter_context(patch.object(config, 'get_nexon_api_key', lambda: None))
        stack.enter_context(patch.object(module, 'is_creator', lambda: True))
        stack.enter_context(patch.object(QApplication, 'quit', lambda: None))
        stack.enter_context(patch.object(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.No))
        screen = type(app.primaryScreen())
        for name in ('availableGeometry', 'geometry'):
            stack.enter_context(patch.object(screen, name, lambda self: QRect(0, 0, 1600, 1400)))
        w = MainWindow(); w._post_show_done = True; w._booting = False; w._leave_setup(); w.resize(1000, 1250); w.show()
        for timer in w.findChildren(QTimer): timer.stop()
        c = w.optimization_tools; d = c.panel; c.open()
        c._apply_inspection(X9800, [WIRED, WIFI])
        e = c.engine

        def shot(name):
            c._tick()
            for _ in range(6): app.processEvents()
            assert w.grab().save(str(out / name))
        try:
            shot('opt-1-recommended.png')
            # 적용 중(샘플): 세션 진행 중인 것처럼 상태만 바꾼다(실제 적용 없음)
            e.thread = NS(is_alive=lambda: True); e.task = 'session'; e.phase = 'applied'
            e.outcome = dict(priority=('ok', ''), cpu=('ok', ''), tcp=('same', ''))
            c._summary_requested = dict(priority=True, cpu=True, tcp=True, auto=False, layout='focus')
            e.status = ('게임 우선순위: 높음 적용 · 확인 완료\ncpu 배치: 게임 0xFFF · 그 외 0xF000\n'
                        '다른 도구가 CPU 배치를 바꿨어요 · CP3.exe (PID 10596): 적용=0xF000, 현재=0xFFFF.')
            d.details_toggle.setChecked(True)
            shot('opt-2-applied-details.png')
            d.details_toggle.setChecked(False)
            e.phase = 'ended'; e.outcome = dict(priority=('restored', ''), cpu=('restored', ''))
            c._summary_requested['auto'] = True
            shot('opt-3-game-ended.png')
            e.thread = None; e.phase = None; e.outcome = {}; e.status = '시작 전 · 시스템 설정을 변경하지 않았어요.'; e.ran = False
            c._summary_requested = {}; c._kept_on = False
            d.advanced_toggle.setChecked(True)
            d.split.setCurrentIndex(d.split.findData('max_focus'))
            shot('opt-4-custom-advanced.png')
            assert not boundary.violations, boundary.violations
        finally:
            e.thread = None
            w._force_quit = True; w.close(); app.processEvents()
    print(out)


if __name__ == '__main__':
    main(Path(sys.argv[1] if len(sys.argv) > 1 else 'opt-recommend'))
