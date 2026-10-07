"""로그 링버퍼(문의 '버그 신고' 첨부용) 테스트."""

import logging

from mabinogi_addon.logbuffer import RingBufferHandler


def test_ring_buffer_keeps_recent_lines():
    h = RingBufferHandler(capacity=3)
    h.setFormatter(logging.Formatter("%(message)s"))
    for i in range(5):
        h.emit(
            logging.LogRecord("t", logging.INFO, __file__, i, f"line{i}", None, None)
        )
    # 마지막 3줄만 보관
    assert h.text().splitlines() == ["line2", "line3", "line4"]


def test_recent_logs_empty_when_not_installed():
    # install() 전 전역 핸들러 없음 → 빈 문자열(모듈 상태 의존 최소화 위해 직접 확인)
    import mabinogi_addon.logbuffer as lb

    if lb._handler is None:
        assert lb.recent_logs() == ""
