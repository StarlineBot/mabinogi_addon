"""설정+자산 zip 백업(export_bundle/import_bundle)과 초기화(reset_config) 테스트.

설정 JSON만으론 커스텀 버프 아이콘 같은 '파일 자산'이 빠져 다른 PC(특히 exe)에서
버프 목록·순서·고정이 복원되지 않는다. zip 번들은 설정 + 사용자 데이터 폴더의
자산 파일을 함께 담아 이를 해결한다.
"""

import json
import zipfile

from mabinogi_addon import config


def _make_user_dir(tmp_path):
    user = tmp_path / "userdata"
    (user / "buff" / "icon").mkdir(parents=True)
    (user / "buff" / "image").mkdir(parents=True)
    (user / "buff" / "icon" / "manashield.png").write_bytes(b"ICON")
    (user / "buff" / "image" / "manashield_enable.png").write_bytes(b"IMG")
    return user


def test_export_bundle_contains_config_and_assets(tmp_path):
    cfg = tmp_path / "config.local.json"
    config._write_local_config(
        {"buffTracker": {"buffs": [{"id": "manashield"}]},
         "nexonApiKey": "SECRET"},
        cfg,
    )
    user = _make_user_dir(tmp_path)

    data = config.export_bundle_bytes(cfg, user)
    import io

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        assert "config.json" in names
        assert "userdata/buff/icon/manashield.png" in names
        assert "userdata/buff/image/manashield_enable.png" in names
        exported = json.loads(z.read("config.json").decode("utf-8"))
        assert "nexonApiKey" not in exported  # 비밀값 제외
        assert exported["buffTracker"]["buffs"][0]["id"] == "manashield"


def test_bundle_round_trip_restores_assets(tmp_path):
    # 원본 PC
    cfg_a = tmp_path / "a" / "config.local.json"
    cfg_a.parent.mkdir()
    config._write_local_config({"buffTracker": {"x": 10, "y": 20, "locked": True}}, cfg_a)
    user_a = _make_user_dir(tmp_path / "a")
    bundle = tmp_path / "backup.zip"
    config.export_bundle(bundle, cfg_a, user_a)

    # 대상 PC(빈 상태)
    cfg_b = tmp_path / "b" / "config.local.json"
    cfg_b.parent.mkdir()
    user_b = tmp_path / "b" / "userdata"
    config.import_bundle(bundle, cfg_b, user_b)

    assert (user_b / "buff" / "icon" / "manashield.png").read_bytes() == b"ICON"
    data = config._read_local_config(cfg_b)
    assert data["buffTracker"] == {"x": 10, "y": 20, "locked": True}


def test_import_bundle_accepts_legacy_json(tmp_path):
    src = tmp_path / "old.json"
    src.write_text(json.dumps({"partyKeywords": ["글렌"]}), encoding="utf-8")
    cfg = tmp_path / "config.local.json"
    config.import_bundle(src, cfg, tmp_path / "userdata")
    assert config._read_local_config(cfg)["partyKeywords"] == ["글렌"]


def test_import_bundle_keeps_secrets(tmp_path):
    cfg = tmp_path / "config.local.json"
    config._write_local_config({"nexonApiKey": "KEEP"}, cfg)
    user = _make_user_dir(tmp_path)
    bundle = tmp_path / "b.zip"
    config.export_bundle(bundle, cfg, user)
    config.import_bundle(bundle, cfg, tmp_path / "ud2")
    assert config._read_local_config(cfg)["nexonApiKey"] == "KEEP"


def test_import_bundle_blocks_zip_slip(tmp_path):
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("config.json", "{}")
        z.writestr("userdata/../../evil.png", b"PWN")  # 경로 탈출 시도
    bundle = tmp_path / "evil.zip"
    bundle.write_bytes(buf.getvalue())
    user = tmp_path / "ud"
    config.import_bundle(bundle, tmp_path / "config.local.json", user)
    assert not (tmp_path / "evil.png").exists()  # 폴더 밖으로 안 빠져나감


def test_import_bundle_requires_config(tmp_path):
    import io

    import pytest

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("userdata/x.png", b"X")  # config.json 없음
    bundle = tmp_path / "noconfig.zip"
    bundle.write_bytes(buf.getvalue())
    with pytest.raises(ValueError):
        config.import_bundle(bundle, tmp_path / "config.local.json", tmp_path / "ud")


def test_reset_keeps_secrets_only(tmp_path):
    cfg = tmp_path / "config.local.json"
    config._write_local_config(
        {"nexonApiKey": "KEEP", "inquiryWebhookUrl": "https://h",
         "buffTracker": {"x": 1}, "party": {"keywords": ["a"]}},
        cfg,
    )
    config.reset_config(cfg)
    data = config._read_local_config(cfg)
    assert data == {"nexonApiKey": "KEEP", "inquiryWebhookUrl": "https://h"}
