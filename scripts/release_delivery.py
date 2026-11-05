"""Promote a verified candidate, never build it. Called only after explicit dispatch authorization."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

from scripts.release_candidate import PUBLIC_REPO, digest, gate, require, verify_bundle


def gh(*args, token):
    return subprocess.check_output(['gh', *args], env={**os.environ, 'GH_TOKEN': token}, text=True)


def fold_changelog(text):
    """README용 내역: 최신 버전 하나만 펼치고 이전 버전은 접는다(CHANGELOG.md 자체는 전체 유지)."""
    lines = text.splitlines(keepends=True)
    heads = [i for i, line in enumerate(lines) if line.startswith('### v')]
    if len(heads) < 2:
        return text
    latest, older = ''.join(lines[:heads[1]]).rstrip('\n'), ''.join(lines[heads[1]:]).strip('\n')
    return (latest+'\n\n<details>\n<summary>이전 버전 업데이트 내역 보기</summary>\n\n'
            + older+'\n\n</details>\n')


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
    (public/'README.md').write_text(template.replace('<!-- CHANGELOG -->', fold_changelog(changelog.read_text(encoding='utf-8'))), encoding='utf-8')
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
        announce(hook, tag, content)


# Discord 앞단 Cloudflare는 Python-urllib 기본 User-Agent를 403으로 막는다(앱 문의하기와 같은 원인).
# 2026-10-19 배포 단계를 bash(curl) → 파이썬으로 옮긴 뒤 헤더가 빠져 배포 알림이 조용히 실패했다.
USER_AGENT = 'mabinogi-addon-release (https://github.com/StarlineBot/mabinogi_addon, 1.0)'


def announce(hook, tag, content, *, urlopen=urllib.request.urlopen):
    """배포 알림(포럼 글 = 버전). 포럼이 아닌 채널이면 thread_name을 거부(400)하므로 제목을 본문에 넣어 다시 보낸다.
    실패해도 배포는 끝난 뒤라 경고만 — 단 원인(HTTP 코드)을 남긴다. 성공하면 True."""
    def post(payload):
        request = urllib.request.Request(hook, data=json.dumps(payload).encode(), method='POST',
                                         headers={'Content-Type': 'application/json', 'User-Agent': USER_AGENT})
        with urlopen(request, timeout=30):
            pass
    payload = dict(thread_name=tag, content=content[:1900])
    try:
        try:
            post(payload)
        except urllib.error.HTTPError as exc:
            if exc.code != 400:
                raise
            post(dict(content=f'**{tag}**\n{content}'[:1900]))
        return True
    except Exception as exc:  # noqa: BLE001 — 배포는 이미 끝났다
        detail = f'HTTP {exc.code}' if isinstance(exc, urllib.error.HTTPError) else type(exc).__name__
        print(f'::warning::Release published, Discord announcement failed ({detail})')
        return False


if __name__ == '__main__':
    promote()
