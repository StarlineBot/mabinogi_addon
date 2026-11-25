"""착장 서랍 렌더(사용자 확인용, 기획 11-25 시안 카드_착장서랍.png와 비교).

- drawer_middle.png: 가운데 줄 레나(호감도 60 — 50 열림·100 잠김) → 오른쪽으로 열림
- drawer_right.png: 맨 오른쪽 줄 다래(사용 중, 호감도 20 — 둘 다 잠김) → 왼쪽으로 열림
- drawer_wearing.png: 아리아가 50 옷을 입은 카드 + 서랍(기본·100)

실행: QT_QPA_PLATFORM=offscreen uv run --frozen python -m scripts.render_outfit_drawer
"""
from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mabinogi_addon import config  # noqa: E402
from mabinogi_addon.ui.theme import apply_theme  # noqa: E402

OUT = Path("docs/assets/character-outfits-20261125")
DARK = {"background": "#1b1e24", "accent": "#00C9A2", "content": "auto"}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    apply_theme("custom", DARK)
    raw = {"voice": {"pack": "조용한 여성"},
           "character": {"pet": True, "outfit": {"부드러운 여성": "tshirt"},
                         "affinity": {"화난 여성": {"value": 60, "cleared": 2}, "조용한 여성": {"value": 20},
                                      "부드러운 여성": {"value": 100, "cleared": 3}, "차분한 남성": {"value": 0}}}}
    with patch.object(config, "_read_local_config", lambda *a, **k: deepcopy(raw)), \
            patch.object(config, "_write_local_config", lambda *a, **k: None):
        from mabinogi_addon.ui.character_tab import CharacterTab
        tab = CharacterTab()
        tab.resize(760, 680)
        tab.show()
        app.processEvents()
        by_name = {c.character.name: c for c in tab.cards}
        for name, file in (("레나", "drawer_middle.png"), ("다래", "drawer_right.png"), ("아리아", "drawer_wearing.png")):
            tab.drawer.open_for(by_name[name], animate=False)
            app.processEvents()
            tab.grab().save(str(OUT / file))
            print(OUT / file, "왼쪽" if tab.drawer.opens_left else "오른쪽")
        tab.drawer.close_drawer()


if __name__ == "__main__":
    main()
