import json
import socket
import threading

from test_support.diagnostic_signal import ENVIRONMENT, FailureChannel, notify_failure


def test_run_scoped_signal_ignores_foreign_journals(tmp_path, monkeypatch):
    failed=threading.Event()
    channel=FailureChannel(failed,tmp_path)
    monkeypatch.setenv(ENVIRONMENT,channel.endpoint)
    try:
        notify_failure(tmp_path/'different-run')
        assert not failed.wait(.15)
        endpoint=json.loads(channel.endpoint)
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sender:
            sender.sendto(b'not-the-run-token',('127.0.0.1',endpoint['port']))
        assert not failed.wait(.15)
        notify_failure(tmp_path)
        assert failed.wait(1)
    finally: channel.close()
    assert not channel.thread.is_alive()


def test_nested_run_signal_does_not_notify_outer_supervisor(tmp_path, monkeypatch):
    outer_failed=threading.Event();inner_failed=threading.Event()
    outer=FailureChannel(outer_failed,tmp_path/'outer')
    inner=FailureChannel(inner_failed,tmp_path/'inner')
    monkeypatch.setenv(ENVIRONMENT,inner.endpoint)
    try:
        notify_failure(tmp_path/'inner')
        assert inner_failed.wait(1) and not outer_failed.is_set()
    finally: inner.close();outer.close()
    assert not inner.thread.is_alive() and not outer.thread.is_alive()


def test_invalid_endpoint_keeps_existing_fallbacks(tmp_path,monkeypatch):
    for value in ('invalid','{}','null','[]','{"root":null}'):
        monkeypatch.setenv(ENVIRONMENT,value)
        notify_failure(tmp_path)


def test_channel_setup_failure_never_starts_unmonitored_suite(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from scripts import run_regressions as runner
    def denied(*a): raise PermissionError(13,'private details')
    def unexpected(*a,**k): raise AssertionError('must not start without notification channel')
    monkeypatch.setattr(runner,'FailureChannel',denied)
    monkeypatch.setattr(runner.subprocess,'Popen',unexpected)
    args=SimpleNamespace(diagnostics=str(tmp_path),stack_interval=30,
        pytest_args=[],case_timeout=180,session_timeout=1500)
    assert runner.supervise(args)==3
    text=next(tmp_path.glob('run-*/failure.json')).read_text(encoding='utf-8')
    assert 'notification channel' in text and 'private details' not in text
