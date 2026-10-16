"""실제 제작자 잡담 위젯 렌더. 사용자 설정/외부 장치는 변경하지 않는다."""

import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config
from mabinogi_addon.ui.main_window import MainWindow
from test_support.boundaries import ExternalBoundaries


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    out = Path("/tmp/creator-dialogue-preview")
    out.mkdir(exist_ok=True)
    raw = {"general": {"skipSetup": True}}
    with ExternalBoundaries() as boundary, \
            patch.object(config, "_read_local_config", side_effect=lambda *a, **k: deepcopy(raw)), \
            patch.object(config, "_write_local_config"), \
            patch.object(config, "load_discord_user", return_value={"id": "preview", "name": "미리보기"}), \
            patch.object(QApplication, "quit"), patch("os._exit"):
        window = MainWindow()
        try:
            # 시안은 충분한 작업 영역 기준. 작은 실제 화면에서는 제품의 높이 제한을 사용.
            screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1600, 1100))
            with patch.object(window, "screen", return_value=screen):
                window.show()
                app.processEvents()
                d = window.creator_dialogue
                d.visibility = lambda *args: True
                d.refresh()
                app.processEvents()
                window.grab().save(str(out / "tracker-idle.png"))
                d.bubble.set_message("방금 대단한 생각을 했는데 까먹었습니다.")
                d._position(d.bubble.text.text())
                d.bubble.show()
                d.bubble.raise_()
                window.grab().save(str(out / "tracker-speaking.png"))
                d._position("지금은 잠깐 생각 중입니다. 조금만 더 생각해 보겠습니다.")
                window.grab().save(str(out / "tracker-wrapped.png"))
                d.dismiss()
                window.buff_tab.buff_list.setCurrentRow(4)
                app.processEvents()
                window.grab().save(str(out / "buff-normal.png"))
                with patch.object(window, "screen", return_value=SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1100, 730))):
                    d.refresh()
                    app.processEvents()
                    window.grab().save(str(out / "buff-small.png"))
                d.refresh()
                window._tracker_tabs.setCurrentIndex(1)
                for mode in ("off", "band", "percent"):
                    window.debuff_tab.method_combo.setCurrentIndex(window.debuff_tab.method_combo.findData(mode))
                    app.processEvents()
                    window.grab().save(str(out / f"debuff-{mode}.png"))
                window.debuff_tab.status_label.setText("게임 비활성 상태입니다. 게임창을 확인한 뒤 지정한 영역의 판독을 다시 시작합니다.")
                window.debuff_tab._bar_gating_notice.setText("베타 확인 방식은 게임 화면과 보스 HP 영역이 보이는 상태에서 확인합니다. 안내가 길어져도 아래 목록과 버튼을 사용할 수 있어야 합니다.")
                app.processEvents()
                window.grab().save(str(out / "debuff-long.png"))
                with patch.object(window, "screen", return_value=SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1100, 730))):
                    d.refresh()
                    app.processEvents()
                    window.grab().save(str(out / "debuff-small.png"))
                window._tabs.setCurrentIndex(1)
                d.refresh()
                app.processEvents()
                window.grab().save(str(out / "party.png"))
                window._tabs.setCurrentIndex(2)
                for index, name in ((0, "custom"), (3, "memo"), (6, "exchange")):
                    window._convenience_tabs.setCurrentIndex(index)
                    app.processEvents()
                    window.grab().save(str(out / f"{name}.png"))
                window._tabs.setCurrentIndex(3)
                app.processEvents()
                d._position("...방금 무슨 생각 하고 있었지?")
                d.bubble.show()
                d.bubble.raise_()
                window.grab().save(str(out / "settings-speaking.png"))
        finally:
            window._force_quit = True
            window.close()
            app.processEvents()
        if boundary.violations:
            raise AssertionError(boundary.violations)
    print(out)


if __name__ == "__main__":
    main()
