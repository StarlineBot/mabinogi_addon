"""최적화 명세 13.7: 우선순위 두 경로 교차 확인(판정은 OS 없이)."""
import pytest

from mabinogi_addon.system import process_priority as pp


@pytest.mark.parametrize('api, base, expected, text', [
    (pp.HIGH, 13, (pp.HIGH, 'agree'), '높음'),
    (pp.NORMAL, 8, (pp.NORMAL, 'agree'), '보통'),
    (pp.NORMAL, 13, (None, 'mismatch'), '확인 불가(API 보통 · 목록 높음)'),  # 2026-10-24 실사용 같은 모양
    (None, 13, (pp.HIGH, 'list_only'), '높음'),
    (pp.HIGH, None, (pp.HIGH, 'api_only'), '높음'),
    (None, None, (None, 'unknown'), '확인 불가'),
])
def test_two_paths_must_agree_or_reading_is_unconfirmed(api, base, expected, text):
    assert pp.judge(api, base) == expected
    assert pp.describe(dict(api=api, list_base=base)) == text


def test_realtime_is_never_writable():
    assert pp.REALTIME not in pp.WRITABLE and pp.HIGH in pp.WRITABLE
    with pytest.raises(ValueError):
        pp.write(1, pp.REALTIME)


def test_base_numbers_match_windows_classes():
    assert pp.BASE == {pp.IDLE: 4, pp.BELOW_NORMAL: 6, pp.NORMAL: 8, pp.ABOVE_NORMAL: 10, pp.HIGH: 13, pp.REALTIME: 24}
