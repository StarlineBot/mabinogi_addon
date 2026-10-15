"""보존된 과거 축소 판독 기준선. 제품 코드에서는 사용하지 않는다."""

import cv2

from mabinogi_addon.detect import match_icon
from mabinogi_addon.tracker.debuff_engine import DebuffEngine, _variant


class LegacyScaledEngine(DebuffEngine):
    def __init__(self, templates, order, **kwargs):
        super().__init__(templates, order, **kwargs)
        self._variants = {key: [_variant(template, 10)] for key, template in templates.items()}

    @staticmethod
    def _scale(region):
        h, w = region.shape[:2]
        return cv2.resize(region, (max(1, round(w * 0.625)), max(1, round(h * 0.625))),
                          interpolation=cv2.INTER_AREA)

    def _best(self, small, bid, gray=None):
        return max((match_icon(small, template).score for template in self._variants[bid]), default=-1.0)
