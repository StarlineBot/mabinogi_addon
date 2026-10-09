"""신규 기본 버프(마기그래프·활력의 목소리) 회귀 테스트.

번들(DEFAULT) 자산만으로:
- 카탈로그에 포함되고 한글 이름이 붙는지
- 지정한 기본 순서(마기=상태지원 뒤, 활력의 목소리=투안 뒤)대로 들어가는지
- 매칭 아이콘 + 표시 이미지가 짝지어지는지
- 아이콘 템플릿이 실제로 탐지(자가 매칭)되는지
를 고정한다. (devdata/USER 폴더 영향을 받지 않도록 DEFAULT 디렉터리만 지정.)
"""

import numpy as np

from mabinogi_addon.catalog import (
    DEFAULT_ICON_DIR,
    DEFAULT_IMAGE_DIR,
    build_templates,
    load_catalog,
)
from mabinogi_addon.detect import match_icon

_NEW = {"magi": "마기그래프", "voice_of_vitality": "활력의 목소리"}


def _bundle_catalog():
    return load_catalog(
        icon_dirs=(DEFAULT_ICON_DIR,), image_dirs=(DEFAULT_IMAGE_DIR,)
    )


def test_new_buffs_present_with_korean_names():
    by_id = {b.id: b for b in _bundle_catalog()}
    for bid, name in _NEW.items():
        assert bid in by_id, f"{bid} 번들에 없음"
        assert by_id[bid].name == name
        assert by_id[bid].display_image is not None  # 표시 이미지 짝지어짐


def test_new_buffs_order_positions():
    ids = [b.id for b in _bundle_catalog()]
    # 마기그래프는 상태지원 바로 뒤, 활력의 목소리는 투안 바로 뒤.
    assert ids.index("magi") == ids.index("sharp") + 1
    assert ids.index("voice_of_vitality") == ids.index("tuan") + 1


def test_new_buff_icons_self_match():
    templates = build_templates(_bundle_catalog())
    for bid in _NEW:
        tmpl = templates.get(bid)
        assert tmpl is not None, f"{bid} 템플릿 로드 실패"
        h, w = tmpl.shape[:2]
        # 아이콘을 여백 있는 영역 가운데 올려 자가 매칭(실제 탐지 경로와 동일).
        region = np.zeros((h + 16, w + 16, 3), dtype=np.uint8)
        region[8 : 8 + h, 8 : 8 + w] = tmpl
        result = match_icon(region, tmpl)
        assert result.score > 0.95
        assert abs(result.x - 8) <= 2
        assert abs(result.y - 8) <= 2
