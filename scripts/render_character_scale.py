"""다섯 캐릭터 서 있기 나란히(앱 펫 창 그리기 경로 그대로) — 캐릭터별 배율(사용자 11-24 B안: Starline ×1.15, 레나 ×0.95) 확인용.

실행: QT_QPA_PLATFORM=offscreen uv run python -m scripts.render_character_scale
"""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mabinogi_addon.character import roster  # noqa: E402
from mabinogi_addon.character.brain import PROFILES, Brain, Floor  # noqa: E402
from mabinogi_addon.ui.pet_window import WIN_H, WIN_W, PetWindow, load_frames  # noqa: E402
from scripts.render_pet_gif import OUT  # noqa: E402


def main() -> None:
    app = QApplication.instance() or QApplication([])
    order = ["Starline", "레나", "다래", "이안", "아리아"]
    step = 190
    image = QImage(step * len(order) + WIN_W - step, WIN_H, QImage.Format.Format_ARGB32)
    image.fill(QColor("#2b3a55"))
    p = QPainter(image)
    for i, folder in enumerate(order):
        character = next(c for c in roster.ROSTER if roster.folder(c) == folder)
        profile = PROFILES[folder]
        brain = Brain(Floor(0, 2000, 700), rng=random.Random(1), profile=profile)
        brain._next_walk = brain._next_idle = brain._next_extra = 1e9   # 서 있기 그대로
        window = PetWindow(brain, load_frames(folder, profile), character.color, clock=lambda: 1.0,
                           outline=character.outline)
        window.step()
        p.drawImage(QPoint(i * step, 0), window.grab().toImage())
        window.close()
    p.setPen(QColor("#ffffff"))
    for i, folder in enumerate(order):
        p.drawText(i * step + WIN_W // 2 - 30, 18, f"{folder} ×{PROFILES[folder].scale:g}")
    p.end()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "five_standing_scale.png"
    image.save(str(path))
    print(path)
    app.processEvents()


if __name__ == "__main__":
    main()
