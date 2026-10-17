import os
from types import SimpleNamespace

import pytest

from mabinogi_addon.system import capture_exclusion as exclusion

AVAILABLE = exclusion.available


@pytest.fixture
def native(monkeypatch):
    state = SimpleNamespace(calls=[], affinity={1: 0, 2: 1, 3: 0x11}, foreign=set(),
                            hidden=set(), outside=set(), failures=set(), flushes=0)

    def owner(hwnd, pointer):
        pointer._obj.value = os.getpid() + (1 if hwnd in state.foreign else 0)
        return 123

    def rectangle(hwnd, pointer):
        if ("rect", hwnd) in state.failures:
            return False
        rect = pointer._obj
        rect.left = 500 if hwnd in state.outside else -20
        rect.top, rect.right, rect.bottom = 0, rect.left + 80, 80
        return True

    def get(hwnd, pointer):
        if ("get", hwnd) in state.failures:
            return False
        pointer._obj.value = state.affinity[hwnd]
        return True

    def set_value(hwnd, value):
        state.calls.append((hwnd, value))
        if ("set", hwnd, value) in state.failures:
            return False
        state.affinity[hwnd] = value
        return True

    def flush():
        state.flushes += 1
        return -1 if "flush" in state.failures else 0

    user = SimpleNamespace(GetWindowThreadProcessId=owner, GetWindowRect=rectangle,
                           IsWindow=lambda hwnd: True,
                           IsWindowVisible=lambda hwnd: hwnd not in state.hidden,
                           GetWindowDisplayAffinity=get, SetWindowDisplayAffinity=set_value)
    monkeypatch.setattr(exclusion, "available", lambda: True)
    monkeypatch.setattr(exclusion, "_api", lambda: (user, SimpleNamespace(DwmFlush=flush)))
    monkeypatch.setattr(exclusion, "_warned", False)
    return state


@pytest.mark.parametrize("raises", [False, True])
def test_capture_restores_original_affinity_in_reverse_order_even_on_error(native, raises):
    original = dict(native.affinity)
    try:
        with exclusion.excluding_windows([1, 2, 3, 1], (-10, 10, 30, 30)):
            assert native.affinity == {1: 0x11, 2: 0x11, 3: 0x11}
            if raises:
                raise OSError("capture failed")
    except OSError:
        assert raises
    assert native.affinity == original
    assert native.calls == [(1, 0x11), (2, 0x11), (2, 1), (1, 0)]
    assert native.flushes == 2


@pytest.mark.parametrize("kind", ["foreign", "hidden", "outside"])
def test_unrelated_windows_are_not_modified(native, kind):
    getattr(native, kind).add(1)
    with exclusion.excluding_windows([1], (0, 0, 10, 10)):
        pass
    assert not native.calls and not native.flushes


@pytest.mark.parametrize("failure", [("rect", 1), ("get", 1), ("set", 1, 0x11), "flush"])
def test_native_failure_does_not_skip_capture_or_leave_other_windows_excluded(native, failure, caplog):
    native.failures.add(failure)
    original = dict(native.affinity)
    captures = []
    for _ in range(3):
        with exclusion.excluding_windows([1, 2], (0, 0, 10, 10)):
            captures.append(1)
    assert captures == [1, 1, 1]
    assert native.affinity == original
    assert len(caplog.records) == 1


def test_changed_owner_is_not_modified_during_restore(native):
    with exclusion.excluding_windows([1], (0, 0, 10, 10)):
        native.foreign.add(1)
    assert native.calls == [(1, 0x11)]


def test_transient_restore_failure_is_retried_without_skipping_other_windows(native, monkeypatch):
    user, _ = exclusion._api()
    original = user.SetWindowDisplayAffinity
    failures = []

    def fail_once(hwnd, value):
        if hwnd == 2 and value == 1 and not failures:
            failures.append((hwnd, value))
            return False
        return original(hwnd, value)

    monkeypatch.setattr(user, "SetWindowDisplayAffinity", fail_once)
    with exclusion.excluding_windows([1, 2], (0, 0, 10, 10)):
        pass
    assert failures == [(2, 1)]
    assert native.affinity == {1: 0, 2: 1, 3: 0x11}


def test_permanent_restore_failure_is_bounded_reported_and_does_not_skip_other_windows(native, caplog):
    native.failures.add(("set", 2, 1))
    with exclusion.excluding_windows([1, 2], (0, 0, 10, 10)) as pending:
        pass
    assert native.calls.count((2, 1)) == 3
    assert native.affinity[1] == 0
    assert pending == [(2, 1)]
    assert len(caplog.records) == 1
    native.failures.clear()
    assert exclusion.restore_window(*pending[0])
    assert native.affinity[2] == 1


def test_missing_native_library_does_not_abort_capture(monkeypatch, caplog):
    monkeypatch.setattr(exclusion, "available", lambda: True)
    monkeypatch.setattr(exclusion, "_warned", False)

    def missing():
        raise OSError("DWM unavailable")

    monkeypatch.setattr(exclusion, "_api", missing)
    with exclusion.excluding_windows([1], (0, 0, 10, 10)):
        pass
    assert len(caplog.records) == 1


@pytest.mark.parametrize("exists", [False, True])
def test_failed_owner_query_is_not_mistaken_for_a_destroyed_window(native, monkeypatch, exists):
    user, _ = exclusion._api()
    original = user.GetWindowThreadProcessId
    with exclusion.excluding_windows([1], (0, 0, 10, 10)) as pending:
        monkeypatch.setattr(user, "GetWindowThreadProcessId", lambda *args: 0)
        monkeypatch.setattr(user, "IsWindow", lambda hwnd: exists)
    assert pending == ([(1, 0)] if exists else [])
    if exists:
        monkeypatch.setattr(user, "GetWindowThreadProcessId", original)
        assert exclusion.restore_window(*pending[0])
        assert native.affinity[1] == 0


def test_unavailable_platform_does_not_initialize_native_api(monkeypatch):
    monkeypatch.setattr(exclusion, "available", lambda: False)
    monkeypatch.setattr(exclusion, "_api", lambda: pytest.fail("unsupported platform called Windows API"))
    with exclusion.excluding_windows([1], (0, 0, 10, 10)):
        pass


@pytest.mark.parametrize("platform,build,expected", [("linux", 0, False), ("win32", 19040, False),
                                                    ("win32", 19041, True), ("win32", 26100, True)])
def test_old_windows_never_uses_black_rectangle_fallback(monkeypatch, platform, build, expected):
    monkeypatch.setattr(exclusion, "sys", SimpleNamespace(platform=platform,
                                                        getwindowsversion=lambda: SimpleNamespace(
                                                            platform_version=(10, 0, build))))
    assert AVAILABLE() is expected


def test_manifest_compatibility_version_does_not_disable_supported_windows(monkeypatch):
    version = SimpleNamespace(build=9200, platform_version=(10, 0, 26100))
    monkeypatch.setattr(exclusion, "sys", SimpleNamespace(platform="win32", getwindowsversion=lambda: version))
    assert AVAILABLE()
