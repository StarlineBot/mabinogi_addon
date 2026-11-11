"""설정 동기화(계정 관리 명세 3.3·5절) — 가짜 서버로: 30초 모으기·종료 시 올림, 빼는 값, 해상도, 409 충돌, 새 PC, 비로그인 0회."""
import io
import json
import os
import time
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from account_fakes import test_key, FakeServer, make_token
from mabinogi_addon import account, cloud_sync, config, paths
from mabinogi_addon.ui.account_controller import DEBOUNCE_MS, AccountController

POS_A = {"x": 100, "y": 200}
POS_B = {"x": 900, "y": 50}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class Inline:
    inline = True

    def submit(self, fn, *a):
        from concurrent.futures import Future
        f = Future()
        try:
            f.set_result(fn(*a))
        except Exception as exc:  # noqa: BLE001
            f.set_exception(exc)
        return f

    def shutdown(self, wait=False):
        pass


def _local(**extra):
    raw = {"installId": "pc-1", "nexonApiKey": "SECRET", "optimizationSelection": {"x": 1},
           "general": {"gameExe": "Client.exe", "lastSeenVersion": "0.45.0", "theme": "dark", "firstUse": "done"},
           "autofindV2": {"last": {"buff": {"box": {"x": 1, "y": 2, "w": 3, "h": 4}}}, "use": {"buff": True}, "fixed": ["buff"]},
           "buffTracker": {"captureRegion": {"x": 10, "y": 20, "w": 300, "h": 600}, "pos": dict(POS_A), "scale": 150},
           "statBars": {"bars": {"hp": {"pos": dict(POS_A), "show": True}}}}
    raw.update(extra)
    config._write_local_config(raw)
    return raw


def _controller(server, *, resolution="2560x1440"):
    c = AccountController(client_factory=lambda t: account.Client(t, opener=server.opener), executor=Inline(),
                          resolution_fn=lambda: resolution)
    c._resolution = resolution
    return c


def _login():
    config.save_account_token(make_token())


def test_blob_has_no_excluded_values(app):
    _local()
    _login()
    cloud_sync.save_record(rev=3, hash="x", enabled=True)
    blob, _ = cloud_sync.build_blob(resolution="2560x1440", device="내 PC")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        doc = json.loads(z.read("config.json"))
        meta = json.loads(z.read("sync.json"))
    text = json.dumps(doc, ensure_ascii=False)
    for word in ("installId", "nexonApiKey", "optimizationSelection", "discordAccount", "settingsSync", "gameExe",
                 "lastSeenVersion", '"last"', "firstUse", "SECRET"):
        assert word not in text, word
    assert doc["buffTracker"]["scale"] == 150 and doc["autofindV2"]["use"] == {"buff": True}
    assert meta["resolution"] == "2560x1440" and meta["device"] == "내 PC"


def test_changes_are_collected_30s_then_uploaded_once_and_on_exit(app):
    _local()
    _login()
    server = FakeServer()
    c = _controller(server)
    c.start()  # 서버에 설정 없음(exists=false) → 처음 한 번 올림(If-Match 0)
    assert server.rev == 1 and server.last_query == {"device": cloud_sync.device_name()[:64], "resolution": "2560x1440"}
    assert [h.get("if-match") for m, p, h in server.calls if m == "PUT"] == ["0"]
    server.calls.clear()
    for scale in (120, 130, 140):  # 연달아 바꿈 → 30초 뒤 한 번
        raw = config._read_local_config()
        raw["buffTracker"]["scale"] = scale
        config._write_local_config(raw)
    app.processEvents()
    assert c._debounce.isActive() and c._debounce.interval() == DEBOUNCE_MS == 30_000
    assert [m for m, *_ in server.calls] == []  # 아직 안 보냄
    c._debounce.timeout.emit()
    assert [(m, p) for m, p, _ in server.calls] == [("PUT", "/settings")] and server.rev == 2
    config._write_local_config(config._read_local_config())  # 내용 그대로 → 올리지 않음
    app.processEvents()
    c._debounce.timeout.emit()
    assert server.rev == 2
    raw = config._read_local_config()
    raw["buffTracker"]["scale"] = 175
    config._write_local_config(raw)
    server.calls.clear()
    c.shutdown()  # 끌 때 한 번
    assert [(m, p) for m, p, _ in server.calls] == [("PUT", "/settings")] and server.rev == 3


def test_not_logged_in_makes_zero_requests(app):
    _local()
    server = FakeServer()
    c = _controller(server)
    c.start()
    config._write_local_config({**config._read_local_config(), "x": 1})
    app.processEvents()
    c.upload_now()
    c.shutdown()
    assert server.calls == [] and not c._debounce.isActive()


def _server_with(raw_doc, *, resolution, rev=5):
    server = FakeServer()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("config.json", json.dumps(raw_doc, ensure_ascii=False))
        z.writestr("sync.json", json.dumps({"resolution": resolution, "device": "다른 PC"}))
    server.rev, server.blob = rev, buf.getvalue()
    server.info = {"rev": rev, "updated": time.time() - 86400, "device": "다른 PC", "resolution": resolution}
    return server


def _remote_doc():
    return {"general": {"theme": "light", "gameExe": "Other.exe"},
            "buffTracker": {"captureRegion": {"x": 1, "y": 2, "w": 3, "h": 4}, "pos": dict(POS_B), "scale": 90},
            "statBars": {"bars": {"hp": {"pos": dict(POS_B), "show": False}}},
            "autofindV2": {"fixed": ["boss"], "use": {"buff": False}}}


def test_new_pc_asks_then_load_applies_and_keeps_pc_values(app):
    _local()
    _login()
    server = _server_with(_remote_doc(), resolution="2560x1440")
    c = _controller(server, resolution="2560x1440")
    asked, applied = [], []
    c.ask.connect(lambda info, reason: asked.append(reason))
    c.applied.connect(applied.append)
    c.start()
    assert asked == ["new_pc"] and server.rev == 5  # 묻기 전엔 아무것도 덮지 않음
    c.resolve("load")
    raw = config._read_local_config()
    assert applied == [True]
    assert raw["general"]["theme"] == "light" and raw["buffTracker"]["scale"] == 90
    assert raw["buffTracker"]["pos"] == POS_B and raw["statBars"]["bars"]["hp"]["pos"] == POS_B  # 같은 해상도 → 위치도
    assert raw["general"]["gameExe"] == "Client.exe" and raw["installId"] == "pc-1"  # 이 PC 값 유지
    assert raw["nexonApiKey"] == "SECRET" and raw["general"]["lastSeenVersion"] == "0.45.0"
    assert raw["autofindV2"]["last"]["buff"]["box"] == {"x": 1, "y": 2, "w": 3, "h": 4}
    assert raw["settingsSync"]["rev"] == 5
    c.shutdown(flush=False)


def test_different_resolution_keeps_this_pc_positions(app):
    _local()
    _login()
    server = _server_with(_remote_doc(), resolution="1920x1080")
    c = _controller(server, resolution="2560x1440")
    c.start()
    applied = []
    c.applied.connect(applied.append)
    c.resolve("load")
    raw = config._read_local_config()
    assert applied == [False] and raw["buffTracker"]["scale"] == 90  # 위치가 아닌 값은 따라감
    assert raw["buffTracker"]["pos"] == POS_A and raw["statBars"]["bars"]["hp"]["pos"] == POS_A
    assert raw["buffTracker"]["captureRegion"] == {"x": 10, "y": 20, "w": 300, "h": 600}
    assert raw["statBars"]["bars"]["hp"]["show"] is False
    assert raw["autofindV2"]["fixed"] == ["buff"] and raw["autofindV2"]["use"] == {"buff": False}
    c.shutdown(flush=False)


def test_keep_this_pc_overwrites_server(app):
    _local()
    _login()
    server = _server_with(_remote_doc(), resolution="2560x1440")
    c = _controller(server)
    c.start()
    c.resolve("keep")
    assert server.rev == 6 and json.loads(zipfile.ZipFile(io.BytesIO(server.blob)).read("config.json"))["buffTracker"]["scale"] == 150
    c.shutdown(flush=False)


def test_conflict_409_asks(app):
    _local()
    _login()
    server = FakeServer()
    c = _controller(server)
    c.start()
    assert server.rev == 1
    server.rev = 4  # 다른 PC가 그 사이 올림
    server.info = {"rev": 4, "updated": time.time(), "device": "노트북"}
    raw = config._read_local_config()
    raw["buffTracker"]["scale"] = 111
    config._write_local_config(raw)
    asked = []
    c.ask.connect(lambda info, reason: asked.append((reason, info["rev"], info.get("device"))))
    c.upload_now()
    assert asked == [("conflict", 4, "노트북")]  # 409 본문은 rev뿐 — /settings를 한 번 더 읽어 '마지막 저장 · PC'까지
    c.shutdown(flush=False)


def test_server_newer_and_no_local_change_downloads_silently(app):
    _local()
    _login()
    server = _server_with(_remote_doc(), resolution="2560x1440", rev=7)
    _raw, digest = cloud_sync.local_state()
    cloud_sync.save_record(rev=6, hash=digest)
    c = _controller(server)
    asked, applied = [], []
    c.ask.connect(lambda *a: asked.append(a))
    c.applied.connect(applied.append)
    c.start()
    assert asked == [] and applied == [True] and config._read_local_config()["buffTracker"]["scale"] == 90
    c.shutdown(flush=False)


def test_both_changed_asks(app):
    _local()
    _login()
    server = _server_with(_remote_doc(), resolution="2560x1440", rev=7)
    cloud_sync.save_record(rev=6, hash="예전 지문")
    c = _controller(server)
    asked = []
    c.ask.connect(lambda info, reason: asked.append(reason))
    c.start()
    assert asked == ["both_changed"]
    c.shutdown(flush=False)


def test_too_big_bundle_is_not_sent(app, monkeypatch):
    _local()
    monkeypatch.setattr(cloud_sync, "MAX_BYTES", 10)
    with pytest.raises(ValueError, match="MB"):
        cloud_sync.build_blob(resolution="1x1", device="pc")


def test_merge_keeps_local_only_positions_and_drops_unknown_when_resolution_differs():
    local = {"a": {"pos": dict(POS_A)}, "only_here": {"pos": dict(POS_A)}}
    incoming = {"a": {"pos": dict(POS_B), "n": 1}, "b": {"pos": dict(POS_B)}}
    merged = cloud_sync.merge_incoming(incoming, local, same_resolution=False)
    assert merged["a"] == {"pos": POS_A, "n": 1} and merged["b"] == {}
    assert cloud_sync.merge_incoming(incoming, local, same_resolution=True)["a"]["pos"] == POS_B
    assert paths  # 사용자 폴더는 conftest가 격리


def test_account_box_states(app):
    """설정 › 계정: 비로그인은 로그인 버튼 + 안내 한 줄, 로그인하면 로그아웃 · ☑ 설정 동기화(기본 켬) · '마지막 동기화: n분 전'."""
    from PySide6.QtWidgets import QGroupBox

    from mabinogi_addon.system.window_watcher import create_window_watcher
    from mabinogi_addon.ui.settings_tab import SettingsTab, sync_status_text
    tab = SettingsTab(create_window_watcher())
    try:
        c = AccountController(client_factory=lambda t: None)
        tab.attach_account(c)
        assert [b for b in tab.findChildren(QGroupBox) if b.title() == "계정"]
        assert tab._login_btn.text() == "디스코드로 로그인" and tab._sync_check.isHidden()
        _login()
        tab._refresh_login()
        assert tab._login_btn.text() == "로그아웃" and not tab._sync_check.isHidden() and tab._sync_check.isChecked()
        cloud_sync.save_record(at=time.time() - 180)
        tab._refresh_sync_status()
        assert tab._sync_status.text() == "마지막 동기화: 3분 전"
        tab._sync_check.setChecked(False)
        assert cloud_sync.record(config._read_local_config())["enabled"] is False
        assert sync_status_text(True, False, c) == "설정 동기화 꺼짐 — 이 PC 설정만 써요."
        c.last_error = "서버에 연결하지 못했어요"
        assert sync_status_text(True, True, c).startswith("동기화 못 함")
        c.shutdown(flush=False)
    finally:
        tab.deleteLater()
