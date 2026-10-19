"""Optional pytest collection audit: source, parameters, fixtures and suite ownership."""

import inspect
import json
from pathlib import Path


def group_for(path):
    name = Path(path).name
    groups = {
        'resources': ('dorcha','tuarim','resource','crescendo','pellom'),
        'combat': ('buff','debuff','boss','stat','halo','pattern'),
        'dialogue': ('dialogue',),
        'configuration': ('config','catalog','preset','custom','memo'),
        'capture': ('capture','region','autofind','dpi','window','dwm','tracking'),
        'navigation': ('navigation','setup','tour','layout','interaction','registration','wrapping'),
        'delivery': ('release','updat','windows_ci','test_inventory'),
        'calculator': ('dungeon','calculator'),
    }
    if 'tests/windows/' in str(path).replace('\\','/'):
        return 'windows'
    if name == 'test_windows_ci.py':
        return 'delivery'
    return next((group for group, words in groups.items() if any(word in name for word in words)), 'core')


def pytest_addoption(parser):
    parser.addoption('--test-inventory', help='Write collected cases and fixture identities as JSON')
    parser.addoption('--regression-group', action='append', default=[], help='Select functional groups (repeatable)')


def pytest_collection_modifyitems(config, items):
    rows = []
    chosen, rejected = [], []
    groups = config.getoption('--regression-group')
    for item in items:
        group = group_for(item.path)
        fixtures = {}
        for name in item.fixturenames:
            definitions = item._fixtureinfo.name2fixturedefs.get(name, ())
            if definitions:
                fn = definitions[-1].func
                fixtures[name] = f'{inspect.getsourcefile(fn)}:{fn.__code__.co_firstlineno}'
        fn = item.obj
        rows.append(dict(node=item.nodeid, group=group,
                         source=f'{inspect.getsourcefile(fn)}:{fn.__code__.co_firstlineno}',
                         parameters=repr(getattr(getattr(item, 'callspec', None), 'params', {})),
                         fixtures=fixtures,
                         native=item.get_closest_marker('windows_integration') is not None))
        (chosen if not groups or group in groups else rejected).append(item)
    unknown = set(groups) - {row['group'] for row in rows}
    if unknown:
        import pytest
        raise pytest.UsageError(f'Unknown regression groups: {sorted(unknown)}')
    if rejected:
        config.hook.pytest_deselected(items=rejected)
        items[:] = chosen
    destination = config.getoption('--test-inventory')
    if destination:
        Path(destination).write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf-8')
