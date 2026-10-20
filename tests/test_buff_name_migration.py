"""One-time name migration must preserve raw settings and survive failed atomic writes."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from mabinogi_addon import config
from mabinogi_addon.catalog import DEFAULT_BUFF_NAMES

MARKER = 'defaultBuffNamesKoreanMigrated'


@pytest.fixture
def document():
    return {
        'warnGoneSeeded': True,
        'general': {'windowPos': {'x': -800, 'y': 35}, 'unknown': ['kept']},
        'buffTracker': {
            'captureRegion': {'x': 11, 'y': 22, 'w': 333, 'h': 444},
            'extra': {'preserve': True},
            'buffs': [
                {'id': 'premium_battle', 'name': 'premium_battle', 'hidden': False},
                {'id': 'overture_of_the_battlefield', 'name': 'overture_of_the_battlefield',
                 'showDuration': True, 'hidden': True,
                 'alert': {'enabled': True, 'beforeSec': 19, 'sound': False,
                           'enabled2': True, 'beforeSec2': 3, 'warnGone': False, 'extra': 'keep'},
                 'customIcon': 'data/custom.png', 'unknown': [1, 2]},
                {'id': 'vivace', 'name': '나만의 비바체'},
                {'id': 'march', 'name': 'My march'},
                {'id': 'tuan', 'name': ''},
                {'id': 'sharp', 'name': '상태지원'},
                {'id': 'custom', 'name': 'custom', 'extra': 'kept'},
            ],
        },
        'debuffTracker': {'buffs': [{'id': 'march', 'name': 'march'}]},
        'overlay': {'buff': {'x': 300, 'y': 20, 'locked': True}},
        'unknownRoot': {'items': [3, False, None]},
    }


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def test_only_exact_default_id_names_change_and_raw_fields_survive(tmp_path, document):
    path = tmp_path / 'settings.json'
    save(path, document)
    assert config.migrate_default_buff_names(path)
    expected = deepcopy(document)
    expected[MARKER] = True
    for row in expected['buffTracker']['buffs']:
        if row['id'] in DEFAULT_BUFF_NAMES and row['name'] == row['id']:
            row['name'] = DEFAULT_BUFF_NAMES[row['id']]
    assert json.loads(path.read_text(encoding='utf-8')) == expected
    assert json.loads(path.with_name(path.name + '.bak').read_text(encoding='utf-8')) == document
    assert 'magi' not in [row['id'] for row in expected['buffTracker']['buffs']]


def test_all_fourteen_defaults_and_completion_prevents_later_renaming(tmp_path, monkeypatch):
    path = tmp_path / 'settings.json'
    raw = {'buffTracker': {'buffs': [{'id': key, 'name': key} for key in DEFAULT_BUFF_NAMES]}}
    save(path, raw)
    assert config.migrate_default_buff_names(path)
    data = config._read_local_config(path)
    assert {row['id']: row['name'] for row in data['buffTracker']['buffs']} == DEFAULT_BUFF_NAMES
    data['buffTracker']['buffs'][0]['name'] = 'premium_battle'
    save(path, data)
    original = path.read_bytes()
    monkeypatch.setattr(config, '_write_local_config', lambda *args: pytest.fail('migration ran twice'))
    assert config.migrate_default_buff_names(path)
    assert path.read_bytes() == original


@pytest.mark.parametrize('failure', ['fsync', 'replace'])
def test_failed_write_preserves_source_marker_and_retry(tmp_path, monkeypatch, document, failure):
    path = tmp_path / 'settings.json'
    save(path, document)
    original = path.read_bytes()
    def fail(*args):
        raise PermissionError('injected failure')
    with monkeypatch.context() as patch:
        if failure == 'fsync':
            patch.setattr(config.os, 'fsync', fail)
        else:
            replace = config.os.replace
            def replace_primary(src, dest):
                if Path(dest) == path:
                    fail()
                return replace(src, dest)
            patch.setattr(config.os, 'replace', replace_primary)
        assert not config.migrate_default_buff_names(path)
    assert path.read_bytes() == original
    assert MARKER not in config._read_local_config(path)
    assert config.migrate_default_buff_names(path)
    assert config._read_local_config(path)[MARKER] is True


@pytest.mark.parametrize('broken', [b'{bad', b'\xff\xfe', b'[]', b'null', b''])
def test_recovery_keeps_good_backup_even_if_replace_fails(tmp_path, monkeypatch, document, broken):
    path = tmp_path / 'settings.json'
    backup = path.with_name(path.name + '.bak')
    path.write_bytes(broken)
    save(backup, document)
    good = backup.read_bytes()
    replace = config.os.replace
    def reject_primary(src, dest):
        if Path(dest) == path:
            raise PermissionError('injected failure')
        return replace(src, dest)
    with monkeypatch.context() as patch:
        patch.setattr(config.os, 'replace', reject_primary)
        assert not config.migrate_default_buff_names(path)
    assert path.read_bytes() == broken and backup.read_bytes() == good
    assert config._read_local_config(path) == document
    assert config.migrate_default_buff_names(path)
    assert backup.read_bytes() == good
    assert config._read_local_config(path)['buffTracker']['buffs'][0]['name'] == DEFAULT_BUFF_NAMES['premium_battle']


@pytest.mark.parametrize('broken', [None, b'{bad', b'\xff', b'[]'])
def test_missing_or_unrecoverable_file_is_not_replaced(tmp_path, broken):
    path = tmp_path / 'settings.json'
    if broken is not None:
        path.write_bytes(broken)
    assert not config.migrate_default_buff_names(path)
    assert path.exists() is (broken is not None)
    if broken is not None:
        assert path.read_bytes() == broken


def test_unreadable_document_is_not_marked_or_rewritten(tmp_path, monkeypatch, document):
    path = tmp_path / 'settings.json'
    save(path, document)
    original = path.read_bytes()
    read = Path.read_text
    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError('unreadable')
        return read(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', denied)
    assert not config.migrate_default_buff_names(path)
    assert path.read_bytes() == original


def test_new_user_initialization_and_first_ui_load_then_restart(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from mabinogi_addon.ui.main_window import MainWindow
    from mabinogi_addon.setup_state import initialize_new_user

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QApplication, 'quit', lambda: None)
    initialize_new_user()
    data = config._read_local_config()
    assert all(not value['enabled'] for key, value in data.items())
    data['warnGoneSeeded'] = True
    data['buffTracker']['buffs'] = [
        {'id': 'premium_battle', 'name': 'premium_battle'},
        {'id': 'march', 'name': 'march'},
    ]
    config._write_local_config(data)
    for repeat in range(2):
        window = MainWindow()
        try:
            panel = window.buff_tab
            assert panel._display_name('premium_battle') == DEFAULT_BUFF_NAMES['premium_battle']
            assert panel._display_name('march') == DEFAULT_BUFF_NAMES['march']
            assert panel.anchor_name.text() == DEFAULT_BUFF_NAMES['premium_battle']
            assert config._read_local_config()[MARKER] is True
        finally:
            window._force_quit = True
            window.close()
            window.deleteLater()
            app.processEvents()
