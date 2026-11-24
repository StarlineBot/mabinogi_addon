"""캐릭터 알파 렌더(사용자 확인용) — 메인 창 탭 7개·캐릭터 탭·펫 동작 GIF. 모든 값은 샘플.

실행: QT_QPA_PLATFORM=offscreen uv run python -m scripts.render_character_alpha
"""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import os
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

OUT = Path('docs/assets/character-alpha-20261124')
DARK = {"background": "#1b1e24", "accent": "#00C9A2", "content": "auto"}


def main():
    import sys
    # 사용: … render_character_alpha [목소리 팩] — 아리아 고른 화면은 '부드러운 여성'(파일 main_character_tab_aria.png)
    pack = sys.argv[1] if len(sys.argv) > 1 else '조용한 여성'
    suffix = '' if pack == '조용한 여성' else '_aria'
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([]); app.setStyle('Fusion'); apply_theme('custom', DARK)
    raw = {'general': {'skipSetup': True, 'theme': 'dark'}, 'buffTracker': {'enabled': False},
           'debuffTracker': {'enabled': False}, 'voice': {'pack': pack},
           'character': {'pet': True, 'affinity': {'조용한 여성': {'value': 34, 'cleared': 1, 'totals': {'pets': 4, 'corner_minutes': 35}},
                                                     '부드러운 여성': {'value': 12, 'totals': {'alerts': 3}}}}}
    with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
        data = Path(folder) / 'data'; data.mkdir()
        boundary = stack.enter_context(ExternalBoundaries())
        stack.enter_context(patch.object(paths, 'user_data_dir', lambda: data))
        stack.enter_context(patch.object(config, '_read_local_config', lambda *a, **k: deepcopy(raw)))
        stack.enter_context(patch.object(config, '_write_local_config', lambda *a, **k: None))
        stack.enter_context(patch.object(config, 'load_discord_user', lambda *a, **k: {'id': 'preview', 'name': '미리보기'}))
        stack.enter_context(patch.object(config, 'get_nexon_api_key', lambda: None))
        stack.enter_context(patch.object(module, 'is_creator', lambda: True))
        from mabinogi_addon import feature_access
        stack.enter_context(patch.object(feature_access, 'is_creator', lambda: True))  # 캐릭터 알파는 제작자 전용
        stack.enter_context(patch.object(QApplication, 'quit', lambda: None))
        stack.enter_context(patch.object(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.No))
        screen = type(app.primaryScreen())
        for name in ('availableGeometry', 'geometry'):
            stack.enter_context(patch.object(screen, name, lambda self: QRect(0, 0, 1600, 1200)))
        w = MainWindow(); w._post_show_done = True; w._booting = False; w._leave_setup(); w.resize(790, 900); w.show()
        for timer in w.findChildren(QTimer):
            timer.stop()
        w.optimization_tools.refresh_access(); w.blackbox_tools.refresh_access()
        try:
            w._tabs.setCurrentWidget(w._character_scroll)
            for _ in range(6):
                app.processEvents()
            assert w.grab().save(str(OUT / f'main_character_tab{suffix}.png'))
            if suffix:
                return
            w._tabs.setCurrentWidget(w._settings_scroll)
            app.processEvents()
            w._settings_scroll.ensureWidgetVisible(w.settings_tab._alert_volume, 0, 260)
            for _ in range(6):
                app.processEvents()
            assert w.grab().save(str(OUT / 'settings_volume_only.png'))
            print([w._tabs.tabText(i) for i in range(w._tabs.count())])
            assert not boundary.violations, boundary.violations
        finally:
            w._force_quit = True; w.close(); app.processEvents()
    print(OUT)


if __name__ == '__main__':
    main()
