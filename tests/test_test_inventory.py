import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_support.inventory import group_for
from scripts.test_audit import audit


@pytest.mark.parametrize('path,group', [('tests/test_dorcha_restart.py','resources'),
    ('tests/test_debuff_auto.py','combat'),('tests/test_custom_autosave.py','configuration'),
    ('tests/test_navigation.py','navigation'),('tests/windows/test_native.py','windows'),
    ('tests/test_release_candidate.py','delivery')])
def test_owners_are_deterministic(path,group):
    assert group_for(path)==group


def test_audit_keeps_different_fixture_boundaries_and_parameters(tmp_path):
    rows = [dict(node='one',source='fixture.py:10',parameters='{}',fixtures={'boundary':'a:10'},group='resources',native=False),
            dict(node='two',source='fixture.py:10',parameters='{}',fixtures={'boundary':'b:10'},group='resources',native=True)]
    inventory=tmp_path/'inventory.json'
    inventory.write_text(json.dumps(rows),encoding='utf-8')
    junit=tmp_path/'junit.xml'
    junit.write_text('<testsuites><testsuite tests="2"><testcase classname="module" time="0.1"/><testcase classname="module" time="0.2"/></testsuite></testsuites>',encoding='utf-8')
    result=audit(inventory,junit)
    assert not result['exact_duplicates']
    assert result['native']==['two']
    rows.append({**rows[0],'node':'duplicate'})
    inventory.write_text(json.dumps(rows),encoding='utf-8')
    assert audit(inventory,junit)['exact_duplicates']==[['one','duplicate']]


def test_unknown_group_is_an_error_and_inventory_covers_all_cases(tmp_path):
    root=Path(__file__).resolve().parents[1]
    dest=tmp_path/'inventory.json'
    args=[sys.executable,'-m','pytest','tests/test_duration.py','--collect-only','-q',f'--test-inventory={dest}']
    result=subprocess.run(args,cwd=root,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    rows=json.loads(dest.read_text(encoding='utf-8'))
    assert rows and all(r['group']=='core' for r in rows)
    result=subprocess.run(args+['--regression-group=does-not-exist'],cwd=root,capture_output=True,text=True,timeout=30)
    assert result.returncode!=0
    assert 'Unknown regression groups' in result.stderr
