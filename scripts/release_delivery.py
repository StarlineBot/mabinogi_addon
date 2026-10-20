"""Promote a verified candidate, never build it. Called only after explicit dispatch authorization."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request

from scripts.release_candidate import PUBLIC_REPO, digest, gate, require, verify_bundle


def gh(*args, token):
    return subprocess.check_output(['gh', *args], env={**os.environ, 'GH_TOKEN': token}, text=True)


def prepare_public(root, public, candidate, version):
    notes = (candidate/'notes.md').read_text(encoding='utf-8')
    changelog = public/'CHANGELOG.md'
    previous = (changelog if changelog.exists() else root/'packaging/CHANGELOG.md').read_text(encoding='utf-8')
    heading = f'### v{version}'
    require(not any(line == heading or line.startswith(heading+' ') for line in previous.splitlines()),
            'version already in public changelog')
    changelog.write_text(heading+'\n'+notes+'\n'+previous, encoding='utf-8')
    template = (root/'packaging/releases_README.md').read_text(encoding='utf-8')
    require('<!-- CHANGELOG -->' in template, 'missing changelog placeholder')
    (public/'README.md').write_text(template.replace('<!-- CHANGELOG -->', changelog.read_text(encoding='utf-8')), encoding='utf-8')
    shutil.copyfile(candidate/'version.json', public/'version.json')
    target = public/'data/dialogues.json'
    target.parent.mkdir(exist_ok=True)
    if not target.exists():
        shutil.copyfile(root/'src/mabinogi_addon/assets/dialogues.json', target)


def ensure_unpublished(context):
    tag = 'v'+context['version']
    targets = [(context['repository'], os.environ['GH_TOKEN']),
               (PUBLIC_REPO, os.environ['RELEASES_TOKEN'])]
    # An earlier partial publication requires inspection, not an overwrite.
    for repo, token in targets:
        pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{repo}/releases?per_page=100', token=token))
        releases = [release for page in pages for release in page]
        require(not any(r['tag_name'] == tag for r in releases), 'release already exists; inspect partial publication')
    return targets


def promote(root=Path('.'), folder=Path('candidate'), public=Path('pub')):
    context = json.loads(Path('verified-run.json').read_text(encoding='utf-8'))
    require(gate(context['repository'], context['run_id'], context['run_attempt'],
                 context['source_sha'], context['version']) == context, 'provenance changed')
    verify_bundle(folder, context)
    version, tag = context['version'], 'v'+context['version']
    targets = ensure_unpublished(context)
    prepare_public(root, public, folder, version)
    assets = [str(folder/name) for name in ('mabinogi-addon.exe','version.json','candidate.json')]
    for repo, token in targets:
        args = ['release','create',tag,'--repo',repo,'--draft','--title',tag,
                '--notes-file',str(folder/'notes.md'), *assets]
        if repo == context['repository']:
            args += ['--verify-tag']
        gh(*args, token=token)
        # Verify uploaded bytes before either draft becomes public.
        with tempfile.TemporaryDirectory() as temp:
            gh('release','download',tag,'--repo',repo,'--dir',temp, token=token)
            for asset in assets:
                require(digest(Path(temp)/Path(asset).name) == digest(asset), 'uploaded asset hash mismatch')
    # Downloads can cross expiry or main can advance while uploading.
    require(gate(context['repository'],context['run_id'],context['run_attempt'],
                 context['source_sha'],version) == context, 'provenance changed before publication')
    verify_bundle(folder, context)
    for repo, token in reversed(targets):
        gh('release','edit',tag,'--repo',repo,'--draft=false', token=token)
    subprocess.run(['git','-C',str(public),'config','user.name','github-actions'],check=True)
    subprocess.run(['git','-C',str(public),'config','user.email','github-actions@users.noreply.github.com'],check=True)
    subprocess.run(['git','-C',str(public),'add','version.json','README.md','CHANGELOG.md','data/dialogues.json'],check=True)
    subprocess.run(['git','-C',str(public),'commit','-m',f'release: {tag}'],check=True)
    subprocess.run(['git','-C',str(public),'push','origin','HEAD:main'],check=True)
    hook = os.environ.get('RELEASE_WEBHOOK_URL')
    if hook:
        content = (folder/'notes.md').read_text(encoding='utf-8') + f'\nhttps://github.com/{PUBLIC_REPO}/releases/tag/{tag}'
        request = urllib.request.Request(hook, data=json.dumps(dict(thread_name=tag,content=content[:1900])).encode(),
                                         headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=30):
                pass
        except Exception:
            print('::warning::Release published, Discord announcement failed')


if __name__ == '__main__':
    promote()
