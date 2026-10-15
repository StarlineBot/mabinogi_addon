"""사용 준비 화면 렌더. 사용자 설정이나 네트워크를 변경하지 않는다."""

import os
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from mabinogi_addon import config
from mabinogi_addon.ui.setup_page import SetupPage


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    out = Path("/tmp/setup-preview")
    out.mkdir(exist_ok=True)
    raw = {"general": {"gameExe": "Client.exe"},
           "buffTracker": {"enabled": True, "captureRegion": {"x": 10, "y": 20, "w": 300, "h": 500}},
           "debuffTracker": {"enabled": False}, "tuarim": {"enabled": True},
           "bossPattern": {"enabled": True}, "skillbar": {"enabled": True},
           "customOverlay": {"enabled": False}, "memo": {"enabled": False}}
    with patch.object(config, "_read_local_config", return_value=raw), \
            patch.object(config, "load_discord_user", return_value={"id": "preview"}):
        page = SetupPage()
        page.resize(790, 744)
        page.show()
        app.processEvents()
        page.grab().save(str(out / "ready.png"))
        raw["tuarim"]["box"] = {"x": 740, "y": 918, "w": 42, "h": 16}
        page.refresh()
        page.progress.setText("등록 완료 1 / 등록하지 않음 1 / 찾지 못함 1")
        app.processEvents()
        page.grab().save(str(out / "registered.png"))
        page.close()
    from mabinogi_addon.setup_state import FEATURES
    empty = {feature.section: {"enabled": False} for feature in FEATURES}
    with patch.object(config, "_read_local_config", return_value=empty), \
            patch.object(config, "load_discord_user", return_value=None):
        page = SetupPage()
        page.resize(790, 744)
        page.show()
        app.processEvents()
        page.grab().save(str(out / "new-user.png"))
        page.selection.verticalScrollBar().setValue(page.selection.verticalScrollBar().maximum())
        app.processEvents()
        page.grab().save(str(out / "new-user-scrolled.png"))
        page.close()
    with patch.object(config, "_read_local_config", return_value=raw), \
            patch.object(config, "load_discord_user", return_value=None):
        page = SetupPage()
        page.resize(790, 744)
        page.show()
        app.processEvents()
        page.grab().save(str(out / "existing-logged-out.png"))
        page.close()
    print(out)


def render_tabs():
    from mabinogi_addon.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    raw = {"general": {"gameExe": "Client.exe", "skipSetup": True}}
    out = Path("/tmp/setup-preview")
    out.mkdir(exist_ok=True)
    def write(data, *args, **kwargs):
        raw.clear()
        raw.update(deepcopy(data))
    with patch.object(config, "_read_local_config", side_effect=lambda *a, **k: deepcopy(raw)), \
            patch.object(config, "_write_local_config", side_effect=write), \
            patch.object(config, "load_discord_user", return_value={"id": "preview", "name": "미리보기"}), \
            patch("os._exit"):
        window = MainWindow()
        window.show()
        window._pages.setCurrentWidget(window._tabs)
        for section, tabs in (("tracker", window._tracker_tabs), ("convenience", window._convenience_tabs)):
            window._tabs.setCurrentWidget(tabs)
            for index in range(tabs.count()):
                tabs.setCurrentIndex(index)
                app.processEvents()
                window.grab().save(str(out / f"{section}_{index}.png"))
        window._force_quit = True
        window.close()


if __name__ == "__main__":
    main()
    render_tabs()
