"""카드 테두리·상태 렌더(기획 11-25 — 시안 카드_테두리_최종.png와 비교).

- frames_states.png: 다래 사용 중(명판)·레나 적용 대기(떠오름 + 버튼)·나머지 25% 어둡게, 아리아에 마우스(원래 밝기)
- frames_drawer.png: 레나 적용 대기 + 서랍 열림(떠오른 카드에 맞춤)
- frames_full.png: 탭 전체(스크롤 없이 늘려서)

실행: QT_QPA_PLATFORM=offscreen uv run --frozen python -m scripts.render_card_frames
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

OUT = Path("docs/assets/character-frames-20261125")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    apply_theme("custom", {"background": "#1b1e24", "accent": "#00C9A2", "content": "auto"})
    raw = {"voice": {"pack": "조용한 여성"},
           "character": {"pet": True, "affinity": {"화난 여성": {"value": 60, "cleared": 2}}}}
    with patch.object(config, "_read_local_config", lambda *a, **k: deepcopy(raw)), \
            patch.object(config, "_write_local_config", lambda *a, **k: None):
        from mabinogi_addon.ui.character_tab import CharacterTab
        tab = CharacterTab()
        tab._play_sample = lambda pack: None
        tab.resize(766, 960)
        tab.show()
        app.processEvents()
        by_name = {c.character.name: c for c in tab.cards}
        tab.grab().save(str(OUT / "frames_full.png"))
        tab.preview(by_name["레나"].character)          # 레나 적용 대기
        by_name["아리아"]._hover = True                  # 아리아에 마우스
        tab.frames.update()
        app.processEvents()
        tab.grab().save(str(OUT / "frames_states.png"))
        by_name["아리아"]._hover = False
        tab.drawer.open_for(by_name["레나"], animate=False)
        app.processEvents()
        tab.grab().save(str(OUT / "frames_drawer.png"))
        for f in ("frames_full.png", "frames_states.png", "frames_drawer.png"):
            print(OUT / f)


if __name__ == "__main__":
    main()
