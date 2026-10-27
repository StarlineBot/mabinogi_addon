"""버프·디버프 탭 상태 줄 아이콘(2026-10-27 사용자 결정 B안): 글자 기호 대신 그린 모노톤 아이콘."""
import pytest
from PySide6.QtGui import QColor

from mabinogi_addon.ui.status_icon import KINDS, paint_icon
from test_navigation import window  # noqa: F401  (픽스처)


@pytest.mark.parametrize('kind', KINDS)
def test_each_icon_is_drawn_in_the_status_color_only(window, kind):
    image = paint_icon(kind, '#e67e22').toImage()
    assert image.width() == 28  # 14px × 2(고해상도)
    target = QColor('#e67e22')
    opaque = [image.pixelColor(x, y) for x in range(28) for y in range(28) if image.pixelColor(x, y).alpha() > 200]
    assert opaque and all(max(abs(c.red() - target.red()), abs(c.green() - target.green()), abs(c.blue() - target.blue())) <= 3
                          for c in opaque)  # 단색(모노톤, 안티앨리어싱 반올림만 허용)
    assert image.pixelColor(0, 0).alpha() == 0  # 투명 배경


def test_icons_differ_from_each_other(window):
    images = [paint_icon(kind, '#2ecc71').toImage() for kind in KINDS]
    assert len({bytes(img.constBits()) for img in images}) == len(KINDS)


def test_buff_status_uses_icons_and_no_glyph_prefix(window, monkeypatch):
    w = window[0]
    from mabinogi_addon import config
    monkeypatch.setattr(config, 'load_capture_region', lambda key: None)
    text, color, icon = w._buff_status()
    assert icon == 'region' and text.startswith('영역 미지정') and color == w._STATUS_WARN
    monkeypatch.setattr(config, 'load_capture_region', lambda key: {'x': 0, 'y': 0, 'w': 10, 'h': 10})
    w.buff_controller = None
    assert w._buff_status()[2] == 'waiting' and w._debuff_status()[2] == 'waiting'
    w.buff_tab.set_status(*w._buff_status())
    assert w.buff_tab.status_icon.kind == 'waiting' and not w.buff_tab.status_icon.isHidden()
    assert not w.buff_tab.status_label.text().startswith(('ℹ', '⏸', '⚠', '●'))
    from types import SimpleNamespace as NS
    w.buff_controller = NS(item_count=2)
    monkeypatch.setattr(w._watcher, 'is_game_active', lambda: False)
    assert w._buff_status()[2] == 'inactive'
    monkeypatch.setattr(w._watcher, 'is_game_active', lambda: True)
    w._engine = NS(anchor_seen=False)
    assert w._buff_status()[2] == 'anchor' and '⚓' in w._buff_status()[0]  # 문구 속 ⚓는 유지
    w._engine = NS(anchor_seen=True)
    assert w._buff_status() == ('추적 중 — 버프 2개 표시', w._STATUS_OK, 'ok')
    w.buff_controller = None
