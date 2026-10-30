"""0.24.0 일회 이관: 기본 디버프와 같은 이름의 사용자 아이콘을 치워 새 기본(게임 원본 16px)을 쓰게 한다."""

import json

import numpy as np

from mabinogi_addon import catalog, config, image_io

DEFAULTS = {"모모", "케라", "슈터스 아이"}


def _icon(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    assert image_io.imwrite(path, np.full((28, 28, 3), value, np.uint8))


def test_same_name_user_icons_move_to_backup_and_custom_ones_stay(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"debuffTracker": {"debuffs": [{"id": "모모", "name": "네잎"}]}}), encoding="utf-8")
    icons = tmp_path / "debuff" / "icon"
    _icon(icons / "모모.png", 10)
    _icon(icons / "슈터스 아이.png", 20)
    _icon(icons / "내가 만든 디버프.png", 30)
    assert config.migrate_default_debuff_icons(cfg, user_dir=icons, default_ids=DEFAULTS)
    assert sorted(p.name for p in icons.glob("*.png")) == ["내가 만든 디버프.png"]
    backup = tmp_path / "debuff" / "icon_backup_0.24.0"
    assert sorted(p.name for p in backup.glob("*.png")) == ["모모.png", "슈터스 아이.png"]
    assert image_io.imread(backup / "모모.png")[0, 0, 0] == 10  # 지우지 않고 그대로 옮김
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["defaultDebuffIconsNativeMigrated"] is True
    assert data["debuffTracker"]["debuffs"] == [{"id": "모모", "name": "네잎"}]  # 이름·설정은 그대로


def test_runs_once(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    icons = tmp_path / "debuff" / "icon"
    assert config.migrate_default_debuff_icons(cfg, user_dir=icons, default_ids=DEFAULTS)  # 폴더 없어도 표시
    _icon(icons / "케라.png", 40)  # 이관 뒤 사용자가 일부러 다시 바꾼 아이콘은 존중
    assert config.migrate_default_debuff_icons(cfg, user_dir=icons, default_ids=DEFAULTS)
    assert (icons / "케라.png").exists()


def test_existing_backup_name_is_not_overwritten(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    icons = tmp_path / "debuff" / "icon"
    backup = tmp_path / "debuff" / "icon_backup_0.24.0"
    _icon(backup / "모모.png", 1)
    _icon(icons / "모모.png", 2)
    assert config.migrate_default_debuff_icons(cfg, user_dir=icons, default_ids=DEFAULTS)
    assert image_io.imread(backup / "모모.png")[0, 0, 0] == 1
    assert image_io.imread(backup / "모모 (2).png")[0, 0, 0] == 2


def test_move_failure_leaves_marker_unset_for_retry(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    icons = tmp_path / "debuff" / "icon"
    _icon(icons / "모모.png", 5)

    def fail(*_args, **_kwargs):
        raise PermissionError("in use")

    monkeypatch.setattr(config.shutil, "move", fail)
    assert config.migrate_default_debuff_icons(cfg, user_dir=icons, default_ids=DEFAULTS) is False
    assert "defaultDebuffIconsNativeMigrated" not in json.loads(cfg.read_text(encoding="utf-8"))
    assert (icons / "모모.png").exists()


def test_unreadable_config_is_left_alone(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text("{broken", encoding="utf-8")
    icons = tmp_path / "debuff" / "icon"
    _icon(icons / "모모.png", 5)
    assert config.migrate_default_debuff_icons(cfg, user_dir=icons, default_ids=DEFAULTS) is False
    assert cfg.read_text(encoding="utf-8") == "{broken" and (icons / "모모.png").exists()


def test_after_migration_catalog_uses_bundled_native_icon(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    icons = tmp_path / "debuff" / "icon"
    _icon(icons / "모모.png", 9)
    before = {b.id: b for b in catalog.load_debuff_catalog(icon_dirs=(catalog.DEFAULT_DEBUFF_ICON_DIR, icons))}
    assert before["모모"].match_icon == icons / "모모.png"
    assert config.migrate_default_debuff_icons(cfg, user_dir=icons)  # 실제 기본 목록(0.30.0 와이어웹 추가로 20종)으로
    after = {b.id: b for b in catalog.load_debuff_catalog(icon_dirs=(catalog.DEFAULT_DEBUFF_ICON_DIR, icons))}
    assert after["모모"].match_icon == catalog.DEFAULT_DEBUFF_ICON_DIR / "모모.png"
    assert after["모모"].display_image is not None
    assert len(catalog.default_debuff_ids()) == 20  # 0.30.0 와이어웹 기본 추가(명세 변경)
