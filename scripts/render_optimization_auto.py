"""최적화 명세 13.10 자동 적용 렌더: 최적화 탭(자동 적용 켬·게임 대기)과 상단 배지(게임 대기·적용 중·보류). 값은 모두 샘플.

QT_QPA_PLATFORM=offscreen uv run python -m scripts.render_optimization_auto /tmp/opt-auto
"""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import os
import sys
import tempfile
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QRect, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from mabinogi_addon import config, paths
from mabinogi_addon.ui import optimization_controller as module
from mabinogi_addon.ui.main_window import MainWindow
from mabinogi_addon.ui.theme import apply_theme
from test_support.boundaries import ExternalBoundaries
from test_support.qt_runtime import configure_offscreen_fonts


def main(out):
    out.mkdir(parents=True, exist_ok=True)
    configure_offscreen_fonts()
    app = QApplication.instance() or QApplication([]); apply_theme('light')
    raw = {'general': {'skipSetup': True}, 'buffTracker': {'enabled': False}, 'debuffTracker': {'enabled': False}}
    with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
        data = Path(folder) / 'data'; data.mkdir()
        boundary = stack.enter_context(ExternalBoundaries())
        stack.enter_context(patch.object(paths, 'user_data_dir', lambda: data))
        stack.enter_context(patch.object(config, '_read_local_config', lambda *a, **k: deepcopy(raw)))
        stack.enter_context(patch.object(config, '_write_local_config', lambda *a, **k: None))
        stack.enter_context(patch.object(config, 'load_discord_user', lambda *a, **k: {'id': 'preview', 'name': '미리보기'}))
        stack.enter_context(patch.object(config, 'get_nexon_api_key', lambda: None))
        stack.enter_context(patch.object(module, 'is_creator', lambda: True))
        stack.enter_context(patch.object(QApplication, 'quit', lambda: None))
        stack.enter_context(patch.object(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.No))
        screen = type(app.primaryScreen())
        for name in ('availableGeometry', 'geometry'):
            stack.enter_context(patch.object(screen, name, lambda self: QRect(0, 0, 1600, 1200)))
        w = MainWindow(); w._post_show_done = True; w._booting = False; w._leave_setup(); w.resize(1000, 1080); w.show()
        for timer in w.findChildren(QTimer): timer.stop()
        c = w.optimization_tools; d = c.panel; c.open()
        d.cpu_info.setText('AMD Ryzen 7 9800X3D · 물리 코어 8개 / 논리 프로세서 16개 (미리보기)')
        d.split.clear(); d.split.addItem('게임 7개 + 백그라운드 물리 코어 1개', 7)
        d.adapter.clear(); d.adapter.addItem('이더넷 (미리보기)', '12345678-1234-1234-1234-123456789abc')
        c._restoring_selection = True; d.auto.setChecked(True); c._restoring_selection = False  # 샘플 상태(세션 시작 안 함)
        d.toggle.setChecked(True); d.toggle.setText('최적화 적용 중')
        d.status.setText('게임 실행 대기 · 자동 적용 켜짐(게임을 켜면 적용하고, 끄면 그 게임에 건 값을 되돌려요).')

        def grab(widget, name):
            for _ in range(6): app.processEvents()
            assert widget.grab().save(str(out / name))
        try:
            grab(w, 'optimization-auto-tab.png')
            bar = w._combat_status.parentWidget()
            for name, state in (('badge-waiting.png', ('최적화: 게임 대기', 'neutral')),
                                ('badge-applied.png', ('최적화: 적용 중 7+1', 'neutral')),
                                ('badge-held.png', ('최적화: 보류', 'neutral'))):
                with patch.object(module, 'optimization_badge', lambda *a, _s=state, **k: _s):
                    c._update_badge()
                grab(bar, name)
            assert not boundary.violations, boundary.violations
        finally:
            w._force_quit = True; w.close(); app.processEvents()
    print(out)


if __name__ == '__main__':
    main(Path(sys.argv[1] if len(sys.argv) > 1 else 'optimization-auto'))
