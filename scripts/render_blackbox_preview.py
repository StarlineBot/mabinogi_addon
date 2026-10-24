"""블랙박스 탭(0.16.0, 제작자가 아닌 디스코드 로그인 사용자)의 샘플 렌더. 장치/네트워크/설정 격리.

꺼짐·녹화 중·오류 3장 + 단축키 변경 창 2장(통과·실패) + 상단 상태 줄 3장 + 저장 내역·복구 창.

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
                                         lambda: {'id': '1234567890', 'name': '일반 사용자 (예시)'}))
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
            for control in panel.controls():
                control.setEnabled(True)
            panel.folder.setText(r'C:\Users\예시\Videos\마비노기 블랙박스')
            window.show()
            states = {
                'blackbox-off-preview.png': dict(on=False, status='사용 안 함', available='확보한 영상 0초 / 설정 5분',
                                                 recent='최근 저장: 아직 없어요', error=''),
                'blackbox-recording-preview.png': dict(on=True, status='보관 중', available='확보한 영상 3분 12초 / 설정 5분',
                                                       recent='최근 저장: 15:52 · 1분 49초 영상 · blackbox-20261024-155210.mp4',
                                                       error=''),
                'blackbox-error-preview.png': dict(on=True, status='녹화 오류', available='확보한 영상 0초 / 설정 5분',
                                                   recent='최근 저장: 저장 안 함 · 녹화 오류로 저장할 영상이 없어요 · 앱에서 확인',
                                                   error='영상 인코더가 멈춰 녹화를 중단했어요 (자세한 내용: app.log)'),
            }
            for name, state in states.items():
                panel.enabled.setChecked(state['on'])
                panel.status.setText(state['status'])
                panel.available.setText(state['available'])
                panel.recent.setText(state['recent'])
                panel.show_error(state['error'])
                app.processEvents()
                if not window.grab().save(str(destination / name)):
                    raise OSError('preview image save failed')
            # 상단 상태 줄(0.16.0 추가): 둘 다 켜짐 / 전투 보조 일시정지 / 블랙박스 오류. 상태 표시만 바꾼다(동작 연결 없음).
            from mabinogi_addon.ui.blackbox_controller import BADGE_COLORS, BADGE_TIPS, blackbox_badge
            from types import SimpleNamespace as _NS
            badge, bar = window._blackbox_badge, window._combat_status.parentWidget()
            for name, paused, status in (('statusbar-both-on-preview.png', False, 'recording'),
                                         ('statusbar-combat-paused-preview.png', True, 'recording'),
                                         ('statusbar-blackbox-error-preview.png', False, 'error')):
                window._paused = paused
                window._update_header_status()
                text, kind = blackbox_badge(_NS(enabled=True, status=status), 192_000_000)
                badge.setText(text)
                badge.setStyleSheet(window.status_style(BADGE_COLORS[kind]))
                badge.setToolTip(BADGE_TIPS[kind])
                badge.show()
                app.processEvents()
                if not bar.grab().save(str(destination / name)):
                    raise OSError('status bar preview image save failed')
            window._paused = False
            window._update_header_status()
            badge.hide()
            # 단축키 변경 창: 통과(초록, 저장 가능) / 실패(빨강, 저장 비활성)
            from mabinogi_addon.ui.blackbox_hotkey_dialog import HotkeyDialog
            for name, (modifiers, vk) in (('blackbox-hotkey-ok-preview.png', (2 | 4, 0x79)),
                                          ('blackbox-hotkey-invalid-preview.png', (8, 0x79))):
                dialog = HotkeyDialog((3, 0x2C), window)
                dialog.feed(True, None, modifiers)
                dialog.feed(True, vk, modifiers)
                dialog.show(); app.processEvents()
                if not dialog.grab().save(str(destination / name)):
                    raise OSError('hotkey preview image save failed')
                dialog.close(); dialog.deleteLater()
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
