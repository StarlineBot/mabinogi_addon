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
    # 0.30.2 명세 변경: 장식 마스크가 금속 픽셀만 보게 되어(잎사귀 사이 배경 제외) 밝은 배경에서도 예전 점수(score)보다
    # 높게 0.97을 넘는다 → 낮은 점수 인정(soft) 경로 없이 바로 찾고, 값은 그대로.
    trace = {}
    box = locate_dorcha(image_io.imread(DATA / name), diagnostics=trace)
    assert box is not None and trace['value'] == value
    assert trace['ornament']['score'] >= 0.97 > score


def test_soft_ornament_without_readable_digits_is_rejected():
    frame = image_io.imread(DATA / '2026-10-11_111640.png').copy()
    x, y, w, h = locate_dorcha(frame)
    frame[y:y + h, x:x + w] = 40  # 숫자를 지움 → 0.94~0.97 장식만으로는 인정하지 않음
    trace = {}
    # 0.30.2: 장식은 이제 0.97을 넘어 찾지만 숫자가 없으면 여전히 거절(이유가 '숫자 못 읽음'으로 정확해짐)
    assert locate_dorcha(frame, diagnostics=trace) is None and trace['rejection'] == 'unreadable_digits'


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


# ---- ② 문의자 원본(4K, 밝은 모래): 기존 '0' 3종과 가장자리 1px 달라 0.849로 거절 + 장식 최고점이 3px 어긋남 ----

REPORT = 'tests/data/2026-10-24_dorcha_report_4K.png'


def test_inquirer_frame_reads_zero_at_true_box():
    frame = image_io.imread(DATA / '2026-10-24_dorcha_report_4K.png')
    trace = {}
    assert locate_dorcha(frame, diagnostics=trace) == (1112, 1736, 28, 23)
    assert trace['value'] == 0 and trace['soft_ornament']
    from mabinogi_addon.detect.dorcha_reader import read_dorcha
    word = {}
    assert read_dorcha(frame[1736:1759, 1112:1140], word) == 0 and word['score'] > 0.95


def test_inquirer_saved_region_is_corrected_by_verification_crop():
    # 저장 영역(1113,1736 29×24)은 1px 어긋나 그대로는 못 읽지만, 앱의 검증(_verify_registered_region과 같은 여백)이 칸을 바로잡는다
    frame = image_io.imread(DATA / '2026-10-24_dorcha_report_4K.png')
    x, y, w, h = 1113, 1736, 29, 24
    pad_x, pad_y = max(8, w // 2), max(17, h)
    left, top = x - pad_x, y - pad_y
    found = locate_dorcha(frame[top:y + h + pad_y, left:x + w + pad_x])
    assert found is not None and (left + found[0], top + found[1]) == (1112, 1736)


def test_zero_reference_from_inquirer_is_recorded_with_provenance():
    import json
    sources = json.loads((Path(__file__).parents[1] / 'src/mabinogi_addon/detect/templates/dorcha/sources.json').read_text(encoding='utf-8'))
    entry = next(s for s in sources if s['file'] == '2026-10-24_dorcha_report_4K.png')
    assert entry['value'] == 0 and entry['box'] == [1112, 1736, 28, 23]
