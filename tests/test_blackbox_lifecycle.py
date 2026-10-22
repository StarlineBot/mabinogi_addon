from mabinogi_addon.blackbox_lifecycle import BlackboxLifecycle


class Runtime:
    def __init__(self):
        self.started = 0
        self.finished = 0
        self.ready = False
    def begin_close(self):
        self.started += 1
    def finish_close(self):
        self.finished += 1
        return self.ready


class Spool:
    def __init__(self):
        self.closed = 0
        self.fail = False
    def close(self):
        if self.fail:
            raise PermissionError('busy')
        self.closed += 1


class Producer:
    def __init__(self):
        self.requests = 0
        self.stopped = False
        self.fail = False
    def request_stop(self):
        self.requests += 1
        if self.fail:
            raise OSError('stop failed')
    def is_stopped(self):
        return self.stopped


def test_shutdown_waits_for_native_producers_then_results_then_cleanup():
    runtime, spool, producer = Runtime(), Spool(), Producer()
    lifecycle = BlackboxLifecycle(runtime, spool, producers=(producer,))
    assert not lifecycle.prepare_close()
    assert runtime.started == 1 and runtime.finished == spool.closed == 0
    assert not lifecycle.prepare_close() and producer.requests == 1
    producer.stopped = True
    assert not lifecycle.prepare_close() and spool.closed == 0
    runtime.ready = True
    spool.fail = True
    assert not lifecycle.prepare_close() and 'cleanup pending' in lifecycle.pending_reason
    spool.fail = False
    assert lifecycle.prepare_close() and lifecycle.prepare_close()
    assert spool.closed == 1 and runtime.started == producer.requests == 1


def test_stop_failure_does_not_prevent_stopping_other_producers():
    runtime, spool, first, second = Runtime(), Spool(), Producer(), Producer()
    first.fail = True
    lifecycle = BlackboxLifecycle(runtime, spool, producers=(first, second))
    assert not lifecycle.prepare_close()
    assert first.requests == second.requests == 1 and runtime.finished == 0
    first.fail = False
    first.stopped = second.stopped = runtime.ready = True
    assert lifecycle.prepare_close()
    assert first.requests == 2 and second.requests == 1


def test_truthy_native_state_is_not_completed():
    runtime, spool, producer = Runtime(), Spool(), Producer()
    runtime.ready = True
    producer.stopped = 1
    lifecycle = BlackboxLifecycle(runtime, spool, producers=(producer,))
    assert not lifecycle.prepare_close() and runtime.finished == 0
