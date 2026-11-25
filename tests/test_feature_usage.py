"""사용 기능 보고 featureUsage(docs/account-management-spec.md 3.4.2, 사용자 결정 11-18 B안).

봇 '켠 기능'이 스위치 없는 기능(버프·디버프·보스 패턴·1분 헤일로)을 못 보던 것 — 앱이 기능별 마지막 동작 날짜를 적는다."""
import json

import pytest
from test_navigation import window  # noqa: F401  (픽스처)

from mabinogi_addon import cloud_sync, config, feature_usage


class Store:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.saves = []

    def load(self):
        return dict(self.data)

    def save(self, updates):
        self.saves.append(dict(updates))
        self.data.update(updates)


def _recorder(store, day):
    return feature_usage.Recorder(store.load, store.save, today=lambda: day["d"])


# ---- 기록 규칙(순수) ----
def test_writes_once_per_key_per_day():
    store, day = Store(), {"d": "2026-11-18"}
    r = _recorder(store, day)
    assert r.observe({"buff", "boss"}, game_running=True, paused=False) == ["boss", "buff"]
    for _ in range(50):  # 같은 날 계속 동작 — 다시 쓰지 않음(동기화 30초 모으기를 깨우지 않게)
        assert r.observe({"buff", "boss"}, game_running=True, paused=False) == []
    assert r.observe({"buff", "halo"}, game_running=True, paused=False) == ["halo"]  # 그날 처음인 키만
    day["d"] = "2026-11-19"
    assert r.observe({"buff"}, game_running=True, paused=False) == ["buff"]  # 다음 날 다시 한 번
    assert store.saves == [{"boss": "2026-11-18", "buff": "2026-11-18"}, {"halo": "2026-11-18"},
                           {"buff": "2026-11-19"}]


def test_already_recorded_today_on_disk_is_not_rewritten():
    store = Store({"buff": "2026-11-18", "old": "x"})
    r = _recorder(store, {"d": "2026-11-18"})
    assert r.observe({"buff"}, game_running=True, paused=False) == []
    assert store.saves == []


@pytest.mark.parametrize("running,paused", [(False, False), (True, True), (False, True)])
def test_no_write_when_game_off_or_paused(running, paused):
    store = Store()
    r = _recorder(store, {"d": "2026-11-18"})
    assert r.observe(set(feature_usage.KEYS), game_running=running, paused=paused) == []
    assert store.saves == []


def test_unknown_keys_ignored_and_failed_save_retried():
    store, calls = Store(), {"n": 0}

    def flaky(updates):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk")
        store.save(updates)
    r = feature_usage.Recorder(store.load, flaky, today=lambda: "2026-11-18")
    with pytest.raises(OSError):
        r.observe({"buff", "autofindV2"}, game_running=True, paused=False)
    assert r.observe({"buff", "autofindV2"}, game_running=True, paused=False) == ["buff"]  # 실패는 기억 안 함 → 다시
    assert store.data == {"buff": "2026-11-18"}


def test_keys_match_spec_table():
    assert set(feature_usage.KEYS) == {"buff", "debuff", "boss", "halo", "tuarim", "dorcha", "stat_bars", "skillbar",
                                       "custom", "cooldown", "boss_bar", "fps", "opt", "cursor", "blackbox", "alarm",
                                       "keywords", "pet", "character_voice"}   # 11-25 캐릭터 두 줄


# ---- 저장·동기화·가져오기 ----
def test_config_save_merges_and_load_cleans():
    config.save_feature_usage({"buff": "2026-11-18"})
    config.save_feature_usage({"boss": "2026-11-18"})
    raw = config._read_local_config()
    raw["featureUsage"]["bad"] = "2026-11-18"
    raw["featureUsage"]["halo"] = 3
    config._write_local_config(raw)
    assert config.load_feature_usage() == {"buff": "2026-11-18", "boss": "2026-11-18"}


def test_feature_usage_is_in_sync_bundle_and_export():
    config.save_feature_usage({"buff": "2026-11-18"})
    assert cloud_sync.strip_for_sync(config._read_local_config())["featureUsage"] == {"buff": "2026-11-18"}
    assert "featureUsage" not in config._LOCAL_ONLY_KEYS
    assert json.loads(config.config_json_for_export())["featureUsage"] == {"buff": "2026-11-18"}


@pytest.mark.parametrize("same_resolution", [True, False])
def test_sync_receive_keeps_this_pc_usage(same_resolution):
    local = {"featureUsage": {"buff": "2026-11-18"}, "memo": {"text": "a"}}
    incoming = {"featureUsage": {"buff": "2026-11-01", "boss": "2026-11-17"}, "memo": {"text": "b"}}
    merged = cloud_sync.merge_incoming(incoming, local, same_resolution=same_resolution)
    assert merged["featureUsage"] == {"buff": "2026-11-18"} and merged["memo"] == {"text": "b"}
    merged = cloud_sync.merge_incoming(incoming, {"memo": {}}, same_resolution=same_resolution)
    assert "featureUsage" not in merged  # 이 PC에 없으면 받은 값도 넣지 않음


def test_file_import_keeps_this_pc_usage(tmp_path):
    config.save_feature_usage({"buff": "2026-11-18"})
    src = tmp_path / "in.json"
    src.write_text(json.dumps({"featureUsage": {"buff": "2026-10-01", "boss": "2026-10-01"},
                               "memo": {"text": "가져옴"}}, ensure_ascii=False), encoding="utf-8")
    config.import_config(src)
    raw = config._read_local_config()
    assert raw["featureUsage"] == {"buff": "2026-11-18"} and raw["memo"] == {"text": "가져옴"}


# ---- 메인 창: 동작 판단 + 기록 시점 ----
def test_window_records_only_while_game_runs_and_not_paused(window, monkeypatch):  # noqa: F811
    w, _ = window
    monkeypatch.setattr(w, "_feature_usage_active", lambda: {"buff", "keywords"})
    w._usage = feature_usage.Recorder(config.load_feature_usage, config.save_feature_usage, today=lambda: "2026-11-18")
    w._game_session.identity = None  # 게임 꺼짐(프로세스 없음 + 게임 창이 앞에 없음)
    monkeypatch.setattr(w._watcher, "is_game_active", lambda: False)
    assert w._note_feature_usage(now=100.0) == [] and config.load_feature_usage() == {}
    w._game_session.identity = (1234, 1.0)
    w._paused = True
    assert w._note_feature_usage(now=200.0) == [] and config.load_feature_usage() == {}
    w._paused = False
    assert w._note_feature_usage(now=300.0) == ["buff", "keywords"]
    assert w._note_feature_usage(now=301.0) == []  # 5초 간격
    assert w._note_feature_usage(now=400.0) == []  # 같은 날 다시 안 씀
    assert config.load_feature_usage() == {"buff": "2026-11-18", "keywords": "2026-11-18"}


@pytest.mark.parametrize("identity,foreground", [
    (None, True),          # 게임창 미등록 — 프로세스는 못 잡지만 창 판정(제목 폴백)으로 게임이 앞에 있음(QA 11-19)
    ((1234, 1.0), False),  # 등록 사용자 — 게임이 뒤에 있어도 프로세스가 있으면 기록(기존 동작)
    ((1234, 1.0), True),
])
def test_records_without_registered_game_exe(window, monkeypatch, identity, foreground):  # noqa: F811
    w, _ = window
    monkeypatch.setattr(w, "_feature_usage_active", lambda: {"buff"})
    monkeypatch.setattr(w._watcher, "is_game_active", lambda: foreground)
    w._usage = feature_usage.Recorder(config.load_feature_usage, config.save_feature_usage, today=lambda: "2026-11-19")
    w._game_session.identity = identity
    assert w._note_feature_usage(now=100.0) == ["buff"]
    assert config.load_feature_usage() == {"buff": "2026-11-19"}
    w._usage = feature_usage.Recorder(config.load_feature_usage, lambda u: pytest.fail("일시정지 중 기록"),
                                      today=lambda: "2026-11-20")
    w._paused = True  # 미등록이어도 일시정지면 안 씀
    assert w._note_feature_usage(now=200.0) == []
    w._paused = False


class _Count:
    def __init__(self, n):
        self.item_count = n


# 바꾼 값은 테스트 안에서 되돌린다(monkeypatch.context) — 컨트롤러가 가짜인 채로 창을 닫으면 stop()이 실패해
# 다음 테스트 창까지 깨진다(11-18 QA: 배포 검사에서 release_notes_trigger 닫기 오류·세그폴트).
def test_window_active_set_reads_feature_state(window, monkeypatch):  # noqa: F811
    w, _ = window
    assert "buff" not in w._feature_usage_active()
    with monkeypatch.context() as mp:
        mp.setattr(w, "buff_controller", _Count(2))
        mp.setattr(w.party_tab, "_keywords", ["브리레흐"])
        mp.setattr(w.boss_tab, "_cur_boss", "glas")
        w.alarm_tab.enable.setChecked(True)
        from mabinogi_addon import alarm as alarm_model
        assert "alarm" not in w._feature_usage_active()  # 켬 + 알람 0개 → 아님
        mp.setattr(w.alarm_tab.clock, "alarms", [alarm_model.new_timer(5, 0.0, name="t")])
        active = w._feature_usage_active()
        assert {"buff", "keywords", "boss", "alarm"} <= active
        assert "autofindV2" not in active and active <= set(feature_usage.KEYS)
        w.alarm_tab.enable.setChecked(False)
        assert "alarm" not in w._feature_usage_active()


def test_window_active_check_failure_skips_only_that_key(window, monkeypatch):  # noqa: F811
    w, _ = window
    with monkeypatch.context() as mp:
        mp.setattr(w.party_tab, "_keywords", ["x"])
        mp.setattr(w, "buff_controller", object())  # item_count 없음 → 예외 → buff만 빠짐
        assert "keywords" in w._feature_usage_active()


# ---- 11-25 캐릭터 사용 기록(기획 — 명세 3.4.2 끝 두 줄) ----
def test_character_keys_are_known_and_in_bundle():
    assert {"pet", "character_voice"} <= set(feature_usage.KEYS)
    assert feature_usage.clean({"pet": "2026-11-25", "character_voice": "2026-11-25"}) == {
        "pet": "2026-11-25", "character_voice": "2026-11-25"}


def test_window_records_pet_and_character_voice_once_a_day(window, monkeypatch):  # noqa: F811
    from pathlib import Path

    from mabinogi_addon.ui import character_controller as cc
    from mabinogi_addon.ui import notifier

    w, _ = window
    tools = w.character_tools
    with monkeypatch.context() as mp:
        # 펫: 켬 + 창 보임일 때만
        assert "pet" not in w._feature_usage_active()
        mp.setattr(config, "load_pet_on", lambda *a, **k: True)
        assert "pet" not in w._feature_usage_active()            # 켰지만 창 없음(숨김)

        class _Win:
            visible = False

            def isVisible(self):  # noqa: N802
                return self.visible

            def stop(self):
                pass

            def deleteLater(self):  # noqa: N802
                pass
        win = _Win()
        mp.setattr(tools, "window", win)
        assert "pet" not in w._feature_usage_active()            # 창이 숨음
        win.visible = True
        assert "pet" in w._feature_usage_active()
        mp.setattr(config, "load_pet_on", lambda *a, **k: False)
        assert "pet" not in w._feature_usage_active()            # 스위치 끔
        mp.setattr(tools, "window", None)
        # 캐릭터 목소리: 기본 목소리면 알림이 울려도 안 적음
        mp.setattr(cc, "today", lambda now=None: "2026-11-25")
        mp.setattr(config, "load_voice_pack", lambda *a, **k: "")
        notifier._announce("buff1", Path("sounds/기본/a.mp3"))
        assert "character_voice" not in w._feature_usage_active()
        mp.setattr(config, "load_voice_pack", lambda *a, **k: "조용한 여성")
        assert "character_voice" not in w._feature_usage_active()   # 아직 안 울림
        notifier._announce("preview", Path("sounds/조용한 여성/인사.mp3"))
        assert "character_voice" not in w._feature_usage_active()   # 미리듣기는 알림 아님
        notifier._announce("buff1", Path("sounds/조용한 여성/a.mp3"))
        assert "character_voice" in w._feature_usage_active()
        mp.setattr(cc, "today", lambda now=None: "2026-11-26")
        assert "character_voice" not in w._feature_usage_active()   # 다음 날은 다시 울려야
        mp.setattr(cc, "today", lambda now=None: "2026-11-25")
        # 하루 한 번 기록(Recorder 규칙 그대로)
        mp.setattr(config, "load_pet_on", lambda *a, **k: True)
        mp.setattr(tools, "window", win)
        w._usage = feature_usage.Recorder(config.load_feature_usage, config.save_feature_usage, today=lambda: "2026-11-25")
        w._game_session.identity = (1234, 1.0)
        assert {"pet", "character_voice"} <= set(w._note_feature_usage(now=100.0))
        assert "pet" not in w._note_feature_usage(now=200.0)
        usage = config.load_feature_usage()
        assert usage["pet"] == "2026-11-25" and usage["character_voice"] == "2026-11-25"
        mp.setattr(tools, "window", None)
