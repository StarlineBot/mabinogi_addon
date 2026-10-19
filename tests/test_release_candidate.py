from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from scripts import release_candidate as c
from scripts import release_delivery as d

SHA = 'a'*40
REPO = 'owner/project'
NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root = tmp_path/'source'
    (root/'dist').mkdir(parents=True)
    (root/'dist/mabinogi-addon.exe').write_bytes(bytes(range(256))*5)
    for report in ('unit-results.xml','windows-results.xml'):
        (root/report).write_text('<testsuites><testsuite tests="3" failures="0" errors="0" skipped="1"/></testsuites>',encoding='utf-8')
    notes = root/'src/mabinogi_addon/assets/release_notes.md'
    notes.parent.mkdir(parents=True)
    notes.write_text('## v0.6.0\n\nUser notes\n\n## v0.5.0\nOld notes\n', encoding='utf-8')
    monkeypatch.setattr(c.subprocess,'check_output',lambda *a,**k: SHA)
    monkeypatch.setattr(c,'fingerprint',lambda sha,**kw: 'fingerprint')
    folder = tmp_path/'candidate'
    manifest = c.seal(root,folder,SHA,'0.6.0',123,2,REPO,now=NOW,read_version=lambda p:'0.6.0')
    context = {key:manifest[key] for key in ('source_sha','version','run_id','run_attempt','repository')}
    return root, folder, manifest, context


def test_sealed_bytes_reports_notes_and_version_are_preserved(bundle):
    root, folder, manifest, context = bundle
    assert c.verify_bundle(folder,context,now=NOW) == manifest
    assert (root/'dist/mabinogi-addon.exe').read_bytes() == (folder/'mabinogi-addon.exe').read_bytes()
    assert 'Old notes' not in (folder/'notes.md').read_text(encoding='utf-8')
    assert json.loads((folder/'version.json').read_text(encoding='utf-8'))['sha256'] == c.digest(folder/'mabinogi-addon.exe')


@pytest.mark.parametrize('key,value', [('source_sha','b'*40),('version','0.7.0'),('run_id',124),
                                      ('run_attempt',3),('repository','other/repo')])
def test_different_provenance_cannot_promote(bundle,key,value):
    _,folder,_,context = bundle
    context[key] = value
    with pytest.raises(ValueError,match='mismatch'):
        c.verify_bundle(folder,context,now=NOW)


@pytest.mark.parametrize('name', ['mabinogi-addon.exe','version.json','unit-results.xml','windows-results.xml','notes.md'])
@pytest.mark.parametrize('damage', ['missing','modified'])
def test_missing_or_modified_asset_blocks(bundle,name,damage):
    _,folder,_,context = bundle
    path = folder/name
    if damage == 'missing':
        path.unlink()
    else:
        path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises(ValueError):
        c.verify_bundle(folder,context,now=NOW)


@pytest.mark.parametrize('hours',[24,25])
def test_expired_bundle_blocks(bundle,hours):
    _,folder,_,context = bundle
    with pytest.raises(ValueError,match='expired'):
        c.verify_bundle(folder,context,now=NOW+timedelta(hours=hours))


@pytest.mark.parametrize('xml', ['<testsuites/>','<testsuite tests="1" skipped="1"/>',
                               '<testsuite tests="3" failures="1"/>','<testsuite tests="3" errors="1"/>'])
def test_failed_empty_or_all_skipped_reports_block(tmp_path,xml):
    path = tmp_path/'report.xml'
    path.write_text(xml,encoding='utf-8')
    with pytest.raises(ValueError):
        c.report_passed(path)


@pytest.fixture
def provenance():
    run = dict(id=123,repository=dict(full_name=REPO),head_sha=SHA,run_attempt=2,workflow_id=7,
               path=c.WORKFLOW,head_branch='main',event='workflow_dispatch',status='completed',conclusion='success')
    jobs = [dict(name='validate',conclusion='success',steps=[dict(name=n,conclusion='success') for n in c.REQUIRED])]
    artifact = dict(id=456,name='verified-windows-123-2',expired=False,size_in_bytes=100,
                    workflow_run=dict(id=123,head_sha=SHA),expires_at=(NOW+c.TTL).isoformat())
    return run,jobs,artifact


def test_successful_exact_run_and_artifact(provenance):
    c.check_context(*provenance,7,REPO,SHA,'0.6.0',2,now=NOW)


@pytest.mark.parametrize('field,value', [('head_sha','b'*40),('run_attempt',1),('workflow_id',8),
    ('path','other.yml'),('head_branch','work'),('event','push'),('status','in_progress'),('conclusion','failure')])
def test_wrong_or_failed_run_blocks(provenance,field,value):
    run,jobs,artifact = provenance
    run[field] = value
    with pytest.raises(ValueError):
        c.check_context(run,jobs,artifact,7,REPO,SHA,'0.6.0',2,now=NOW)


@pytest.mark.parametrize('stage',c.REQUIRED)
@pytest.mark.parametrize('outcome',['failure','skipped','cancelled'])
def test_each_required_stage_must_actually_pass(provenance,stage,outcome):
    run,jobs,artifact = provenance
    next(step for step in jobs[0]['steps'] if step['name']==stage)['conclusion'] = outcome
    with pytest.raises(ValueError,match='stage'):
        c.check_context(run,jobs,artifact,7,REPO,SHA,'0.6.0',2,now=NOW)


@pytest.mark.parametrize('field,value',[('expired',True),('name','verified-windows-123-1'),
                                       ('size_in_bytes',0),('expires_at',NOW.isoformat()),
                                       ('workflow_run',dict(id=122,head_sha=SHA))])
def test_invalid_artifact_blocks(provenance,field,value):
    run,jobs,artifact = provenance
    artifact[field] = value
    with pytest.raises(ValueError):
        c.check_context(run,jobs,artifact,7,REPO,SHA,'0.6.0',2,now=NOW)


@pytest.mark.parametrize('existing',[None,b'author custom data\n',b'malformed but preserve'])
def test_public_dialogue_seed_never_replaces_author_file(bundle,tmp_path,existing):
    root,folder,_,_ = bundle
    (root/'packaging').mkdir()
    (root/'packaging/CHANGELOG.md').write_text('Old changelog\n',encoding='utf-8')
    (root/'packaging/releases_README.md').write_text('Header\n<!-- CHANGELOG -->\n',encoding='utf-8')
    (root/'src/mabinogi_addon/assets/dialogues.json').write_bytes(b'initial dialogue')
    public = tmp_path/'pub'
    (public/'data').mkdir(parents=True)
    target = public/'data/dialogues.json'
    if existing is not None:
        target.write_bytes(existing)
    d.prepare_public(root,public,folder,'0.6.0')
    assert target.read_bytes() == (existing if existing is not None else b'initial dialogue')
    assert (public/'version.json').read_bytes() == (folder/'version.json').read_bytes()
    with pytest.raises(ValueError,match='already'):
        d.prepare_public(root,public,folder,'0.6.0')


@pytest.mark.parametrize('corruption',['hash','expired','failed-gate','changed-after-upload','corrupt-upload','missing-upload'])
def test_delivery_failure_never_publishes_or_updates(bundle,tmp_path,monkeypatch,corruption):
    root,folder,manifest,context = bundle
    monkeypatch.chdir(tmp_path)
    Path('verified-run.json').write_text(json.dumps(context),encoding='utf-8')
    monkeypatch.setenv('GH_TOKEN','source-test-token')
    monkeypatch.setenv('RELEASES_TOKEN','public-test-token')
    calls = []
    gates = []

    def gate(*args):
        gates.append(args)
        if corruption == 'failed-gate' or corruption == 'changed-after-upload' and len(gates)>1:
            raise ValueError('validation changed')
        return context

    monkeypatch.setattr(d,'gate',gate)
    original = c.verify_bundle
    monkeypatch.setattr(d,'verify_bundle',lambda f,ctx:original(f,ctx,now=NOW+timedelta(hours=25) if corruption=='expired' else NOW))
    monkeypatch.setattr(d,'prepare_public',lambda *args:None)
    monkeypatch.setattr(d.subprocess,'run',lambda *args,**kw:pytest.fail('public git write before gate'))

    def gh(*args,token):
        calls.append(args)
        if args[0]=='api':
            return '[]'
        if args[:2]==('release','download'):
            dest = Path(args[args.index('--dir')+1])
            for name in ('mabinogi-addon.exe','candidate.json','version.json'):
                if corruption=='missing-upload' and name=='mabinogi-addon.exe':
                    continue
                (dest/name).write_bytes((folder/name).read_bytes())
            if corruption=='corrupt-upload':
                (dest/'mabinogi-addon.exe').write_bytes(b'wrong exe')
        return ''

    monkeypatch.setattr(d,'gh',gh)
    if corruption=='hash':
        (folder/'mabinogi-addon.exe').write_bytes(b'changed')
    with pytest.raises((ValueError,FileNotFoundError)):
        d.promote(root,folder,tmp_path/'pub')
    assert not any(call[:2]==('release','edit') for call in calls)


def test_delivery_download_checks_same_bytes_and_never_rebuilds(bundle,tmp_path,monkeypatch):
    root,folder,_,context = bundle
    monkeypatch.chdir(tmp_path)
    Path('verified-run.json').write_text(json.dumps(context),encoding='utf-8')
    monkeypatch.setenv('GH_TOKEN','source-test-token')
    monkeypatch.setenv('RELEASES_TOKEN','public-test-token')
    monkeypatch.delenv('RELEASE_WEBHOOK_URL',raising=False)
    monkeypatch.setattr(d,'gate',lambda *args:context)
    original = c.verify_bundle
    monkeypatch.setattr(d,'verify_bundle',lambda f,ctx:original(f,ctx,now=NOW))
    monkeypatch.setattr(d,'prepare_public',lambda *args:None)
    events = []

    def gh(*args,token):
        events.append(args)
        if args[0]=='api':
            return '[]'
        if args[:2]==('release','create'):
            assert '--draft' in args
            assert str(folder/'mabinogi-addon.exe') in args
        if args[:2]==('release','download'):
            dest = Path(args[args.index('--dir')+1])
            for name in ('mabinogi-addon.exe','candidate.json','version.json'):
                (dest/name).write_bytes((folder/name).read_bytes())
        return ''

    monkeypatch.setattr(d,'gh',gh)
    monkeypatch.setattr(d.subprocess,'run',lambda args,**kw:events.append(tuple(args)))
    d.promote(root,folder,tmp_path/'pub')
    assert sum(event[:2]==('release','download') for event in events)==2
    assert sum(event[:2]==('release','edit') for event in events)==2
    assert all(event[0] in ('api','release','git') for event in events)
    last_download = max(i for i,e in enumerate(events) if e[:2]==('release','download'))
    assert all(i>last_download for i,e in enumerate(events) if e[:2]==('release','edit'))
    assert (root/'dist/mabinogi-addon.exe').read_bytes()==(folder/'mabinogi-addon.exe').read_bytes()


@pytest.mark.parametrize('changed',['tag','product'])
def test_gate_rejects_wrong_tag_or_product_change(provenance,monkeypatch,changed):
    run,jobs,artifact = provenance
    artifact['expires_at']=(c.utcnow()+c.TTL).isoformat()
    monkeypatch.setenv('GITHUB_REPOSITORY',REPO)
    monkeypatch.setattr(c,'api',lambda path:dict(id=7) if path.endswith('windows.yml') else run)
    monkeypatch.setattr(c,'pages',lambda path,field:jobs if field=='jobs' else [artifact])
    monkeypatch.setattr(c.subprocess,'run',lambda *a,**k:None)
    monkeypatch.setattr(c.subprocess,'check_output',lambda *a,**k:'b'*40 if changed=='tag' else SHA)
    monkeypatch.setattr(c,'fingerprint',lambda sha:sha if changed=='product' else 'same')
    with pytest.raises(ValueError,match='tag|inputs changed'):
        c.gate(REPO,123,2,SHA,'0.6.0')


def test_retention_leaves_only_one_previous_candidate_before_upload(monkeypatch):
    artifacts = [dict(id=i,name=f'verified-windows-{i}-1') for i in (1,2,3)]
    artifacts.append(dict(id=4,name='unrelated-artifact'))
    deleted = []
    monkeypatch.setattr(c,'pages',lambda *a:artifacts)
    monkeypatch.setattr(c,'api',lambda path,method:deleted.append((path,method)))
    c.prune(REPO)
    assert deleted == [(f'repos/{REPO}/actions/artifacts/{i}','DELETE') for i in (2,1)]


def test_fingerprint_includes_qa_dependencies_but_not_documents(monkeypatch):
    entries = [b'100644 blob '+b'a'*40+b'\t'+path for path in
               (b'src/product.py',b'scripts/qa_active_fixture.py',b'docs/qa/report.md',
                b'docs/qa/assets/native/input.png',b'docs/qa/assets/helper/probe.py',
                b'docs/examples/dialogue/sample.json')]
    monkeypatch.setattr(c.subprocess,'check_output',lambda *a,**k:b'\0'.join(entries))
    before=c.fingerprint(SHA)
    entries[2]=entries[2].replace(b'a'*40,b'b'*40)
    assert c.fingerprint(SHA)==before
    entries[1]=entries[1].replace(b'a'*40,b'b'*40)
    assert c.fingerprint(SHA)!=before
    for index in (3,4,5):
        previous = c.fingerprint(SHA)
        entries[index]=entries[index].replace(b'a'*40,b'b'*40)
        assert c.fingerprint(SHA)!=previous


def test_used_tag_cannot_start_candidate_validation(bundle,monkeypatch):
    root,_,_,_ = bundle
    monkeypatch.setattr(c.subprocess,'check_output',lambda *a,**kw:'v0.6.0\n')
    with pytest.raises(ValueError,match='already used'):
        c.preflight(root,SHA,'0.6.0')
    monkeypatch.setattr(c.subprocess,'check_output',lambda *a,**kw:'')
    c.preflight(root,SHA,'0.6.0')


@pytest.mark.parametrize('version',['0.0.0','0.6.1'])
def test_wrong_embedded_exe_version_never_seals(bundle,tmp_path,version):
    root,_,_,_ = bundle
    output=tmp_path/'wrong-candidate'
    with pytest.raises(ValueError,match='version mismatch'):
        c.seal(root,output,SHA,'0.6.0',123,2,REPO,read_version=lambda _:version)
    assert not output.exists()


def test_expanded_payload_limit_is_enforced(bundle,monkeypatch):
    _,folder,manifest,context=bundle
    # Even when every listed file fits exactly, the manifest itself must fit too.
    monkeypatch.setattr(c,'MAX_BYTES',sum(f['size'] for f in manifest['files'].values()))
    with pytest.raises(ValueError,match='oversized'):
        c.verify_bundle(folder,context,now=NOW)
