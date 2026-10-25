"""0.17.2 상단 상태 줄: 최적화 배지를 블랙박스·전투 보조와 같은 모양으로(사용자 결정). 최적화 4상태 렌더.

QT_QPA_PLATFORM=offscreen uv run python -m scripts.render_status_badges_0172 /tmp/status-0172
상태 표시만 바꾼다(최적화 작업·녹화 연결 없음). 제작자 계정 예시로 최적화 배지를 보인다.
"""

from contextlib import ExitStack
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from test_support.qt_runtime import configure_offscreen_fonts
from test_support.boundaries import ExternalBoundaries


def render(destination: Path):
    configure_offscreen_fonts()
    from mabinogi_addon import config, feature_access, paths
    from mabinogi_addon.system import autostart
    from mabinogi_addon.system.window_watcher import AlwaysActiveWatcher
    from mabinogi_addon.ui import main_window, optimization_controller
    from mabinogi_addon.ui.blackbox_controller import BADGE_COLORS, BADGE_TIPS, blackbox_badge
    from mabinogi_addon.ui.theme import apply_theme
    from types import SimpleNamespace as NS

    app = QApplication.instance() or QApplication([])
    destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as tmp, ExitStack() as stack:
        root = Path(tmp)
        original = config.LOCAL_CONFIG_PATH
        read, write = config._read_local_config, config._write_local_config
        target = root / 'config.json'
        stack.enter_context(ExternalBoundaries())
        stack.enter_context(patch.object(config, '_read_local_config',
            lambda path=original: read(target if path == original else path)))
        stack.enter_context(patch.object(config, '_write_local_config',
            lambda data, path=original: write(data, target if path == original else path)))
        stack.enter_context(patch.object(config, 'ENV_PATH', root / '.env'))
        stack.enter_context(patch.object(config, 'load_discord_user',
                                         lambda *a: {'id': feature_access.CREATOR_DISCORD_ID, 'name': '제작자 (예시)'}))
        stack.enter_context(patch.object(paths, 'user_data_dir', lambda: root / 'data'))
        stack.enter_context(patch.object(autostart, 'is_enabled', lambda: False))
        stack.enter_context(patch.object(autostart, 'reconcile', lambda value: None))
        stack.enter_context(patch.object(main_window, 'create_window_watcher', lambda **kw: AlwaysActiveWatcher()))
        stack.enter_context(patch.object(main_window.MainWindow, '_maybe_check_update', lambda self, *args: None))
        stack.enter_context(patch.object(QApplication, 'quit', lambda: None))
        stack.enter_context(patch('os._exit', lambda code: None))
        write({'general': {'skipSetup': True, 'tourShown': True, 'firstUseGuideShown': True}}, target)
        apply_theme('light')
        window = main_window.MainWindow()
        try:
            for timer in window.findChildren(QTimer):
                timer.stop()
            window._pages.setCurrentWidget(window._tabs)
            window.resize(1000, 700)
            window.show()
            text, kind = blackbox_badge(NS(enabled=True, status='recording'), 192_000_000)
            badge = window._blackbox_badge
            badge.setText(text); badge.setStyleSheet(window.status_style(BADGE_COLORS[kind]))
            badge.setToolTip(BADGE_TIPS[kind]); badge.show()
            tools = window.optimization_tools
            bar = window._combat_status.parentWidget()
            for name, state in (('statusbar-opt-applied.png', ('최적화: 적용 중 6+2', 'neutral')),
                                ('statusbar-opt-waiting.png', ('최적화: 게임 대기', 'neutral')),
                                ('statusbar-opt-restore-wait.png', ('최적화: 원복 대기', 'warn')),
                                ('statusbar-opt-error.png', ('최적화: 오류', 'error'))):
                with patch.object(optimization_controller, 'optimization_badge', lambda *a, _s=state, **k: _s):
                    tools._update_badge()
                app.processEvents()
                if not bar.grab().save(str(destination / name)):
                    raise OSError('status bar preview image save failed')
        finally:
            window._force_quit = True
            window.close()
            window.deleteLater()
            app.processEvents()


if __name__ == '__main__':
    render(Path(sys.argv[1] if len(sys.argv) > 1 else 'status-0172'))
