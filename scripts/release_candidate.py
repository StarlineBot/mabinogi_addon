"""Seal and verify immutable Windows candidates. No publication in this module."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request
import xml.etree.ElementTree as ET

MAX_BYTES = 200 * 1024 * 1024
TTL = timedelta(days=1)
PROFILE = 'linux-regression-windows-smoke-v1'
REQUIRED_JOBS = {
    'regression': ('Isolated regression', 'Verify clean regression checkout', 'Store regression report'),
    'validate': ('Fetch regression report', 'Windows startup smoke',
                 'Verify clean checkout after tests', 'Verify exe build',
                 'Seal verified candidate', 'Store verified candidate'),
}
REQUIRED = tuple(stage for stages in REQUIRED_JOBS.values() for stage in stages)
WORKFLOW = '.github/workflows/windows.yml'
PUBLIC_REPO = 'StarlineBot/mabinogi_addon-releases'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def utcnow():
    return datetime.now(timezone.utc)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def identity(sha, version):
    require(bool(re.fullmatch(r'[0-9a-f]{40}', sha)), 'complete source SHA required')
    require(bool(re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', version)), 'X.Y.Z version required')
    require(version != '0.0.0', 'development version cannot be promoted')


def fingerprint(sha, root=None):
    # Documentation can advance after QA; build/runtime/security/test inputs cannot.
    raw = subprocess.check_output(['git','ls-tree','-rz','--full-tree',sha],cwd=root)
    selected = []
    for entry in raw.split(b'\0'):
        if not entry:
            continue
        path = entry.split(b'\t',1)[1].decode('utf-8')
        if (path.startswith(('src/','packaging/','.github/workflows/','tests/','test_support/',
                             'docs/qa/assets/','docs/examples/'))
                or path.startswith('docs/') and path.endswith('.py')
                or path in ('pyproject.toml','uv.lock','pytest.ini')
                or path.startswith('scripts/')):
            selected.append(entry)
    require(bool(selected), 'source fingerprint is empty')
    return hashlib.sha256(b'\0'.join(selected)).hexdigest()


def report_passed(path):
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == 'testsuite' else list(root.iter('testsuite'))
    require(bool(suites), 'missing JUnit test suites')
    require(sum(int(s.get('tests','0')) - int(s.get('skipped','0')) for s in suites) > 0,
            'no executed tests')
    require(all(int(s.get('failures','0')) == int(s.get('errors','0')) == 0 for s in suites),
            'tests did not pass')


def exe_version(path):
    import win32api
    info = win32api.GetFileVersionInfo(str(path), '\\')
    ms,ls = info['FileVersionMS'],info['FileVersionLS']
    require(ls & 65535 == 0, 'unexpected fourth exe version component')
    return f'{ms >> 16}.{ms & 65535}.{ls >> 16}'


def notes_for(root, version):
    text = (root/'src/mabinogi_addon/assets/release_notes.md').read_text(encoding='utf-8')
    sections = re.split(r'^## v',text,flags=re.MULTILINE)
    require(len(sections) > 1 and sections[1].splitlines()[0] == version,
            'top bundled notes must match candidate version')
    return '## v' + sections[1]


def preflight(root, sha, version):
    identity(sha, version)
    notes_for(root, version)
    # Reserve the version only after validation and explicit publication approval.
    tags = subprocess.check_output(['git','tag','--list',f'v{version}'],cwd=root,text=True)
    require(not tags.strip(), 'version tag already used; select an unused version')


def seal(root, output, sha, version, run_id, attempt, repository, now=None, read_version=exe_version,
         mode="verify-only"):
    identity(sha,version)
    require(mode in ("verify-only", "validate-and-publish"), "invalid validation mode")
    require(run_id > 0 and attempt > 0, 'invalid run identity')
    require(subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip() == sha,
            'checkout/source mismatch')
    for report in ('unit-results.xml','windows-results.xml'):
        report_passed(root/report)
    exe = root/'dist/mabinogi-addon.exe'
    require(exe.is_file() and 0 < exe.stat().st_size <= MAX_BYTES, 'exe missing or oversized')
    require(read_version(exe) == version, 'exe resource version mismatch')
    require(not output.exists(), 'candidate output already exists')
    output.mkdir(parents=True)
    shutil.copyfile(exe, output/exe.name)
    for report in ('unit-results.xml','windows-results.xml'):
        shutil.copyfile(root/report,output/report)
    (output/'notes.md').write_text(notes_for(root,version),encoding='utf-8')
    update = dict(version=version, url=f'https://github.com/{PUBLIC_REPO}/releases/download/v{version}/{exe.name}',
                  sha256=digest(exe),size=exe.stat().st_size)
    (output/'version.json').write_text(json.dumps(update,indent=2)+'\n',encoding='utf-8')
    now = now or utcnow()
    manifest = dict(schema=2,validation_profile=PROFILE,
        source_sha=sha,source_fingerprint=fingerprint(sha,root=root),version=version,
        run_id=run_id,run_attempt=attempt,repository=repository,workflow=WORKFLOW,
        authorization=dict(mode=mode, source_sha=sha, version=version, run_id=run_id,
                           run_attempt=attempt, repository=repository),
        created_at=now.isoformat(),expires_at=(now+TTL).isoformat(),exe_version=version,
        files={p.name:dict(sha256=digest(p),size=p.stat().st_size) for p in sorted(output.iterdir())})
    require(sum(f['size'] for f in manifest['files'].values()) <= MAX_BYTES,'candidate oversized')
    (output/'candidate.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    require(sum(p.stat().st_size for p in output.iterdir()) <= MAX_BYTES,'candidate oversized')
    return manifest


def api(path, method='GET', data=None):
    token = os.environ['GH_TOKEN']
    request = urllib.request.Request('https://api.github.com/'+path,
        data=None if data is None else json.dumps(data).encode('utf-8'),
        headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
                 'X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json'},method=method)
    with urllib.request.urlopen(request,timeout=30) as response:
        return json.loads(response.read().decode('utf-8')) if response.status != 204 else None


def pages(path, field):
    result = []
    for page in range(1,101):
        reply = api(path+('?' if '?' not in path else '&')+f'per_page=100&page={page}')
        items = reply[field]
        result.extend(items)
        if len(items) < 100:
            return result
    raise ValueError('API pagination limit exceeded')


def check_dispatch(run, workflow_id, repository, sha, attempt):
    require(run.get('repository',{}).get('full_name') == repository, 'run repository mismatch')
    require(run.get('head_repository',{}).get('full_name') == repository, 'fork source rejected')
    require(run.get('head_sha') == sha and run.get('run_attempt') == attempt, 'run source/attempt mismatch')
    require(run.get('workflow_id') == workflow_id and run.get('path') == WORKFLOW, 'wrong validation workflow')
    require(run.get('head_branch') == 'main' and run.get('event') == 'workflow_dispatch', 'wrong validation trigger')
    require(run.get('status') == 'completed' and run.get('conclusion') == 'success', 'validation not successful')


def check_context(run, jobs, artifact, workflow_id, repository, sha, version, attempt, now=None):
    identity(sha,version)
    check_dispatch(run, workflow_id, repository, sha, attempt)
    for job_name, stages in REQUIRED_JOBS.items():
        matches = [job for job in jobs if job.get('name') == job_name]
        require(len(matches) == 1 and matches[0].get('conclusion') == 'success',
                f'required stage job missing or unsuccessful: {job_name}')
        steps = {s['name']:s.get('conclusion') for s in matches[0].get('steps',[])}
        require(all(steps.get(name) == 'success' for name in stages), 'required stage did not pass')
    require(artifact.get('name') == f'verified-windows-{run["id"]}-{attempt}' and not artifact.get('expired'),
            'artifact missing, wrong attempt, or expired')
    require(artifact.get('workflow_run',{}).get('id') == run['id'] and
            artifact.get('workflow_run',{}).get('head_sha') == sha, 'artifact provenance mismatch')
    require(0 < artifact.get('size_in_bytes',0) <= MAX_BYTES+1024*1024, 'artifact size invalid')
    expiry = datetime.fromisoformat(artifact['expires_at'].replace('Z','+00:00'))
    require(expiry > (now or utcnow()), 'artifact expired')


def gate(repository, run_id, attempt, sha, version, *, require_tag=True):
    identity(sha, version)
    require(run_id > 0 and attempt > 0, 'invalid run identity')
    require(repository == os.environ['GITHUB_REPOSITORY'], 'repository mismatch')
    run = api(f'repos/{repository}/actions/runs/{run_id}')
    workflow = api(f'repos/{repository}/actions/workflows/windows.yml')
    jobs = pages(f'repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs','jobs')
    artifacts = pages(f'repos/{repository}/actions/runs/{run_id}/artifacts','artifacts')
    matches = [a for a in artifacts if a['name'] == f'verified-windows-{run_id}-{attempt}']
    require(len(matches) == 1, 'candidate artifact missing or ambiguous')
    artifact = matches[0]
    check_context(run,jobs,artifact,workflow['id'],repository,sha,version,attempt)
    subprocess.run(['git','fetch','origin','main','--tags'],check=True)
    if require_tag:
        tag_sha = subprocess.check_output(['git','rev-parse',f'refs/tags/v{version}^{{commit}}'],text=True).strip()
        require(tag_sha == sha,'tag must point to validated source SHA')
    require(fingerprint('origin/main') == fingerprint(sha),'validation inputs changed after validation')
    return dict(source_sha=sha,version=version,repository=repository,run_id=run_id,run_attempt=attempt,
                artifact_id=artifact['id'],artifact_name=artifact['name'])


def verify_bundle(folder, context, now=None):
    require((folder/'candidate.json').is_file() and not (folder/'candidate.json').is_symlink(),
            'manifest missing or unsafe')
    manifest = json.loads((folder/'candidate.json').read_text(encoding='utf-8'))
    require(manifest.get('schema') == 2 and manifest.get('workflow') == WORKFLOW and
            manifest.get('validation_profile') == PROFILE, 'unknown candidate format')
    for key in ('source_sha','version','repository','run_id','run_attempt'):
        require(manifest.get(key) == context[key],f'candidate {key} mismatch')
    identity(manifest['source_sha'],manifest['version'])
    now = now or utcnow()
    created = datetime.fromisoformat(manifest['created_at'])
    expiry = datetime.fromisoformat(manifest['expires_at'])
    require(created <= now + timedelta(minutes=5) and created < expiry <= created+TTL and now < expiry,
            'candidate lifetime invalid or expired')
    expected = {'mabinogi-addon.exe','unit-results.xml','windows-results.xml','notes.md','version.json'}
    require(set(manifest['files']) == expected,'candidate file inventory mismatch')
    require({p.name for p in folder.iterdir()} == expected | {'candidate.json'},'unexpected candidate files')
    for name, info in manifest['files'].items():
        path = folder/name
        require(path.is_file() and not path.is_symlink(),'candidate file missing or unsafe')
        require(path.stat().st_size == info['size'] and digest(path) == info['sha256'],'candidate file hash mismatch')
    require(sum(i['size'] for i in manifest['files'].values()) + (folder/'candidate.json').stat().st_size
            <= MAX_BYTES,'candidate oversized')
    require(manifest['exe_version'] == manifest['version'],'embedded version mismatch')
    for report in ('unit-results.xml','windows-results.xml'):
        report_passed(folder/report)
    update = json.loads((folder/'version.json').read_text(encoding='utf-8'))
    exe = manifest['files']['mabinogi-addon.exe']
    require(update == dict(version=manifest['version'],
        url=f'https://github.com/{PUBLIC_REPO}/releases/download/v{manifest["version"]}/mabinogi-addon.exe',
        sha256=exe['sha256'],size=exe['size']),'update metadata mismatch')
    require(manifest['source_fingerprint'] == fingerprint(manifest['source_sha']),'source fingerprint mismatch')
    return manifest


def prune(repository):
    artifacts = pages(f'repos/{repository}/actions/artifacts','artifacts')
    candidates = sorted((a for a in artifacts if a['name'].startswith('verified-windows-')),
                        key=lambda a:a['id'],reverse=True)
    # Leave one previous candidate before uploading the new one: at most two total.
    for artifact in candidates[1:]:
        api(f'repos/{repository}/actions/artifacts/{artifact["id"]}',method='DELETE')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command',choices=['preflight','seal','gate','check','prune'])
    parser.add_argument('--version')
    parser.add_argument('--mode', default='verify-only')
    parser.add_argument('--sha')
    parser.add_argument('--run-id',type=int)
    parser.add_argument('--attempt',type=int,default=1)
    parser.add_argument('--repository',default=os.environ.get('GITHUB_REPOSITORY',''))
    parser.add_argument('--folder',type=Path,default=Path('candidate'))
    args = parser.parse_args()
    if args.command == 'preflight':
        preflight(Path.cwd(),args.sha,args.version)
    elif args.command == 'prune':
        prune(args.repository)
    elif args.command == 'seal':
        seal(Path.cwd(),args.folder,args.sha,args.version,args.run_id,args.attempt,args.repository,mode=args.mode)
    elif args.command == 'gate':
        context = gate(args.repository,args.run_id,args.attempt,args.sha,args.version)
        Path('verified-run.json').write_text(json.dumps(context),encoding='utf-8')
        with Path(os.environ['GITHUB_OUTPUT']).open('a',encoding='utf-8') as out:
            out.write(f'artifact_name={context["artifact_name"]}\n')
    else:
        context = json.loads(Path('verified-run.json').read_text(encoding='utf-8'))
        # Recheck the run/attempt/artifact immediately before any publication.
        require(gate(context['repository'],context['run_id'],context['run_attempt'],
                     context['source_sha'],context['version']) == context,'candidate provenance changed')
        verify_bundle(args.folder,context)


if __name__ == '__main__':
    main()
