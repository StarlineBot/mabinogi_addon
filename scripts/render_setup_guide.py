"""로컬 샘플 설정으로 단계별 안내 렌더. 사용자 파일/네트워크를 사용하지 않는다."""

import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPainter, QPixmap, QFont, QPalette, QColor

from mabinogi_addon import config
from mabinogi_addon.setup_state import FEATURES
from mabinogi_addon.ui.setup_guide import SetupGuide


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    out = Path("/tmp/setup-guide-preview")
    out.mkdir(exist_ok=True)
    from test_support.qt_runtime import configure_offscreen_fonts
    configure_offscreen_fonts()
    app.setFont(QFont("Noto Sans CJK KR", 10))
    raw = {feature.section: {"enabled": False} for feature in FEATURES}
    raw['general'] = {'gameExe': 'Client.exe'}
    raw['statBars']['bars'] = {sid: {'show': False} for sid in ('hp', 'mp', 'sta')}
    raw['autofind'] = {'found': {key: {'box': dict(x=100, y=200, w=300, h=400)}
                               for key in ('buff', 'dorcha', 'tuarim', 'skillbar')}}
    with patch.object(config, "_read_local_config", return_value=raw), \
            patch.object(config, "load_discord_user", return_value={"id": "preview", "name": "미리보기"}), \
            patch.object(config, "_write_local_config"):
        from mabinogi_addon.ui.theme import apply_theme
        for theme in ('light', 'dark'):
            apply_theme(theme)
            palette = QPalette()
            if theme == 'dark':
                for role, value in ((QPalette.Window, '#20242b'), (QPalette.WindowText, '#e5e7eb'),
                                    (QPalette.Base, '#15191f'), (QPalette.Text, '#e5e7eb'),
                                    (QPalette.Button, '#303640'), (QPalette.ButtonText, '#e5e7eb')):
                    palette.setColor(role, QColor(value))
            app.setPalette(palette)
            page = SetupGuide()
            page.reset(first_run=True)
            page.resize(790, 744)
            page.show()
            for key in ('boss', 'debuff', 'halo_timer'):
                page.record_result(key, '나타나면 찾기')
            page.record_result('stat_bars', '못 찾음 · 현재 화면에서 미발견')
            for stage in range(4):
                page.stage = stage
                page.refresh()
                app.processEvents()
                app.processEvents()
                assert page.body_scroll.horizontalScrollBar().maximum() == 0
                page.grab().save(str(out / f"{theme}-stage-{stage + 1}.png"))
            page.close()
        render_tour(app, out)
    print(out)


def render_tour(app, out):
    from _pytest.monkeypatch import MonkeyPatch
    from scripts.qa_setup_audio_boundary import install
    from mabinogi_addon.ui.main_window import MainWindow

    with MonkeyPatch.context() as boundary, patch.object(QApplication, "quit", lambda: None):
        install(boundary)
        window = MainWindow()
        try:
            window.move(0, 0)
            window.show()
            app.processEvents()
            window._open_setup()
            app.processEvents()
            window.grab().save(str(out / "default-start.png"))
            window.setup_guide.active = False
            window._leave_setup()
            window._tabs.setCurrentWidget(window._settings_scroll)
            window._settings_scroll.ensureWidgetVisible(window.settings_tab.setup_btn)
            app.processEvents()
            window.grab().save(str(out / "settings-entry.png"))
            window._run_tour(from_guide=True)
            app.processEvents()
            app.processEvents()
            tour = window._tour
            scene = QPixmap(tour.size())
            scene.fill(Qt.GlobalColor.white)
            painter = QPainter(scene)
            painter.drawPixmap(window.mapToGlobal(QPoint()) - tour.pos(), window.grab())
            painter.drawPixmap(0, 0, tour.grab())
            painter.end()
            scene.save(str(out / "stage-5-tour.png"))
        finally:
            window._force_quit = True
            window.close()


if __name__ == "__main__":
    main()
