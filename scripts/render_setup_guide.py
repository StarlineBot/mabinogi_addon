"""로컬 샘플 설정으로 단계별 안내 렌더. 사용자 파일/네트워크를 사용하지 않는다."""

import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPainter, QPixmap

from mabinogi_addon import config
from mabinogi_addon.setup_state import FEATURES
from mabinogi_addon.ui.setup_guide import SetupGuide


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    out = Path("/tmp/setup-guide-preview")
    out.mkdir(exist_ok=True)
    raw = {feature.section: {"enabled": False} for feature in FEATURES}
    with patch.object(config, "_read_local_config", return_value=raw), \
            patch.object(config, "load_discord_user", return_value={"id": "preview", "name": "미리보기"}), \
            patch.object(config, "_write_local_config"):
        page = SetupGuide()
        page.reset(first_run=True)
        page.resize(790, 744)
        page.show()
        for stage in range(3):
            page.stage = stage
            if stage == 1:
                raw["buffTracker"].update(enabled=True, captureRegion={"x": 1, "y": 2, "w": 300, "h": 400})
                raw["debuffTracker"]["enabled"] = True
            if stage == 2:
                raw["tuarim"]["enabled"] = True
                raw["skillbar"].update(enabled=True, anchor={"x": 10, "y": 20})
            page.refresh()
            app.processEvents()
            app.processEvents()
            page.grab().save(str(out / f"stage-{stage + 1}.png"))
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
            window._tabs.setCurrentIndex(3)
            window._tabs.currentWidget().ensureWidgetVisible(window.settings_tab.setup_btn)
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
            scene.save(str(out / "stage-4.png"))
        finally:
            window._force_quit = True
            window.close()


if __name__ == "__main__":
    main()
