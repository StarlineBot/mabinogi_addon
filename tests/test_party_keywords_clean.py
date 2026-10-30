"""0.30.4 QA(사용자 제보: 파티 모집 키워드가 없는데 알림 소리): 잘못 저장된 키워드·제외 목록을 읽을 때 정리한다.

[""]·[" "]는 빈 키워드가 모든 모집글에 걸리고, 목록 대신 문자열("레이드")은 글자 하나하나가 키워드가 됐다(화면엔 빈 칩).
"""
import logging

import pytest

from mabinogi_addon import config
from mabinogi_addon.party.alerts import AlertState
from mabinogi_addon.party.service import find_alerts
from test_party_service import _now, _raw

RAW = [_raw("A", 1, "글렌베르나 레이드", 1, 4, 1), _raw("B", 2, "브리레흐 이드", 2, 8, 2)]


def _save(party):
    data = config._read_local_config()
    data["party"] = party
    config._write_local_config(data)


@pytest.mark.parametrize("saved", [[""], [" "], ["", "  ", "\t"], "레이드", None, 42, {"a": 1}])
def test_bad_saved_keywords_read_as_none_and_never_alert(saved):
    _save({"keywords": saved, "excludeLeaders": saved})
    keywords, excludes = config.load_party_lists()
    assert keywords == [] and excludes == []
    assert find_alerts(RAW, keywords, excludes, AlertState(), now=_now()) == []


def test_normal_keywords_are_stripped_and_deduplicated():
    _save({"keywords": [" 글렌 ", "", "글렌", "브리"], "excludeLeaders": ["  B  ", ""]})
    keywords, excludes = config.load_party_lists()
    assert keywords == ["글렌", "브리"] and excludes == ["B"]
    hits = find_alerts(RAW, keywords, excludes, AlertState(), now=_now())
    assert [(kw, r.character_name) for kw, r in hits] == [("글렌", "A")]  # B는 제외 목록


def test_save_cleans_too():
    config.save_party_lists([" 레이드 ", "", " "], ["", " X "])
    assert config._read_local_config()["party"] == {"keywords": ["레이드"], "excludeLeaders": ["X"]}


def test_find_alerts_ignores_blank_keywords_even_if_passed_directly():
    assert find_alerts(RAW, ["", " "], [], AlertState(), now=_now()) == []


def test_alert_logs_keyword(caplog, monkeypatch):
    """알림이 울리면 app.log에 키워드 한 줄(진단용)."""
    from PySide6.QtWidgets import QApplication
    from mabinogi_addon.party import worker as worker_module
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(worker_module, "fetch_horn_bugle", lambda *a: RAW)
    monkeypatch.setattr(worker_module, "find_alerts",
                        lambda raw, kw, ex, state: find_alerts(raw, kw, ex, state, now=_now()))
    worker = worker_module.PartyWorker(lambda: "key", lambda: ["글렌"], lambda: [])
    worker._primed = True  # 첫 폴링(기존 모집 '이미 봄') 뒤
    got = []
    worker.alerted.connect(lambda kw, recruit: got.append(kw))
    with caplog.at_level(logging.INFO):
        worker._poll_once()
    assert got == ["글렌"]
    assert any("파티 모집 알림: 키워드 '글렌'" in r.getMessage() for r in caplog.records)
    worker.deleteLater()
