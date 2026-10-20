"""Trusted dispatch receipt, candidate selection and completion-event promotion.

Only data is downloaded from Actions artifacts. All executable code comes from main.
No command here reruns tests/builds or dispatches another workflow.
"""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

from scripts import release_candidate as c
from scripts import release_delivery as delivery

MODES = ('verify-only', 'validate-and-publish', 'publish-existing')
REQUEST_STEP = 'Freeze release request'
REQUEST_UPLOAD = 'Store release request'
BUNDLE_FILES = {'candidate.json', 'mabinogi-addon.exe', 'version.json', 'notes.md',
                'unit-results.xml', 'windows-results.xml'}
CONTEXT_KEYS = ('repository', 'source_sha', 'version', 'run_id', 'run_attempt')


def request_name(run_id, attempt):
    return f'release-request-{run_id}-{attempt}'


def download(repository, artifact, folder, expected, limit):
    """Read a bounded flat ZIP; never extract paths, symlinks or executable code."""
    c.require(not artifact.get('expired') and 0 < artifact['size_in_bytes'] <= limit + 1024*1024,
              'artifact expired or oversized')
    with tempfile.TemporaryDirectory() as temp:
        archive = Path(temp)/'artifact.zip'
        with archive.open('wb') as out:
            subprocess.run(['gh', 'api', f'repos/{repository}/actions/artifacts/{artifact["id"]}/zip'],
                           stdout=out, check=True)
        c.require(archive.stat().st_size <= limit + 1024*1024, 'artifact archive oversized')
        with zipfile.ZipFile(archive) as z:
            entries = z.infolist()
            c.require(len(entries) == len(expected) and {i.filename for i in entries} == expected,
                      'unsafe artifact inventory')
            c.require(sum(i.file_size for i in entries) <= limit, 'expanded artifact oversized')
            c.require(all(not i.is_dir() and (i.external_attr >> 16) & 0o170000 != 0o120000
                          for i in entries), 'unsafe artifact entry')
            folder.mkdir(parents=True, exist_ok=False)
            for entry in entries:
                (folder/entry.filename).write_bytes(z.read(entry))


def candidate_artifact(repository, run_id, attempt):
    matches = [a for a in c.pages(f'repos/{repository}/actions/runs/{run_id}/artifacts', 'artifacts')
               if a['name'] == f'verified-windows-{run_id}-{attempt}']
    c.require(len(matches) == 1, 'candidate artifact missing or ambiguous')
    return matches[0]


def select_existing(repository, sha, version, candidate_run=''):
    """Match the dispatch's frozen inputs, never choose an arbitrary latest success."""
    c.require(not candidate_run or re.fullmatch(r'[1-9]\d*', candidate_run), 'invalid candidate run ID')
    artifacts = c.pages(f'repos/{repository}/actions/artifacts', 'artifacts')
    matches = []
    live_runs = {}
    for artifact in artifacts:
        match = re.fullmatch(r'verified-windows-([1-9]\d*)-([1-9]\d*)', artifact['name'])
        if not match or artifact.get('expired'):
            continue
        run_id, attempt = map(int, match.groups())
        if candidate_run and run_id != int(candidate_run):
            continue
        # Retention can leave prior attempts beside the latest candidate. Exclude
        # those before the strict gate; never turn their rejection into a failure
        # of an otherwise unique latest candidate. API failures remain fatal.
        if run_id not in live_runs:
            live_runs[run_id] = c.api(f'repos/{repository}/actions/runs/{run_id}')
        latest_attempt = live_runs[run_id].get('run_attempt')
        c.require(type(latest_attempt) is int and latest_attempt > 0, 'invalid live run attempt')
        if attempt != latest_attempt:
            continue
        candidate_sha = artifact.get('workflow_run', {}).get('head_sha', '')
        c.identity(candidate_sha, version)
        if c.fingerprint(candidate_sha) != c.fingerprint(sha):
            continue
        # Fetch provenance before downloading bytes. In particular a previous attempt
        # cannot stand in for a newer failed/in-progress attempt of the same run.
        context = c.gate(repository, run_id, attempt, candidate_sha, version, require_tag=False)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)/'candidate'
            download(repository, artifact, folder, BUNDLE_FILES, c.MAX_BYTES)
            manifest = json.loads((folder/'candidate.json').read_text(encoding='utf-8'))
            if manifest.get('version') != version:
                continue
            c.verify_bundle(folder, context)
            matches.append(dict(context=context, manifest_sha256=c.digest(folder/'candidate.json')))
    c.require(len(matches) == 1,
              'no unique valid candidate: no rebuild started; specify candidate_run if ambiguous')
    return matches[0]


def prepare(root, output, repository, sha, version, run_id, attempt, mode, candidate_run=''):
    c.require(mode in MODES, 'invalid release mode')
    c.require(run_id > 0 and attempt > 0, 'invalid request identity')
    c.require(repository == os.environ['GITHUB_REPOSITORY'] and
              sha == os.environ['GITHUB_SHA'] and
              os.environ['GITHUB_REF'] == 'refs/heads/main' and
              os.environ['GITHUB_EVENT_NAME'] == 'workflow_dispatch', 'untrusted request trigger')
    c.require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == sha,
              'request checkout/source mismatch')
    c.preflight(root, sha, version)
    c.require(mode == 'publish-existing' or not candidate_run, 'candidate_run only applies to publish-existing')
    request = dict(schema=1, workflow=c.WORKFLOW, repository=repository, source_sha=sha,
                   source_fingerprint=c.fingerprint(sha), version=version,
                   run_id=run_id, run_attempt=attempt, mode=mode)
    if mode == 'publish-existing':
        request['candidate'] = select_existing(repository, sha, version, candidate_run)
    c.require(not output.exists(), 'request output already exists')
    output.mkdir(parents=True)
    (output/'release-request.json').write_text(json.dumps(request, indent=2)+'\n', encoding='utf-8')
    return request


def completed_request(event, repository, folder):
    c.require(event.get('action') == 'completed' and
              event.get('repository', {}).get('full_name') == repository, 'wrong completion event')
    trigger = event['workflow_run']
    run_id, attempt, sha = trigger['id'], trigger['run_attempt'], trigger['head_sha']
    c.require(type(run_id) is int and run_id > 0 and type(attempt) is int and attempt > 0,
              'invalid triggering run identity')
    workflow_id = c.api(f'repos/{repository}/actions/workflows/windows.yml')['id']
    # Check both the delivered event and live API state; old duplicate events must
    # never select another attempt, even if that newer attempt is also successful.
    c.check_dispatch(trigger, workflow_id, repository, sha, attempt)
    live = c.api(f'repos/{repository}/actions/runs/{run_id}')
    c.check_dispatch(live, workflow_id, repository, sha, attempt)
    jobs = c.pages(f'repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs', 'jobs')
    request_jobs = [j for j in jobs if j.get('name') == 'request']
    c.require(len(request_jobs) == 1 and request_jobs[0].get('conclusion') == 'success',
              'trusted request job missing')
    steps = {s['name']: s.get('conclusion') for s in request_jobs[0].get('steps', [])}
    c.require(all(steps.get(s) == 'success' for s in (REQUEST_STEP, REQUEST_UPLOAD)),
              'request not successfully stored')
    artifacts = c.pages(f'repos/{repository}/actions/runs/{run_id}/artifacts', 'artifacts')
    matches = [a for a in artifacts if a['name'] == request_name(run_id, attempt)]
    c.require(len(matches) == 1, 'request artifact missing or ambiguous')
    artifact = matches[0]
    c.require(artifact.get('workflow_run', {}).get('id') == run_id and
              artifact['workflow_run'].get('head_sha') == sha, 'request artifact provenance mismatch')
    c.require(datetime.fromisoformat(artifact['expires_at'].replace('Z', '+00:00')) > c.utcnow(),
              'request artifact expired')
    download(repository, artifact, folder, {'release-request.json'}, 64*1024)
    request = json.loads((folder/'release-request.json').read_text(encoding='utf-8'))
    c.require(request.get('schema') == 1 and request.get('workflow') == c.WORKFLOW,
              'unknown request format')
    for key, expected in dict(repository=repository, source_sha=sha, run_id=run_id, run_attempt=attempt).items():
        c.require(request.get(key) == expected, f'request {key} mismatch')
    c.identity(sha, request['version'])
    c.require(request.get('mode') in MODES, 'invalid release mode')
    c.require(request.get('source_fingerprint') == c.fingerprint(sha), 'request fingerprint mismatch')
    return request


def approved_candidate(request, folder):
    mode = request['mode']
    c.require(mode in ('validate-and-publish', 'publish-existing'), 'publication not approved')
    if mode == 'validate-and-publish':
        selected = {key: request[key] for key in CONTEXT_KEYS}
    else:
        selected = request['candidate']['context']
        c.require(selected['repository'] == request['repository'] and
                  selected['version'] == request['version'], 'selected candidate mismatch')
    c.require(c.fingerprint(selected['source_sha']) == request['source_fingerprint'],
              'candidate differs from approved source')
    context = c.gate(selected['repository'], selected['run_id'], selected['run_attempt'],
                     selected['source_sha'], selected['version'], require_tag=False)
    if mode == 'publish-existing':
        c.require(context == selected, 'selected candidate provenance changed')
    artifact = candidate_artifact(context['repository'], context['run_id'], context['run_attempt'])
    c.require(artifact['id'] == context['artifact_id'], 'candidate artifact replaced')
    download(context['repository'], artifact, folder, BUNDLE_FILES, c.MAX_BYTES)
    manifest = c.verify_bundle(folder, context)
    if mode == 'validate-and-publish':
        expected = dict(mode=mode, **{key: request[key] for key in CONTEXT_KEYS})
        c.require(manifest.get('authorization') == expected, 'candidate publication approval mismatch')
    else:
        c.require(c.digest(folder/'candidate.json') == request['candidate']['manifest_sha256'],
                  'selected candidate bytes changed')
    return context


def create_tag(context):
    # Atomic create-only ref API: existing tags cannot be moved, deleted or reused.
    c.preflight(Path.cwd(), context['source_sha'], context['version'])
    repo = context['repository']
    ref = 'refs/tags/v'+context['version']
    c.api(f'repos/{repo}/git/refs', method='POST', data=dict(ref=ref, sha=context['source_sha']))
    remote = c.api(f'repos/{repo}/git/ref/tags/v{context["version"]}')
    c.require(remote.get('ref') == ref and remote.get('object', {}).get('type') == 'commit' and
              remote['object'].get('sha') == context['source_sha'], 'created tag source mismatch')


def complete(event, repository, root=Path('.')):
    with tempfile.TemporaryDirectory() as temp:
        request = completed_request(event, repository, Path(temp)/'request')
        if request['mode'] == 'verify-only':
            print('Verification only: publication was not approved.')
            return
        folder = Path(temp)/'candidate'
        context = approved_candidate(request, folder)
        # gate re-fetches main/tags; check the approved inputs again before tag creation.
        c.require(c.fingerprint('HEAD') == request['source_fingerprint'], 'trusted checkout inputs changed')
        c.require(c.gate(context['repository'], context['run_id'], context['run_attempt'],
                         context['source_sha'], context['version'], require_tag=False) == context,
                  'candidate changed before tag creation')
        c.verify_bundle(folder, context)
        delivery.ensure_unpublished(context)
        create_tag(context)
        c.require(c.gate(context['repository'], context['run_id'], context['run_attempt'],
                         context['source_sha'], context['version']) == context, 'final tagged gate changed')
        Path('verified-run.json').write_text(json.dumps(context), encoding='utf-8')
        delivery.promote(root, folder, Path('pub'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prepare', 'authorize', 'complete'))
    args = parser.parse_args()
    repository = os.environ['GITHUB_REPOSITORY']
    if args.command == 'prepare':
        prepare(Path.cwd(), Path('release-request'), repository, os.environ['GITHUB_SHA'],
                os.environ['REQUEST_VERSION'], int(os.environ['GITHUB_RUN_ID']),
                int(os.environ['GITHUB_RUN_ATTEMPT']), os.environ['REQUEST_MODE'],
                os.environ.get('REQUEST_CANDIDATE_RUN', ''))
    else:
        c.require(os.environ['GITHUB_EVENT_NAME'] == 'workflow_run', 'wrong publisher trigger')
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
        if args.command == 'authorize':
            with tempfile.TemporaryDirectory() as temp:
                request = completed_request(event, repository, Path(temp)/'request')
            approved = request['mode'] != 'verify-only'
            with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
                output.write(f'publish={str(approved).lower()}\n')
            print('Publication approved.' if approved else 'Verification only: publication was not approved.')
        else:
            complete(event, repository)


if __name__ == '__main__':
    main()
