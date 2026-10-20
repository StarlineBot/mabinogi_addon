from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from scripts import release_candidate as c
from scripts import release_delivery as d
from scripts import release_automation as a

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
    run = dict(id=123,repository=dict(full_name=REPO),head_repository=dict(full_name=REPO),head_sha=SHA,run_attempt=2,workflow_id=7,
               path=c.WORKFLOW,head_branch='main',event='workflow_dispatch',status='completed',conclusion='success')
    jobs = [dict(name='validate',conclusion='success',steps=[dict(name=n,conclusion='success') for n in c.REQUIRED])]
    artifact = dict(id=456,name='verified-windows-123-2',expired=False,size_in_bytes=100,
                    workflow_run=dict(id=123,head_sha=SHA),expires_at=(NOW+c.TTL).isoformat())
    return run,jobs,artifact


def test_successful_exact_run_and_artifact(provenance):
    c.check_context(*provenance,7,REPO,SHA,'0.6.0',2,now=NOW)


@pytest.mark.parametrize('field,value', [('head_sha','b'*40),('run_attempt',1),('workflow_id',8),
    ('path','other.yml'),('head_branch','work'),('event','push'),('event','pull_request'),
    ('head_repository',dict(full_name='fork/project')),('repository',dict(full_name='other/project')),
    ('status','in_progress'),('conclusion','failure'),('conclusion','cancelled')])
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


@pytest.fixture
def automation(bundle, tmp_path, monkeypatch):
    """Drive real prepare -> completed event -> gates -> delivery with fake GitHub IO."""
    import copy
    import zipfile
    root, folder, manifest, context = bundle
    monkeypatch.chdir(root)
    monkeypatch.setenv('GITHUB_REPOSITORY', REPO)
    monkeypatch.setenv('GITHUB_SHA', SHA)
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    monkeypatch.setenv('GITHUB_EVENT_NAME', 'workflow_dispatch')
    monkeypatch.setenv('GH_TOKEN', 'source-test-token')
    monkeypatch.setenv('RELEASES_TOKEN', 'public-test-token')
    monkeypatch.delenv('RELEASE_WEBHOOK_URL', raising=False)
    monkeypatch.setattr(c, 'utcnow', lambda: NOW)
    events, runs, jobs, artifacts, sources = [], {}, {}, {}, {}
    state = dict(tag=False, version='0.6.0', request=None)

    def run_data(run_id, attempt):
        return dict(id=run_id, run_attempt=attempt, head_sha=SHA, workflow_id=7,
                    repository=dict(full_name=REPO), head_repository=dict(full_name=REPO),
                    path=c.WORKFLOW, head_branch='main', event='workflow_dispatch',
                    status='completed', conclusion='success')

    def artifact_data(artifact_id, name, run_id):
        return dict(id=artifact_id, name=name, size_in_bytes=10000, expired=False,
                    expires_at=(NOW+c.TTL).isoformat(), workflow_run=dict(id=run_id, head_sha=SHA))

    def api(path, method='GET', data=None):
        if path.endswith('/actions/workflows/windows.yml'):
            return dict(id=7)
        if '/actions/runs/' in path:
            return runs[int(path.rsplit('/', 1)[1])]
        if path.endswith('/git/refs'):
            events.append(('tag', data))
            c.require(not state['tag'], 'tag already exists')
            state['tag'] = True
            assert data == dict(ref='refs/tags/v0.6.0', sha=SHA)
            return dict()
        if '/git/ref/tags/' in path:
            return dict(ref='refs/tags/v0.6.0', object=dict(type='commit', sha=SHA))
        raise AssertionError(path)

    def pages(path, field):
        if field == 'jobs':
            return jobs[int(path.split('/runs/')[1].split('/')[0])]
        if '/runs/' in path:
            return artifacts[int(path.split('/runs/')[1].split('/')[0])]
        return [item for items in artifacts.values() for item in items]

    def check_output(args, **kwargs):
        assert args[0] == 'git'
        if args[1:3] == ['tag', '--list']:
            return 'v0.6.0\n' if state['tag'] else ''
        return SHA

    def run(args, **kwargs):
        if args[:2] == ['gh', 'api']:
            artifact_id = int(args[2].split('/artifacts/')[1].split('/')[0])
            events.append(('download', artifact_id))
            with zipfile.ZipFile(kwargs['stdout'], 'w') as archive:
                for file in sources[artifact_id].iterdir():
                    archive.write(file, file.name)
        else:
            assert args[0] == 'git', 'tests/builds must never run during promotion'
            events.append(tuple(args))

    def gh(*args, token):
        events.append(tuple(args))
        if args[0] == 'api':
            return '[]'
        if args[:2] == ('release', 'download'):
            dest = Path(args[args.index('--dir')+1])
            for name in ('mabinogi-addon.exe', 'candidate.json', 'version.json'):
                (dest/name).write_bytes((folder/name).read_bytes())
        return ''

    monkeypatch.setattr(c, 'api', api)
    monkeypatch.setattr(c, 'pages', pages)
    monkeypatch.setattr(c.subprocess, 'check_output', check_output)
    monkeypatch.setattr(c.subprocess, 'run', run)
    monkeypatch.setattr(d, 'gh', gh)
    monkeypatch.setattr(d, 'prepare_public', lambda *args: None)

    def prepare(mode='validate-and-publish', candidate_run=''):
        run_id, attempt = (900, 3) if mode == 'publish-existing' else (123, 2)
        runs[123] = run_data(123, 2)
        jobs[123] = [dict(name='validate', conclusion='success',
                          steps=[dict(name=n, conclusion='success') for n in c.REQUIRED])]
        artifacts[123] = [artifact_data(456, 'verified-windows-123-2', 123)]
        sources[456] = folder
        manifest['authorization']['mode'] = 'verify-only' if mode == 'publish-existing' else mode
        (folder/'candidate.json').write_text(json.dumps(manifest), encoding='utf-8')
        runs[run_id] = run_data(run_id, attempt)
        if run_id not in jobs:
            jobs[run_id] = []
        receipt = tmp_path/f'request-{run_id}-{attempt}'
        request = a.prepare(root, receipt, REPO, SHA, '0.6.0', run_id, attempt, mode, candidate_run)
        jobs[run_id].append(dict(name='request', conclusion='success', steps=[
            dict(name=n, conclusion='success') for n in (a.REQUEST_STEP, a.REQUEST_UPLOAD)]))
        artifacts.setdefault(run_id, []).append(artifact_data(789, a.request_name(run_id, attempt), run_id))
        sources[789] = receipt
        state.update(request=request, receipt=receipt, event=dict(action='completed',
                     repository=dict(full_name=REPO), workflow_run=copy.deepcopy(runs[run_id])))
        return request

    return dict(root=root, folder=folder, manifest=manifest, context=context, events=events,
                runs=runs, jobs=jobs, artifacts=artifacts, sources=sources, state=state, prepare=prepare)


@pytest.mark.parametrize('mode', a.MODES)
def test_one_dispatch_completes_same_bytes_or_preserves_verify_only(automation, mode):
    env = automation
    request = env['prepare'](mode)
    assert request['mode'] == mode
    a.complete(env['state']['event'], REPO, env['root'])
    events = env['events']
    edits = [e for e in events if e[:2] == ('release', 'edit')]
    tags = [e for e in events if e[0] == 'tag']
    if mode == 'verify-only':
        assert edits == tags == []
        assert not any(e[0] == 'release' for e in events)
    else:
        assert len(tags) == 1 and len(edits) == 2
        assert env['manifest']['files']['mabinogi-addon.exe']['sha256'] == c.digest(env['folder']/'mabinogi-addon.exe')
        if mode == 'publish-existing':
            assert env['manifest']['authorization']['mode'] == 'verify-only'
            assert request['candidate']['context']['run_attempt'] == 2
            assert request['run_attempt'] == 3
        # Duplicate event: fail closed on the used tag, never create/publish twice.
        with pytest.raises(ValueError, match='already used'):
            a.complete(env['state']['event'], REPO, env['root'])
        assert sum(e[:2] == ('release', 'edit') for e in events) == 2
        assert sum(e[0] == 'tag' for e in events) == 1


@pytest.mark.parametrize('damage', [
    'event-failed', 'event-cancelled', 'event-fork', 'event-pr', 'event-wrong-workflow',
    'live-attempt', 'live-sha', 'request-missing', 'request-job-skipped', 'request-upload-skipped',
    'request-provenance', 'request-expired', 'request-sha', 'request-version', 'request-attempt',
    'request-mode', 'forged-approval', 'candidate-mode', 'candidate-expired', 'candidate-evicted',
    'candidate-corrupt', 'candidate-source', 'inputs-changed', 'checkout-changed', 'tag-collision',
    'native-skipped', 'artifact-attempt',
])
def test_completion_failure_creates_no_tag_or_publication(automation, monkeypatch, damage):
    env = automation
    env['prepare']()
    state = env['state']
    trigger = state['event']['workflow_run']
    request = state['request']
    receipt = state['receipt']/'release-request.json'
    manifest = env['manifest']
    if damage == 'event-failed':
        trigger['conclusion'] = 'failure'
    elif damage == 'event-cancelled':
        trigger['conclusion'] = 'cancelled'
    elif damage == 'event-fork':
        trigger['head_repository']['full_name'] = 'fork/project'
    elif damage == 'event-pr':
        trigger['event'] = 'pull_request'
    elif damage == 'event-wrong-workflow':
        trigger['workflow_id'] = 8
    elif damage == 'live-attempt':
        env['runs'][123]['run_attempt'] = 3
    elif damage == 'live-sha':
        env['runs'][123]['head_sha'] = 'b'*40
    elif damage == 'request-missing':
        env['artifacts'][123].pop()
    elif damage == 'request-job-skipped':
        env['jobs'][123][-1]['conclusion'] = 'skipped'
    elif damage == 'request-upload-skipped':
        env['jobs'][123][-1]['steps'][-1]['conclusion'] = 'skipped'
    elif damage == 'request-provenance':
        env['artifacts'][123][-1]['workflow_run']['id'] = 122
    elif damage == 'request-expired':
        env['artifacts'][123][-1]['expires_at'] = NOW.isoformat()
    elif damage == 'request-sha':
        request['source_sha'] = 'b'*40
    elif damage == 'request-version':
        request['version'] = '0.7.0'
    elif damage == 'request-attempt':
        request['run_attempt'] = 1
    elif damage == 'request-mode':
        request['mode'] = 'arbitrary-publish'
    elif damage == 'forged-approval':
        manifest['authorization']['mode'] = 'verify-only'
    elif damage == 'candidate-mode':
        manifest.pop('authorization')
    elif damage == 'candidate-expired':
        manifest['expires_at'] = NOW.isoformat()
    elif damage == 'candidate-evicted':
        env['artifacts'][123].pop(0)
    elif damage == 'candidate-corrupt':
        (env['folder']/'mabinogi-addon.exe').write_bytes(b'corrupt')
    elif damage == 'candidate-source':
        manifest['source_sha'] = 'b'*40
    elif damage == 'inputs-changed':
        monkeypatch.setattr(c, 'fingerprint', lambda sha, **kw: 'changed' if sha == 'origin/main' else 'fingerprint')
    elif damage == 'checkout-changed':
        monkeypatch.setattr(c, 'fingerprint', lambda sha, **kw: 'changed' if sha == 'HEAD' else 'fingerprint')
    elif damage == 'tag-collision':
        state['tag'] = True
    elif damage == 'native-skipped':
        env['jobs'][123][0]['steps'][1]['conclusion'] = 'skipped'
    elif damage == 'artifact-attempt':
        env['artifacts'][123][0]['name'] = 'verified-windows-123-1'
    receipt.write_text(json.dumps(request), encoding='utf-8')
    (env['folder']/'candidate.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError):
        a.complete(state['event'], REPO, env['root'])
    assert not any(e[0] in ('tag', 'release') for e in env['events'])


@pytest.mark.parametrize('damage', ['evicted', 'expired', 'attempt', 'bytes', 'source'])
def test_selected_existing_candidate_cannot_be_substituted(automation, monkeypatch, damage):
    env = automation
    request = env['prepare']('publish-existing')
    if damage == 'evicted':
        env['artifacts'][123].clear()
    elif damage == 'expired':
        env['artifacts'][123][0]['expired'] = True
    elif damage == 'attempt':
        env['runs'][123]['run_attempt'] = 3
    elif damage == 'bytes':
        # Even structurally valid manifest edits after the selection are rejected.
        env['manifest']['authorization']['mode'] = 'validate-and-publish'
        (env['folder']/'candidate.json').write_text(json.dumps(env['manifest']), encoding='utf-8')
    else:
        request['candidate']['context']['source_sha'] = 'b'*40
        (env['state']['receipt']/'release-request.json').write_text(json.dumps(request), encoding='utf-8')
    with pytest.raises(ValueError):
        a.complete(env['state']['event'], REPO, env['root'])
    assert not any(e[0] in ('tag', 'release') for e in env['events'])


@pytest.mark.parametrize('state', ['none', 'expired', 'different-inputs', 'ambiguous'])
def test_existing_selection_has_no_implicit_rebuild_or_latest_success_fallback(automation, monkeypatch, state):
    import copy
    env = automation
    env['prepare']('verify-only')
    if state == 'none':
        env['artifacts'][123].clear()
    elif state == 'expired':
        env['artifacts'][123][0]['expired'] = True
    elif state == 'different-inputs':
        monkeypatch.setattr(c, 'fingerprint', lambda sha: sha)
    else:
        env['artifacts'][124] = [dict(env['artifacts'][123][0], id=457,
            name='verified-windows-124-2', workflow_run=dict(id=124, head_sha=SHA))]
        env['runs'][124] = dict(env['runs'][123], id=124)
        env['jobs'][124] = env['jobs'][123]
        source = env['root']/'second-candidate'
        source.mkdir()
        for file in env['folder'].iterdir():
            (source/file.name).write_bytes(file.read_bytes())
        manifest = copy.deepcopy(env['manifest'])
        manifest['run_id'] = 124
        (source/'candidate.json').write_text(json.dumps(manifest), encoding='utf-8')
        env['sources'][457] = source
    with pytest.raises(ValueError, match='no unique'):
        # A different SHA can share a fingerprint (plain docs); a different fingerprint cannot.
        a.select_existing(REPO, 'b'*40 if state == 'different-inputs' else SHA, '0.6.0')
    if state == 'ambiguous':
        assert a.select_existing(REPO, SHA, '0.6.0', candidate_run='123')['context']['run_id'] == 123
    assert not any(e[0] in ('tag', 'release') for e in env['events'])


@pytest.mark.parametrize('entry', ['../release-request.json', 'evil.py', 'link', 'extra', 'oversized'])
def test_artifact_zip_never_extracts_untrusted_paths_or_code(tmp_path, monkeypatch, entry):
    import zipfile
    def run(args, stdout, **kwargs):
        with zipfile.ZipFile(stdout, 'w') as z:
            if entry == 'link':
                info = zipfile.ZipInfo('release-request.json')
                info.external_attr = 0o120777 << 16
                z.writestr(info, 'target')
            elif entry == 'extra':
                z.writestr('release-request.json', '{}')
                z.writestr('extra.py', '')
            else:
                name = 'release-request.json' if entry == 'oversized' else entry
                z.writestr(name, b'X'*200 if entry == 'oversized' else b'{}')
    monkeypatch.setattr(c.subprocess, 'run', run)
    with pytest.raises(ValueError):
        a.download(REPO, dict(id=1, expired=False, size_in_bytes=100), tmp_path/'out',
                   {'release-request.json'}, 100)
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('mode', a.MODES)
def test_approval_probe_needs_no_public_token_and_cannot_publish(automation, tmp_path, monkeypatch, mode):
    env = automation
    env['prepare'](mode)
    monkeypatch.delenv('RELEASES_TOKEN')
    monkeypatch.setenv('GITHUB_EVENT_NAME', 'workflow_run')
    event = tmp_path/'event.json'
    event.write_text(json.dumps(env['state']['event']), encoding='utf-8')
    output = tmp_path/'output'
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(event))
    monkeypatch.setenv('GITHUB_OUTPUT', str(output))
    monkeypatch.setattr('sys.argv', ['release_automation', 'authorize'])
    a.main()
    assert output.read_text(encoding='utf-8') == f'publish={str(mode != "verify-only").lower()}\n'
    assert not any(e[0] in ('tag', 'release') for e in env['events'])


@pytest.mark.parametrize('damage', ['mode', 'branch', 'event', 'source', 'unused-candidate-run'])
def test_untrusted_dispatch_does_not_start_work_or_record_approval(automation, monkeypatch, damage):
    env = automation
    mode, candidate_run = 'verify-only', ''
    if damage == 'mode':
        mode = 'publish-anything'
    elif damage == 'branch':
        monkeypatch.setenv('GITHUB_REF', 'refs/heads/other')
    elif damage == 'event':
        monkeypatch.setenv('GITHUB_EVENT_NAME', 'pull_request')
    elif damage == 'source':
        monkeypatch.setenv('GITHUB_SHA', 'b'*40)
    else:
        candidate_run = '123'
    output = env['root']/'bad-request'
    with pytest.raises(ValueError):
        a.prepare(env['root'], output, REPO, SHA, '0.6.0', 123, 2, mode, candidate_run)
    assert not output.exists()
    assert env['events'] == []


@pytest.mark.parametrize('failure', ['permission', 'remote-collision', 'wrong-created-source', 'partial-release'])
def test_tag_or_prior_release_failure_never_publishes(automation, monkeypatch, failure):
    from urllib.error import HTTPError
    env = automation
    env['prepare']()
    original_api = c.api
    original_gh = d.gh
    def api(path, method='GET', data=None):
        if path.endswith('/git/refs') and failure in ('permission', 'remote-collision'):
            # A concurrent external tag create must also fail atomically at the API.
            raise HTTPError('https://api.github.com/test', 403 if failure == 'permission' else 422,
                            'tag creation rejected', {}, None)
        if '/git/ref/tags/' in path and failure == 'wrong-created-source':
            return dict(ref='refs/tags/v0.6.0', object=dict(type='commit', sha='b'*40))
        return original_api(path, method=method, data=data)
    def gh(*args, token):
        if args[0] == 'api' and failure == 'partial-release':
            return '[[{"tag_name":"v0.6.0"}]]'
        return original_gh(*args, token=token)
    monkeypatch.setattr(c, 'api', api)
    monkeypatch.setattr(d, 'gh', gh)
    with pytest.raises((HTTPError, ValueError)):
        a.complete(env['state']['event'], REPO, env['root'])
    assert not any(e[0] == 'release' for e in env['events'])
    assert not any(e[0] == 'tag' for e in env['events']) or failure == 'wrong-created-source'


def _retain_prior_attempt(env, old_first=False):
    from copy import deepcopy
    import shutil
    old = deepcopy(env['artifacts'][123][0])
    old.update(id=457, name='verified-windows-123-1')
    old_folder = env['root'] / 'prior-attempt'
    shutil.copytree(env['folder'], old_folder)
    manifest = deepcopy(env['manifest'])
    manifest['run_attempt'] = 1
    manifest['authorization']['run_attempt'] = 1
    (old_folder / 'candidate.json').write_text(json.dumps(manifest), encoding='utf-8')
    env['sources'][457] = old_folder
    if old_first:
        env['artifacts'][123].insert(0, old)
    else:
        env['artifacts'][123].append(old)


@pytest.mark.parametrize('candidate_run', ['', '123'])
@pytest.mark.parametrize('old_first', [False, True])
def test_latest_valid_attempt_is_selectable_with_retained_prior_attempt(
        automation, candidate_run, old_first):
    env = automation
    env['prepare']('verify-only')
    _retain_prior_attempt(env, old_first)
    try:
        selected = a.select_existing(REPO, SHA, '0.6.0', candidate_run=candidate_run)
    finally:
        assert not any(event[0] in ('tag', 'release') for event in env['events'])
    assert selected['context']['run_id'] == 123
    assert selected['context']['run_attempt'] == 2
    assert selected['context']['artifact_id'] == 456
    assert not any(event[0] in ('tag', 'release') for event in env['events'])


@pytest.mark.parametrize('status,conclusion', [
    ('completed', 'failure'), ('completed', 'cancelled'), ('in_progress', None)])
@pytest.mark.parametrize('latest_artifact', [False, True])
def test_latest_unsuccessful_attempt_never_falls_back_to_retained_success(
        automation, status, conclusion, latest_artifact):
    env = automation
    env['prepare']('verify-only')
    _retain_prior_attempt(env)
    env['runs'][123].update(status=status, conclusion=conclusion)
    if not latest_artifact:
        env['artifacts'][123] = [a for a in env['artifacts'][123] if a['id'] == 457]
    with pytest.raises(ValueError):
        a.select_existing(REPO, SHA, '0.6.0')
    assert not any(event[0] in ('tag', 'release') for event in env['events'])
    assert not any(event == ('download', 457) for event in env['events'])


def test_selection_api_failure_is_not_treated_as_an_old_attempt(automation, monkeypatch):
    env = automation
    env['prepare']('verify-only')
    _retain_prior_attempt(env)
    def unavailable(path):
        raise RuntimeError('GitHub API unavailable')
    monkeypatch.setattr(c, 'api', unavailable)
    with pytest.raises(RuntimeError, match='API unavailable'):
        a.select_existing(REPO, SHA, '0.6.0')
    assert not any(event[0] in ('tag', 'release', 'download') for event in env['events'])
