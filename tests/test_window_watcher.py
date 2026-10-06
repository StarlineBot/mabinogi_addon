"""포그라운드 감지 watcher 테스트(플랫폼 독립 부분만)."""

from mabinogi_addon.system.window_watcher import (
    AlwaysActiveWatcher,
    create_window_watcher,
)


def test_always_active_is_active():
    assert AlwaysActiveWatcher().is_active() is True


def test_factory_returns_watcher_with_is_active():
    # 비-Windows(맥/리눅스 CI)에선 AlwaysActiveWatcher가 돌아온다.
    w = create_window_watcher()
    assert hasattr(w, "is_active")
    assert isinstance(w.is_active(), bool)
