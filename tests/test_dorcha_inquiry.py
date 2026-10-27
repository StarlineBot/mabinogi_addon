"""2026-10-27 타 사용자 문의(도르카 인식 안 됨): 밝은 배경에서 장식 점수 0.94~0.97은 숫자를 읽을 때만 인정, 진단에 영역·거절 이유."""
from pathlib import Path

import numpy as np
import pytest

from mabinogi_addon import diagnostics, image_io
from mabinogi_addon.detect import dorcha_anchor
from mabinogi_addon.detect.dorcha_anchor import locate_dorcha

DATA = Path(__file__).parent / 'data'


@pytest.mark.parametrize('name, value, score', [
    ('2026-10-11_111640.png', 0, 0.963),           # 4K, 밝은 배경
    ('스크린샷 2026-10-15 213734.png', 3, 0.966),
    ('스크린샷 2026-10-09 201512.png', 15, 0.967),
])
def test_bright_background_ornament_is_accepted_when_digits_read(name, value, score):
    trace = {}
    box = locate_dorcha(image_io.imread(DATA / name), diagnostics=trace)
    assert box is not None and trace['value'] == value and trace['soft_ornament']
    assert abs(trace['ornament']['score'] - score) < 0.002 and trace['ornament']['score'] < 0.97


def test_soft_ornament_without_readable_digits_is_rejected():
    frame = image_io.imread(DATA / '2026-10-11_111640.png').copy()
    x, y, w, h = locate_dorcha(frame)
    frame[y:y + h, x:x + w] = 40  # 숫자를 지움 → 0.94~0.97 장식만으로는 인정하지 않음
    trace = {}
    assert locate_dorcha(frame, diagnostics=trace) is None and trace['rejection'] == 'anchor_not_found'


def test_soft_floor_is_dorcha_only():
    assert dorcha_anchor.SOFT_ACCEPT == 0.94
    from mabinogi_addon.detect.autofind_anchors import ACCEPT
    assert ACCEPT == 0.97  # 투아림·단축바 등 다른 탐색 기준은 그대로


def test_diagnostics_header_has_dorcha_region_and_last_reason(monkeypatch):
    from mabinogi_addon import config
    monkeypatch.setattr(config, 'load_dorcha', lambda *a: {'box': {'x': 1113, 'y': 1736, 'w': 29, 'h': 24}})
    diagnostics.note('도르카 최근 판독', diagnostics.describe_dorcha(
        {'rejection': 'uncertain_word', 'score': 0.849, 'margin': 0.05}, None))
    header = diagnostics.header_text()
    assert '도르카 영역: 29×24 @ (1113,1736)' in header
    assert '도르카 최근 판독: 거절 · uncertain_word · 숫자 점수 0.849·차이 0.050' in header
    assert diagnostics.describe_dorcha({'soft_ornament': True}, 7) == '읽음 7 (장식 낮은 점수 인정)'
    assert diagnostics.describe_dorcha({'rejection': 'anchor_not_found', 'candidates': [{'score': 0.958}]}, None) \
        == '거절 · anchor_not_found · 장식 최고 0.958'
    diagnostics._NOTES.clear()
