"""Render new tab controls and reference detection boxes without game/credentials."""

from pathlib import Path
import argparse

import cv2
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, image_io
from mabinogi_addon.autofind_replay import detector_assets, run_detector
from mabinogi_addon.ui.skillbar_tab import SkillbarTab
from mabinogi_addon.ui.tuarim_tab import TuarimTab


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    config._read_local_config = lambda *a, **k: {}
    config.load_discord_user = lambda: {"id": "render-only"}
    class Watcher:
        def is_game_active(self): return False
        def is_self_active(self): return False
    for name, widget in (("tuarim", TuarimTab(Watcher())), ("skillbar", SkillbarTab(Watcher()))):
        widget._timer.stop()
        widget.resize(760, 700)
        widget.show()
        app.processEvents()
        widget.grab().save(str(args.output / f"{name}_tab.png"))
        widget.shutdown()
        widget.close()
    root = Path(__file__).resolve().parents[1]
    for i, name in enumerate(("스크린샷 2026-10-10 190116.png", "스크린샷 2026-10-12 200511.png")):
        frame = image_io.imread(root / "tests/data" / name)
        for feature in ("tuarim", "skillbar"):
            box = run_detector(feature, frame, detector_assets(feature), {})
            assert box is not None
            x, y, w, h = box
            if feature == "tuarim":
                left, top = max(0, x - 45), max(0, y - 60)
                crop = frame[top:y + h + 8, left:x + w + 8].copy()
                cv2.rectangle(crop, (x - left - 1, y - top - 1), (x - left + w, y - top + h), (180, 224, 0), 1)
                crop = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
            else:
                crop = frame[:130, :1250].copy()
                cv2.rectangle(crop, (x, y), (x + w, y + h), (180, 224, 0), 2)
            assert image_io.imwrite(args.output / f"{feature}_reference_{i}.png", crop)


if __name__ == "__main__":
    main()
