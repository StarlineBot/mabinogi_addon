"""제작자용 최상위 블랙박스 탭의 샘플 렌더. 장치/네트워크/설정 격리.

QT_QPA_PLATFORM=offscreen uv run python -m scripts.render_blackbox_preview /tmp/blackbox-preview
"""

from contextlib import ExitStack
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication

from test_support.qt_runtime import configure_offscreen_fonts
from test_support.boundaries import ExternalBoundaries


def render(destination: Path):
    configure_offscreen_fonts()
    from mabinogi_addon import config, paths
    from mabinogi_addon.system import autostart
    from mabinogi_addon.system.window_watcher import AlwaysActiveWatcher
    from mabinogi_addon.ui import main_window
    from mabinogi_addon.feature_access import CREATOR_DISCORD_ID
    from mabinogi_addon.ui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as tmp, ExitStack() as stack:
        root = Path(tmp)
        original = config.LOCAL_CONFIG_PATH
        read, write = config._read_local_config, config._write_local_config
        target = root / 'config.json'
        boundary = stack.enter_context(ExternalBoundaries())
        stack.enter_context(patch.object(config, '_read_local_config',
            lambda path=original: read(target if path == original else path)))
        stack.enter_context(patch.object(config, '_write_local_config',
            lambda data, path=original: write(data, target if path == original else path)))
        stack.enter_context(patch.object(config, 'ENV_PATH', root / '.env'))
        stack.enter_context(patch.object(config, 'load_discord_user',
                                         lambda: {'id': CREATOR_DISCORD_ID, 'name': '제작자 (예시)'}))
        stack.enter_context(patch.object(paths, 'user_data_dir', lambda: root / 'data'))
        stack.enter_context(patch.object(autostart, 'is_enabled', lambda: False))
        stack.enter_context(patch.object(autostart, 'reconcile', lambda value: None))
        stack.enter_context(patch.object(main_window, 'create_window_watcher', lambda **kw: AlwaysActiveWatcher()))
        stack.enter_context(patch.object(main_window.MainWindow, '_maybe_check_update', lambda self, *args: None))
        stack.enter_context(patch.object(QApplication, 'quit', lambda: None))
        # 제품의 강제 프로세스 종료만 대체해 아래 임시 설정/Qt 정리가 실행되게 한다.
        stack.enter_context(patch('os._exit', lambda code: None))
        write({'general': {'skipSetup': True, 'tourShown': True, 'firstUseGuideShown': True}}, target)
        apply_theme('light')
        window = main_window.MainWindow()
        try:
            # 정적 렌더에서는 기존 탭의 추적/폴링도 실행하지 않는다.
            # ExternalBoundaries는 유지해 놓친 외부 장치 호출이 있으면 실패시킨다.
            for timer in window.findChildren(QTimer):
                timer.stop()
            panel = window.blackbox_tools.panel
            window._tabs.setCurrentWidget(window.blackbox_tools._page)
            window._pages.setCurrentWidget(window._tabs)
            window.resize(1000, 880)
            # 모형의 시각 상태만 변경한다. 어떤 버튼에도 작업/저장 신호 연결은 없다.
            for control in (panel.enabled, panel.retention, panel.save,
                            panel.change_folder, panel.open_folder):
                control.setEnabled(True)
            panel.enabled.setChecked(True)
            panel.status.setText('영상 보관 중 · 예시')
            panel.available.setText('확보한 영상 3분 12초 / 설정 10분')
            panel.audio_info.setText('게임 소리: 무음 진행 예시 · 다른 앱 소리는 녹음하지 않아요.')
            panel.save_result.setText('저장 예시 · 최근 3분 12초를 별도 파일로 저장했어요.')
            window.show()
            app.processEvents()
            for name in ('blackbox-recording-preview.png', 'blackbox-paused-preview.png'):
                if 'paused' in name:
                    panel.status.setText('잠시 멈춤 · 게임이 비활성 상태예요. (예시)')
                    panel.save_result.setText('지금까지 확보한 3분 12초는 저장할 수 있어요. (예시)')
                app.processEvents()
                if not window.grab().save(str(destination / name)):
                    raise OSError('preview image save failed')
            # 새 복구 조작만 별도로 검토한다. 실제 파일/저장 작업은 만들지 않는다.
            from types import SimpleNamespace
            from mabinogi_addon.ui.blackbox_recovery import BlackboxRecovery
            failed = SimpleNamespace(completed=False, error='저장 공간이 부족해 완료하지 못했어요. (예시)', cleanup_error=None)
            service = SimpleNamespace(runtimes={'게임 실행 1 (예시)': object()}, _closing=False,
                _allowed=lambda: True, recoveries=lambda: [(object(), 'sample-failed', failed)],
                orphan_sources=lambda: ())
            dialog = BlackboxRecovery(service, window)
            dialog.setWindowTitle('블랙박스 저장 내역·복구 — 샘플 화면')
            dialog.show(); app.processEvents()
            if not dialog.grab().save(str(destination / 'blackbox-recovery-preview.png')):
                raise OSError('recovery preview image save failed')
            dialog.close(); dialog.deleteLater()
        finally:
            window._force_quit = True
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
        assert not boundary.violations, boundary.violations
    return destination


if __name__ == '__main__':
    print(render(Path(sys.argv[1])))
