import logging

from mabinogi_addon.log_throttle import ExceptionThrottle


def _raise(n):
    try:
        if n:
            raise UnboundLocalError(f'value {n}')
    except UnboundLocalError as exc:
        return type(exc), exc, exc.__traceback__


def test_repeated_exception_logs_traceback_once_then_periodic_summary(caplog):
    throttle = ExceptionThrottle(every=100)
    logger = logging.getLogger('throttle-test')
    with caplog.at_level(logging.CRITICAL, logger='throttle-test'):
        actions = [throttle.log(logger, '처리되지 않은 예외', _raise(i + 1)) for i in range(250)]
    assert actions.count('full') == 1 and actions[0] == 'full'
    assert actions.count('summary') == 2 and actions[99] == 'summary' and actions[199] == 'summary'
    records = caplog.records
    assert len(records) == 3
    assert records[0].exc_info is not None
    assert all(r.exc_info is None for r in records[1:])
    assert '같은 예외 100회 반복' in records[1].getMessage() and 'UnboundLocalError' in records[1].getMessage()


def test_different_exception_location_is_logged_in_full():
    throttle = ExceptionThrottle()
    logger = logging.getLogger('throttle-test-2')
    first = _raise(1)
    try:
        raise ValueError('x')
    except ValueError as exc:
        other = (ValueError, exc, exc.__traceback__)
    assert throttle.log(logger, 'm', first) == 'full'
    assert throttle.log(logger, 'm', other) == 'full'
    assert throttle.log(logger, 'm', first) == 'skip'
