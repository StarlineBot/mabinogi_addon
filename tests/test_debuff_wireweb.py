"""0.30.0 와이어웹 기본 디버프(2026-10-30 사용자 결정): 창 모드 2546×1410 세 장(고목의 페타크·브론타나스·레넨의 미이르).

아이콘은 1번 장의 디버프 줄 마지막 칸(1180,1183)을 픽셀 그대로 자른 16px(2·3번 장은 1216, 세 장 픽셀 차이 0).
디버프 줄은 x=1018부터 18px 간격. 와이어웹 칸만 와이어웹으로 잡히고, 다른 칸은 와이어웹으로 안 잡힌다(QA: 다른 칸 최고 0.642).
"""
import json
from pathlib import Path

import numpy as np
import pytest

from mabinogi_addon import catalog, config, image_io
from mabinogi_addon.tracker.debuff_engine import DebuffEngine

ROOT = Path(__file__).resolve().parents[1]
WIREWEB = "와이어웹"
ROW_X, ROW_Y, STRIDE = 1018, 1183, 18
# 장면: (파일, 와이어웹 칸 번호 = 줄 마지막 칸)
SCENES = [("2026-10-30_windowed_wireweb_1.png", 9),
          ("2026-10-30_windowed_wireweb_2.png", 11),
          ("2026-10-30_windowed_wireweb_3.png", 11)]


def _frame(name):
    frame = image_io.imread(ROOT / "tests/data" / name)
    assert frame is not None and frame.shape == (1410, 2546, 3)
    return frame


def _entries():
    return {item.id: item for item in catalog.load_debuff_catalog(icon_dirs=(catalog.DEFAULT_DEBUFF_ICON_DIR,))}


def _detected(templates, patch):
    """실제 판정 경로(디바운스 포함)로 0.6초 동안 같은 칸을 넣고 '걸림'으로 숨긴 디버프."""
    runtime = DebuffEngine(templates, list(templates))
    result = None
    for step in range(5):
        result = runtime.tick(patch, now=step * 0.15)
    return set(templates) - {entry.buff_id for entry in result.entries}


def test_wireweb_is_last_default_and_native_crop():
    assert catalog.DEFAULT_DEBUFF_ORDER[-1] == WIREWEB and WIREWEB in catalog.default_debuff_ids()
    assert len(catalog.default_debuff_ids()) == 20
    item = _entries()[WIREWEB]
    icon = image_io.imread(item.match_icon)
    assert icon.shape == (16, 16, 3)
    for name, slot in SCENES:
        x = ROW_X + slot * STRIDE
        assert (_frame(name)[ROW_Y:ROW_Y + 16, x:x + 16] == icon).all()


@pytest.mark.parametrize("name, slot", SCENES)
def test_wireweb_slot_is_wireweb_and_other_slots_are_not(name, slot):
    frame = _frame(name)
    templates = catalog.build_templates(list(_entries().values()))
    wireweb_only = {WIREWEB: templates[WIREWEB]}
    for index in range(slot + 1):
        x = ROW_X + index * STRIDE
        patch = frame[ROW_Y - 2:ROW_Y + 18, x - 2:x + 18]
        if index == slot:
            assert WIREWEB in _detected(wireweb_only, patch)
            assert _detected(templates, patch) == {WIREWEB}  # 다른 기본 디버프로도 안 잡힘
        else:
            assert WIREWEB not in _detected(templates, patch), (name, index)
    # 와이어웹 칸을 뺀 줄 전체에서 와이어웹 최고 점수는 일반 감지 기준(0.68) 아래
    left = frame[ROW_Y - 4:ROW_Y + 20, ROW_X - 4:ROW_X + slot * STRIDE - 1]
    assert DebuffEngine(wireweb_only, [WIREWEB]).best_scores(left)[WIREWEB] < 0.68


def _icon(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    assert image_io.imwrite(path, np.full((16, 16, 3), value, np.uint8))


def test_user_wireweb_icon_moves_once_even_after_024_migration(tmp_path):
    """0.24.0 이관 표시가 이미 있어도 0.30.0 표시로 '와이어웹.png'만 한 번 치운다. 이름·설정은 그대로."""
    cfg = tmp_path / "config.json"
    settings = {"debuffTracker": {"debuffs": [{"id": WIREWEB, "name": "거미줄"}]}}
    cfg.write_text(json.dumps({**settings, "defaultDebuffIconsNativeMigrated": True}), encoding="utf-8")
    icons = tmp_path / "debuff" / "icon"
    _icon(icons / f"{WIREWEB}.png", 7)
    _icon(icons / "모모.png", 8)  # 0.24.0 뒤 사용자가 일부러 바꾼 기본 아이콘은 건드리지 않음
    _icon(icons / "내가 만든 디버프.png", 9)
    assert config.migrate_default_debuff_icons(cfg, user_dir=icons)  # 0.24.0: 표시 있어 다시 안 돎
    assert config.migrate_new_default_debuff_icons(cfg, user_dir=icons)
    assert sorted(p.name for p in icons.glob("*.png")) == ["내가 만든 디버프.png", "모모.png"]
    backup = tmp_path / "debuff" / "icon_backup_0.30.0"
    assert image_io.imread(backup / f"{WIREWEB}.png")[0, 0, 0] == 7
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["defaultDebuffWirewebMigrated"] is True
    assert data["debuffTracker"] == settings["debuffTracker"]
    _icon(icons / f"{WIREWEB}.png", 11)  # 이관 뒤 다시 넣은 것은 존중(한 번만)
    assert config.migrate_new_default_debuff_icons(cfg, user_dir=icons)
    assert (icons / f"{WIREWEB}.png").exists()


def test_wireweb_move_failure_retries_next_run(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"defaultDebuffIconsNativeMigrated": True}), encoding="utf-8")
    icons = tmp_path / "debuff" / "icon"
    _icon(icons / f"{WIREWEB}.png", 7)

    def fail(*_args, **_kwargs):
        raise PermissionError("in use")
    monkeypatch.setattr(config.shutil, "move", fail)
    assert config.migrate_new_default_debuff_icons(cfg, user_dir=icons) is False
    assert "defaultDebuffWirewebMigrated" not in json.loads(cfg.read_text(encoding="utf-8"))
    monkeypatch.undo()
    assert config.migrate_new_default_debuff_icons(cfg, user_dir=icons)
    assert not (icons / f"{WIREWEB}.png").exists()
