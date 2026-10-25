"""최적화 명세 13.11 CPU 배치 렌더: 9800X3D 닫힌 콤보·회색 두 줄 설명·펼친 목록, 하이브리드·6코어 목록. 값은 샘플.

QT_QPA_PLATFORM=offscreen uv run python -m scripts.render_cpu_layouts /tmp/cpu-layouts
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
from mabinogi_addon.optimization.session import Core, Topology
from mabinogi_addon.ui import optimization_controller as module
from mabinogi_addon.ui.main_window import MainWindow
from mabinogi_addon.ui.theme import apply_theme
from test_support.boundaries import ExternalBoundaries
from test_support.qt_runtime import configure_offscreen_fonts

MB = 1024 * 1024


def smt(n, start=0, performance=True):
    return tuple(Core(start + i, (2 * (start + i), 2 * (start + i) + 1), performance) for i in range(n))


CPUS = {
    '9800x3d': Topology('AMD Ryzen 7 9800X3D', smt(8), ((96 * MB, tuple(range(16))),)),
    'hybrid': Topology('Intel Core i9-13900K', smt(8) + tuple(Core(8 + i, (16 + i,), False) for i in range(16))),
    '7950x3d': Topology('AMD Ryzen 9 7950X3D', smt(16), ((96 * MB, tuple(range(16))), (32 * MB, tuple(range(16, 32))))),
    '6core': Topology('AMD Ryzen 5 7600', smt(6)),
}


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
        w = MainWindow(); w._post_show_done = True; w._booting = False; w._leave_setup(); w.resize(1000, 1100); w.show()
        for timer in w.findChildren(QTimer): timer.stop()
        c = w.optimization_tools; d = c.panel; c.open()

        def pump():
            for _ in range(6): app.processEvents()
        try:
            for name, topology in CPUS.items():
                c._apply_inspection(topology, [])
                pump()
                group = d.split.parentWidget()
                assert group.grab().save(str(out / f'cpu-group-{name}.png'))
                d.split.showPopup(); pump()
                view = d.split.view()
                assert view.window().grab().save(str(out / f'cpu-popup-{name}.png'))
                d.split.hidePopup(); pump()
            assert not boundary.violations, boundary.violations
        finally:
            w._force_quit = True; w.close(); app.processEvents()
    print(out)


if __name__ == '__main__':
    main(Path(sys.argv[1] if len(sys.argv) > 1 else 'cpu-layouts'))
