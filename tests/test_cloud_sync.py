"""설정 동기화(계정 관리 명세 3.3·5절) — 가짜 서버로: 30초 모으기·종료 시 올림, 빼는 값, 해상도, 409 충돌, 새 PC, 비로그인 0회."""
import io
import json
import os
import time
import zipfile
from pathlib import Path

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
    for word in ("installId", "nexonApiKey", "optimizationSelection", "discordAccount", "settingsSync",
                 "lastSeenVersion", '"last"', "firstUse", "SECRET"):
        assert word not in text, word
    assert doc["buffTracker"]["scale"] == 150 and doc["autofindV2"]["use"] == {"buff": True}
    assert doc["general"]["gameExe"] == "Client.exe"  # 게임창 등록은 따라감(0.46.0, #221)
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
    assert raw["general"]["gameExe"] == "Other.exe"  # 게임창 등록은 받은 값(0.46.0, #221)
    assert raw["installId"] == "pc-1"  # 이 PC 값 유지
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


# ---- QA 866817b ① 로그인 토큰은 설정 내보내기·가져오기(파일·DM 백업)로 옮겨 가지 않는다 ----

_ACCOUNT = ("discordAccount", "discordUser", "settingsSync", "installId")


def _bundle_config(blob: bytes) -> dict:
    return json.loads(zipfile.ZipFile(io.BytesIO(blob)).read("config.json"))


def _logged_in_local():
    _local()
    _login()  # 로그인하면 예전 discordUser는 지워지므로, 남아 있는 경우까지 보려고 뒤에 직접 넣는다
    cloud_sync.save_record(rev=3, hash="이 PC 지문")
    raw = config._read_local_config()
    raw["discordUser"] = {"id": "1", "name": "예전"}
    config._write_local_config(raw)
    assert all(k in raw for k in _ACCOUNT)
    return raw


def test_export_while_logged_in_has_no_token_sync_record_or_install_id(app, tmp_path):
    raw = _logged_in_local()
    token = raw["discordAccount"]["token"]
    path = config.LOCAL_CONFIG_PATH
    assert not any(k in json.loads(config.config_json_for_export(path)) for k in _ACCOUNT)
    blob = config.export_bundle_bytes(path, user_dir=tmp_path / "u")
    dest = tmp_path / "backup.zip"
    config.export_bundle(dest, path=path, user_dir=tmp_path / "u")
    for data in (blob, dest.read_bytes()):
        assert token.encode() not in data and b"pc-1" not in data
        exported = _bundle_config(data)
        assert not any(k in exported for k in _ACCOUNT) and exported["buffTracker"]["scale"] == 150


def test_dm_backup_bundle_has_no_token(app, tmp_path, monkeypatch):
    """DM 백업(릴레이 전송)도 같은 내보내기 길 — 보내는 ZIP에 토큰·동기화 기록·설치 ID가 없다."""
    from mabinogi_addon import settings_sync
    from mabinogi_addon.ui.settings_tab import _ConfigExportThread
    raw = _logged_in_local()
    sent = []
    monkeypatch.setattr(settings_sync, "send_config_backup_file",
                        lambda webhook, uid, bundle, **kw: sent.append(Path(bundle).read_bytes()))
    t = _ConfigExportThread(None, webhook="https://relay.invalid/x", user={"id": "1", "name": "테스터"})
    results = []
    t.done.connect(lambda ok, msg: results.append(ok))
    t.run()
    assert results == [True] and len(sent) == 1
    assert raw["discordAccount"]["token"].encode() not in sent[0]
    assert not any(k in _bundle_config(sent[0]) for k in _ACCOUNT)


@pytest.mark.parametrize("this_pc_logged_in", [True, False])
def test_import_bundle_with_token_keeps_this_pc_account(app, tmp_path, this_pc_logged_in):
    """토큰·동기화 기록·설치 ID가 든 묶음(직접 만든 것)을 가져와도 이 PC 값은 그대로 — 없으면 넣지도 않는다."""
    other = make_token(sub="999888777", name="남의 계정", tier="creator")
    bundle = tmp_path / "other.zip"
    with zipfile.ZipFile(bundle, "w") as z:
        z.writestr("config.json", json.dumps({
            "discordAccount": {"token": other, "checked": time.time()}, "discordUser": {"id": "9", "name": "남"},
            "settingsSync": {"rev": 99, "hash": "남의 지문"}, "installId": "pc-other",
            "buffTracker": {"scale": 77}}, ensure_ascii=False))
    if this_pc_logged_in:
        before = _logged_in_local()
    else:
        _local()
        before = config._read_local_config()
        before.pop("installId")
        config._write_local_config(before)
    config.import_bundle(bundle, path=config.LOCAL_CONFIG_PATH, user_dir=tmp_path / "u")
    after = config._read_local_config()
    assert after["buffTracker"] == {"scale": 77}  # 일반 설정은 들어옴
    for key in _ACCOUNT:
        assert after.get(key) == before.get(key)  # 이 PC 값 유지(없던 것은 계속 없음)
    from mabinogi_addon import feature_access
    assert config.load_account_token() != other and not feature_access.is_creator()
    assert feature_access.is_logged_in() is this_pc_logged_in


# ---- QA 866817b ③ 물음 창을 그냥 닫으면(X·Esc) 서버를 덮지 않는다 ----

def test_closing_ask_window_puts_nothing_and_asks_again_next_start(app):
    _local()
    _login()
    server = _server_with(_remote_doc(), resolution="2560x1440")
    c = _controller(server)
    asked = []
    c.ask.connect(lambda info, reason: asked.append(reason))
    c.start()
    assert asked and server.rev == 5
    c.resolve(None)  # 창 닫음
    raw = config._read_local_config()
    raw["buffTracker"]["scale"] = 123
    config._write_local_config(raw)  # 이번 실행 중 바꿔도
    c.upload_now()
    c._schedule()
    c.shutdown(flush=True)  # 끌 때도
    assert [m for m, p, _ in server.calls if p == "/settings" and m == "PUT"] == []
    assert server.rev == 5
    again = _controller(server)
    asked2 = []
    again.ask.connect(lambda info, reason: asked2.append(reason))
    again.start()
    assert asked2  # 다음 시작 때 다시 물음
    again.shutdown(flush=False)


def test_ask_dialog_x_and_esc_map_to_nothing(app, monkeypatch):
    """메인 창의 물음 창: X·Esc → resolve(None), '이 PC 설정 쓰기'만 'keep'."""
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QMessageBox
    from PySide6.QtTest import QTest
    from mabinogi_addon.ui import main_window

    class Host:
        def __init__(self):
            self.choices, self._closing, self._config_pending_restart = [], False, False
            self._account = self

        def resolve(self, choice):
            self.choices.append(choice)

    def run(action):
        host = Host()

        def act():
            box = next(w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible())
            if action == "esc":
                QTest.keyClick(box, Qt.Key.Key_Escape)
            elif action == "x":
                box.close()
            else:
                next(b for b in box.buttons() if b.text() == action).click()
        QTimer.singleShot(50, act)
        main_window.MainWindow._on_account_ask(host, {"rev": 5, "updated": "2026-11-11T01:02:03Z",
                                                      "device": "노트북"}, "new_pc")
        return host.choices

    monkeypatch.setattr(QMessageBox, "__init__", _parentless(QMessageBox.__init__))
    assert run("esc") == [None]
    assert run("x") == [None]
    assert run("이 PC 설정 쓰기") == ["keep"]
    assert run("불러오기") == ["load"]


def _parentless(init):
    def wrapped(self, *a, **kw):
        init(self)
    return wrapped


# ---- 게임창 등록(gameExe)도 동기화(0.46.0, #221) — 받은 값이 없거나 게임이 아니면 이 PC 값 유지 ----

@pytest.mark.parametrize("incoming,expected", [
    ("client.exe", "client.exe"),            # 받은 값 적용
    (None, "Client.exe"),                    # 받은 설정에 없음 → 이 PC 값 그대로
    ("mabinogi-addon.exe", "Client.exe"),    # 앱 자신 → 무시
    ("chrome.exe", "Client.exe"),            # 브라우저 → 무시
    ("", "Client.exe"),
])
def test_merge_game_exe(incoming, expected):
    local = {"general": {"gameExe": "Client.exe", "theme": "dark"}}
    general = {"theme": "light"} if incoming is None else {"theme": "light", "gameExe": incoming}
    merged = cloud_sync.merge_incoming({"general": general}, local, same_resolution=True)
    assert merged["general"]["gameExe"] == expected and merged["general"]["theme"] == "light"


def test_merge_game_exe_absent_everywhere_stays_absent():
    merged = cloud_sync.merge_incoming({"general": {"gameExe": "chrome.exe"}}, {"general": {}}, same_resolution=True)
    assert "gameExe" not in merged["general"]
    assert "gameExe" not in cloud_sync.merge_incoming({"x": 1}, {}, same_resolution=True).get("general", {})


def test_invalid_game_exe_is_not_uploaded():
    assert "gameExe" not in cloud_sync.strip_for_sync({"general": {"gameExe": "mabinogi-addon.exe"}})["general"]
    assert cloud_sync.strip_for_sync({"general": {"gameExe": "client.exe"}})["general"]["gameExe"] == "client.exe"


# ---- 0.48.0: 한 PC에서도 '설정 불러올까요?' 거짓 물음(QA 997c8a7) ----

def test_stale_ui_write_does_not_roll_back_sync_record(app):
    """화면 쪽 읽기 → (작업 스레드) 기록 rev 6 저장 → 화면 쪽 쓰기 — 기록 rev는 6 그대로."""
    _local()
    cloud_sync.save_record(rev=5, hash="h5")
    stale = config._read_local_config()  # 화면 스레드가 먼저 읽음
    cloud_sync.save_record(rev=6, hash="h6")  # 작업 스레드가 올린 뒤 기록
    stale["buffTracker"]["scale"] = 123
    config._write_local_config(stale)  # 화면 스레드가 옛 내용으로 씀
    raw = config._read_local_config()
    assert raw["settingsSync"]["rev"] == 6 and raw["settingsSync"]["hash"] == "h6"
    assert raw["buffTracker"]["scale"] == 123  # 화면 쪽 변경도 그대로


def test_concurrent_writers_keep_record_and_never_corrupt(app):
    import threading
    _local()
    cloud_sync.save_record(rev=0)
    stop = threading.Event()
    errors = []

    def ui():
        n = 0
        while not stop.is_set():
            raw = config._read_local_config()
            raw.setdefault("misc", {})["n"] = n
            n += 1
            try:
                config._write_local_config(raw)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

    t = threading.Thread(target=ui)
    t.start()
    try:
        for rev in range(1, 60):
            cloud_sync.save_record(rev=rev)
    finally:
        stop.set()
        t.join()
    assert errors == [] and config._read_local_config()["settingsSync"]["rev"] == 59


def test_reset_clears_sync_record(app):
    _local()
    cloud_sync.save_record(rev=7, hash="x")
    config.reset_config()
    assert "settingsSync" not in config._read_local_config()
    config._write_local_config({"a": 1})
    assert "settingsSync" not in config._read_local_config()  # 잊은 기록이 되살아나지 않음


def _same_content_server(rev):
    """이 PC 지금 내용과 똑같은 묶음을 가진 서버(다른 rev)."""
    blob, _ = cloud_sync.build_blob(resolution="2560x1440", device="내 PC")
    server = FakeServer()
    server.rev, server.blob = rev, blob
    server.info = {"rev": rev, "updated": "2026-11-14T01:00:00Z", "device": "내 PC", "resolution": "2560x1440",
                   "size": len(blob)}
    return server


def test_conflict_with_same_server_content_resolves_without_asking(app, caplog):
    import logging
    _local()
    _login()
    caplog.set_level(logging.INFO, logger="mabinogi_addon.account")
    server = _same_content_server(9)
    cloud_sync.save_record(rev=8, hash="이 PC 지문")  # 기록 rev가 옛값으로 되돌아간 상태
    c = _controller(server)
    asked = []
    c.ask.connect(lambda info, reason: asked.append(reason))
    c.started = True
    c.upload_now()
    assert asked == [] and config._read_local_config()["settingsSync"]["rev"] == 9
    assert any("기록 rev만 맞춤" in r.getMessage() and "8" in r.getMessage() and "9" in r.getMessage() for r in caplog.records)
    assert [m for m, p, _ in server.calls if m == "PUT"] == ["PUT"]  # 409 한 번 뒤 다시 올리지 않음
    c.shutdown(flush=False)


def test_both_changed_with_same_content_resolves_and_different_content_asks(app, caplog):
    import logging
    _local()
    _login()
    caplog.set_level(logging.INFO, logger="mabinogi_addon.account")
    server = _same_content_server(9)
    cloud_sync.save_record(rev=8, hash="예전 지문")  # 종료 때 올렸는데 기록을 못 남긴 경우
    c = _controller(server)
    asked = []
    c.ask.connect(lambda info, reason: asked.append(reason))
    c.start()
    assert asked == [] and config._read_local_config()["settingsSync"]["rev"] == 9
    c.shutdown(flush=False)
    raw = config._read_local_config()
    raw["buffTracker"]["scale"] = 77  # 이번엔 내용이 다름
    config._write_local_config(raw)
    server.rev = server.info["rev"] = 10
    c2 = _controller(server)
    c2.ask.connect(lambda info, reason: asked.append(reason))
    c2.start()
    assert asked == ["both_changed"]
    line = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[동기화] 물음")][-1]
    assert "이유=both_changed" in line and "이 PC 기록 rev=9" in line and "서버 rev=10" in line and "서버 PC=내 PC" in line
    c2.shutdown(flush=False)
