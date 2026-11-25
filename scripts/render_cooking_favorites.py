"""요리 즐겨찾기 순서 바꾸기 렌더(11-25) — 즐겨찾기 카테고리, 저장 순서 그대로 + 끄는 중 놓일 자리 선(흉내).

실행: QT_QPA_PLATFORM=offscreen uv run --frozen python -m scripts.render_cooking_favorites
"""
from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mabinogi_addon import config  # noqa: E402
from mabinogi_addon.ui.theme import apply_theme  # noqa: E402

OUT = Path("docs/assets/cooking-favorites-20261125")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    apply_theme("custom", {"background": "#1b1e24", "accent": "#00C9A2", "content": "auto"})
    raw = {"cooking": {"favorites": ["불금 반반 치맥 세트", "모둠회덮밥", "까맣게 구워진 드래곤 심장", "딸기잼", "BnR"]}}
    with patch.object(config, "_read_local_config", lambda *a, **k: deepcopy(raw)), \
            patch.object(config, "_write_local_config", lambda *a, **k: None):
        from mabinogi_addon.ui.cooking_tab import CookingTab
        tab = CookingTab()
        tab.resize(760, 680)
        tab.show()
        tab.category_list.setCurrentItem(tab.category_list.item(0))
        tab.select("모둠회덮밥", stay=True)
        app.processEvents()
        image = tab.grab()
        # 끄는 중 놓일 자리 선(Qt 기본 표시를 흉내 — 오프스크린에선 실제 끌기를 찍을 수 없음): 4번째 줄 위
        rect = tab.dish_list.visualItemRect(tab.dish_list.item(3))
        top_left = tab.dish_list.viewport().mapTo(tab, QPoint(rect.left(), rect.top()))
        p = QPainter(image)
        p.setPen(QPen(QColor("#00C9A2"), 2))
        p.drawLine(top_left.x() + 2, top_left.y(), top_left.x() + rect.width() - 4, top_left.y())
        p.end()
        image.save(str(OUT / "favorites_drag.png"))
        print(OUT / "favorites_drag.png", tab.dish_list.toolTip(), tab.can_reorder())
        tab.shutdown()


if __name__ == "__main__":
    main()
