"""Isolated real source startup; run with --tray for hidden startup.

Device pixels are synthetic. Final hard termination is replaced with Qt exit so
thread cleanup can be observed. This is not a frozen Windows integration proof.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from contextlib import ExitStack
from copy import deepcopy
import gc
import json
import tempfile
from types import SimpleNamespace
import mss
from mss.screenshot import ScreenShot
from unittest.mock import patch

from PySide6.QtCore import QTimer, QThread
from PySide6.QtWidgets import QApplication
import mabinogi_addon
from mabinogi_addon import config, paths
from mabinogi_addon.setup_state import FEATURES
from mabinogi_addon.ui import main_window
from mabinogi_addon.ui.splash import Splash
from test_support.boundaries import ExternalBoundaries


def main():
    tray = "--tray" in sys.argv
    raw = {
        "general": {"startInTray": tray, "skipSetup": True},
        "buffTracker": {"enabled": False},
        "debuffTracker": {"enabled": False},
        "dorcha": {"enabled": False},
        "haloTimer": {"enabled": False},
    }
    raw.update({feature.section: {"enabled": False} for feature in FEATURES})
    events = []
    start = main_window.MainWindow.start
    with ExitStack() as stack:
        temporary = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        (temporary / "data").mkdir()
        boundary = stack.enter_context(ExternalBoundaries())
        stack.enter_context(patch("os._exit", lambda code: QApplication.exit(code)))
        monitors = [dict(left=0, top=0, width=1920, height=1080)] * 2
        capture_requests = []

        def sample_frame(region):
            capture_requests.append(dict(region))
            return ScreenShot(bytearray(region["width"] * region["height"] * 4), region)

        def capture_device():
            return SimpleNamespace(
                monitors=monitors, close=lambda: None, grab=sample_frame
            )

        stack.enter_context(patch.object(mss, "mss", capture_device))
        stack.enter_context(patch.object(mss, "MSS", capture_device))
        stack.enter_context(
            patch.object(paths, "user_data_dir", lambda: temporary / "data")
        )
        stack.enter_context(patch.object(config, "ENV_PATH", temporary / ".env"))
        stack.enter_context(
            patch.object(config, "_read_local_config", lambda *a, **k: deepcopy(raw))
        )

        def write(data, *a, **k):
            raw.clear()
            raw.update(deepcopy(data))

        stack.enter_context(patch.object(config, "_write_local_config", write))
        stack.enter_context(patch.object(config, "load_discord_user", lambda: None))

        def started(window):
            window._post_show_done = (
                True  # Observe startup without opening post-entry tours.
            )
            start(window)
            visible = [
                w
                for w in QApplication.topLevelWidgets()
                if isinstance(w, Splash) and w.isVisible()
            ]
            assert len(visible) == (0 if tray else 1), len(visible)
            events.append({"phase": "started", "visible_loaders": len(visible)})

            def finish():
                visible = [
                    w
                    for w in QApplication.topLevelWidgets()
                    if isinstance(w, Splash) and w.isVisible()
                ]
                assert not visible
                assert window.isVisible() != tray
                events.append(
                    {
                        "phase": "entered",
                        "main_visible": window.isVisible(),
                        "visible_loaders": len(visible),
                    }
                )
                window._force_quit = True
                window.close()

            QTimer.singleShot(400, finish)
            QTimer.singleShot(10000, lambda: QApplication.exit(17))

        stack.enter_context(patch.object(main_window.MainWindow, "start", started))
        try:
            mabinogi_addon.main()
        except SystemExit as exit:
            assert exit.code == 0, exit.code
        assert not boundary.violations, boundary.violations
        running = []
        for obj in gc.get_objects():
            if isinstance(obj, QThread):
                try:
                    if obj.isRunning():
                        running.append(type(obj).__name__)
                except RuntimeError:
                    pass
        assert not running, running
    print(
        "STARTUP_SMOKE "
        + json.dumps(
            {
                "tray": tray,
                "events": events,
                "running_threads": running,
                "sample_frames": len(capture_requests),
            }
        )
    )


if __name__ == "__main__":
    main()
