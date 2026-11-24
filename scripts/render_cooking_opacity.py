"""요리 비율 바 불투명도 비교(0.56.1, 사용자 11-24 '게임바를 완전히 가려서 차는 걸 볼 수 없어').

실행: QT_QPA_PLATFORM=offscreen uv run python -m scripts.render_cooking_opacity
- 위: 요리창 그림(게이지에 예시 채움이 일부 찬 상태) 위에 게임 위 바를 50%·100%로 겹친 모습(경계 점선은 늘 그대로)
- 아래: 요리 탭 '게임 위에 이 바 띄우기' 줄(불투명도 칸 자리)
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path  # noqa: E402

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mabinogi_addon import cooking, paths  # noqa: E402
from mabinogi_addon.ui.cooking_gauge import BAR_W, GAUGE, PANEL, CookingBarOverlay  # noqa: E402

OUT = Path("docs/assets/cooking-20261124")


class _Watcher:
    def is_game_active(self):
        return True

    def is_self_active(self):
        return False


def main() -> None:
    app = QApplication.instance() or QApplication([])
    from mabinogi_addon.ui.theme import apply_theme
    apply_theme("dark")
    dish = {d.name: d for d in cooking.load()}["모둠회덮밥"]
    base = QPixmap(str(paths.resource_dir() / "cooking" / "cook_ui_reference.png"))
    x0, y0, x1, y1 = PANEL
    panel = base.copy(x0, y0, x1 - x0, y1 - y0).toImage()
    gauge_w = GAUGE[2] - GAUGE[0] + 2
    rows = []
    for percent in (50, 100):
        o = CookingBarOverlay(gauge_w / BAR_W)
        o.set_dish(dish)
        o.set_opacity(percent)
        o.set_locked(True)
        bar = o.grab().toImage()
        o.close()
        img = panel.copy()
        p = QPainter(img)
        p.drawImage(QPoint(GAUGE[0] - x0 - 1, GAUGE[3] - y0 + 1 - bar.height()), bar)
        p.setPen(QColor("#ffffff"))
        p.drawText(10, 20, f"불투명도 {percent}%")
        p.end()
        rows.append(img)
    from mabinogi_addon.ui.cooking_tab import CookingTab
    tab = CookingTab(_Watcher())
    tab.resize(760, 900)
    tab.select("모둠회덮밥")
    tab.show()
    app.processEvents()
    row = tab.overlay_buttons.grab().toImage()
    tab.shutdown()
    width = max([r.width() for r in rows] + [row.width() * 2]) + 20
    height = sum(r.height() + 10 for r in rows) + row.height() * 2 + 30
    out = QImage(width, height, QImage.Format.Format_ARGB32)
    out.fill(QColor("#1b1e24"))
    p = QPainter(out)
    y = 10
    for r in rows:
        p.drawImage(10, y, r)
        y += r.height() + 10
    p.drawImage(QPoint(10, y + 10), row.scaled(row.width() * 2, row.height() * 2, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
    p.end()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "cooking_bar_opacity.png"
    out.save(str(path))
    print(path)


if __name__ == "__main__":
    main()
