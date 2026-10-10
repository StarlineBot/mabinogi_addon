"""서버 선택(파티모집 현황 대상 서버) 저장·조회·워커 전달 테스트.

현황판 상단 콤보로 서버(하프/류트/만돌린/울프)를 바꾸면 그 서버로 조회되고,
설정에 저장돼 내보내기/가져오기로도 복원된다.
"""

import io
import json
import zipfile

from mabinogi_addon import config
from mabinogi_addon.party.client import DEFAULT_SERVER, SERVERS


def test_default_server_is_half(tmp_path):
    cfg = tmp_path / "config.local.json"
    assert config.load_party_server(cfg) == DEFAULT_SERVER == "하프"


def test_save_and_load_server_round_trip(tmp_path):
    cfg = tmp_path / "config.local.json"
    config.save_party_server("류트", cfg)
    assert config.load_party_server(cfg) == "류트"


def test_unknown_server_falls_back_to_default(tmp_path):
    cfg = tmp_path / "config.local.json"
    config.save_party_server("없는서버", cfg)
    assert config.load_party_server(cfg) == DEFAULT_SERVER


def test_server_preserves_other_party_fields(tmp_path):
    cfg = tmp_path / "config.local.json"
    config._write_local_config(
        {"party": {"keywords": ["브리"], "excludeLeaders": ["홍길동"]}}, cfg
    )
    config.save_party_server("울프", cfg)
    data = config._read_local_config(cfg)
    assert data["party"]["server"] == "울프"
    assert data["party"]["keywords"] == ["브리"]
    assert data["party"]["excludeLeaders"] == ["홍길동"]


def test_server_survives_export_import(tmp_path):
    cfg = tmp_path / "config.local.json"
    config.save_party_server("만돌린", cfg)
    data = config.export_bundle_bytes(cfg, tmp_path / "userdata")

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        exported = json.loads(z.read("config.json").decode("utf-8"))
    assert exported["party"]["server"] == "만돌린"

    # 다른 PC(빈 설정)에 가져오면 저장된 서버로 복원된다.
    dest = tmp_path / "other.local.json"
    bundle = tmp_path / "backup.zip"
    config.export_bundle(bundle, cfg, tmp_path / "userdata")
    config.import_bundle(bundle, dest, tmp_path / "userdata_restore")
    assert config.load_party_server(dest) == "만돌린"


def test_worker_fetches_selected_server():
    """PartyWorker가 get_server()가 준 서버로 fetch_horn_bugle를 호출한다."""
    from mabinogi_addon.party import worker as worker_mod

    captured = {}

    def fake_fetch(api_key, server_name=DEFAULT_SERVER, **_kw):
        captured["server"] = server_name
        return []

    orig = worker_mod.fetch_horn_bugle
    worker_mod.fetch_horn_bugle = fake_fetch
    try:
        w = worker_mod.PartyWorker(
            get_api_key=lambda: "K",
            get_keywords=list,
            get_excludes=list,
            get_server=lambda: "류트",
        )
        w._poll_once()
    finally:
        worker_mod.fetch_horn_bugle = orig
    assert captured["server"] == "류트"


def test_all_servers_valid():
    assert "하프" in SERVERS
    for s in ("류트", "만돌린", "울프"):
        assert s in SERVERS
