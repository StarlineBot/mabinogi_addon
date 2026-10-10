"""설정 저장의 원자성·손상 복구(전원 차단 대비) + 창 위치 저장."""

from mabinogi_addon import config


def test_atomic_write_keeps_backup(tmp_path):
    p = tmp_path / "cfg.json"
    config._write_local_config({"a": 1}, p)
    assert config._read_local_config(p) == {"a": 1}
    assert not p.with_name("cfg.json.bak").exists()  # 첫 저장엔 백업 없음
    config._write_local_config({"a": 2}, p)
    assert config._read_local_config(p) == {"a": 2}
    assert p.with_name("cfg.json.bak").exists()  # 둘째 저장 → 직전본 백업


def test_recover_from_corrupt_main(tmp_path):
    p = tmp_path / "cfg.json"
    config._write_local_config({"a": 1}, p)
    config._write_local_config({"a": 2}, p)  # .bak = {a:1}, 본 = {a:2}
    p.write_text("{깨진 json", encoding="utf-8")  # 본 파일 손상
    assert config._read_local_config(p) == {"a": 1}  # .bak로 복구


def test_recover_from_empty_main(tmp_path):
    p = tmp_path / "cfg.json"
    config._write_local_config({"a": 1}, p)
    config._write_local_config({"a": 2}, p)
    p.write_text("", encoding="utf-8")  # 빈 파일(쓰다 전원 차단)
    assert config._read_local_config(p) == {"a": 1}


def test_missing_returns_empty(tmp_path):
    assert config._read_local_config(tmp_path / "none.json") == {}


def test_window_pos_roundtrip(tmp_path):
    p = tmp_path / "cfg.json"
    assert config.load_window_pos(p) is None
    config.save_window_pos(123, 456, p)
    assert config.load_window_pos(p) == {"x": 123, "y": 456}
