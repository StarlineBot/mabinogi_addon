"""Minimal LGPL FFmpeg build from pinned official source; no third-party codec libraries.

GPU 제조사 인코더(NVENC/AMF)는 고정 버전의 MIT 헤더만 쓴다. 드라이버 DLL은 실행 시 로드하며 동봉하지 않는다.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile

VERSION = '8.1.3'
SOURCE_URL = 'https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/refs/tags/n8.1.3'
SOURCE_SHA256 = '09f990289327d3ebfedf4fc15cae3f884a65dab7a5aac7bbb5b01ff83900efd9'
COMPILER_NAME = 'llvm-mingw-20261020-ucrt-x86_64'
COMPILER_URL = 'https://github.com/mstorsjo/llvm-mingw/releases/download/20261020/' + COMPILER_NAME + '.zip'
COMPILER_SHA256 = 'fd5462b7f5d93b2ff981fcd3f9c7e427e47f3203c64ea91c27bcc444eebd74cd'
MINGW_COMMIT = '0d6dfbc348dfad714761c0a7151615767f96bcb5'
MINGW_URL = 'https://codeload.github.com/mingw-w64/mingw-w64/tar.gz/' + MINGW_COMMIT
MINGW_SHA256 = '03f717ddb9005d6519e38434359af281d0819d5d468a42578e28bd0fd8e31d0c'
# 하드웨어 인코더 헤더. GitHub 압축 파일은 바이트가 바뀔 수 있어 커밋 SHA와 파일 내용 sha256으로 고정한다.
# FFmpeg 8.1.3 configure 요구: ffnvcodec >= 12.1.14.0(낮을수록 지원 드라이버 범위가 넓다), AMF >= 1.4.36.
NVCODEC_REPO = 'https://github.com/FFmpeg/nv-codec-headers'
NVCODEC_TAG = 'n12.1.14.0'
NVCODEC_COMMIT = '1889e62e2d35ff7aa9baca2bceb14f053785e6f1'
NVCODEC_TREE_SHA256 = '85a81ba7e43925499b632f218110dcf9d3e067c453b840e16d4f25b95f47bda2'  # include/
AMF_REPO = 'https://github.com/GPUOpen-LibrariesAndSDKs/AMF'
AMF_TAG = 'v1.4.36'
AMF_COMMIT = '16f7d73e0b45c473e903e46981ed0b91efc4c091'
AMF_TREE_SHA256 = '5124660defd33f787d378f19aacb904f60ad66741ad01d8887e1ff3d281edac3'  # amf/public/include/
AMF_LICENSE_SHA256 = 'eb297397aaa455b5668ab67d216b83828466152dab123fa92384c6ec16b74170'
BINARIES = ('ffmpeg.exe', 'ffprobe.exe', 'avcodec-62.dll', 'avformat-62.dll',
            'avutil-60.dll', 'avfilter-11.dll', 'swscale-9.dll', 'swresample-6.dll')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(url, expected, path):
    path = Path(path)
    if not path.exists():
        partial = path.with_suffix('.download')
        try:
            urllib.request.urlretrieve(url, partial)
            if digest(partial) != expected:
                raise ValueError('download SHA256 mismatch: ' + path.name)
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
    if digest(path) != expected:
        raise ValueError('cached SHA256 mismatch: ' + path.name)
    return path


def tree_digest(base):
    """디렉터리 파일 내용 해시(상대 경로 + 각 파일 sha256, 경로순). 압축 형식과 무관하다."""
    base = Path(base)
    h = hashlib.sha256()
    # 순서는 POSIX 상대경로 문자열로 고정한다. WindowsPath 비교는 대소문자를 무시해 'AMFXInput.h'와
    # 'Ambisonic2SRenderer.h' 순서가 Linux와 반대가 됐다(0.11.4 3차 검증 AMF 해시 불일치).
    for p in sorted((x for x in base.rglob('*') if x.is_file()), key=lambda x: x.relative_to(base).as_posix()):
        h.update(p.relative_to(base).as_posix().encode() + b'\0' + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def _git_checkout(repo, tag, commit, dest, sparse=()):
    # 외부 헤더 저장소엔 .gitattributes가 없어 Windows Git 기본값(core.autocrlf=true)이 CRLF로 체크아웃해
    # 내용 해시가 달라진다(0.11.4 검증 실패). 저장소 설정으로 남겨 이어지는 sparse-checkout에도 적용한다.
    command = ['git', '-c', 'advice.detachedHead=false', 'clone', '--config', 'core.autocrlf=false',
               '-q', '--depth', '1', '--branch', tag]
    if sparse:
        command += ['--filter=blob:none', '--sparse']
    env = dict(os.environ, GIT_LFS_SKIP_SMUDGE='1')
    subprocess.run(command + [repo, str(dest)], check=True, env=env)
    if sparse:
        subprocess.run(['git', '-C', str(dest), 'sparse-checkout', 'set', '--no-cone', *sparse], check=True, env=env)
    head = subprocess.run(['git', '-C', str(dest), 'rev-parse', 'HEAD'], check=True,
                          capture_output=True, text=True).stdout.strip()
    if head != commit:
        raise ValueError(f'unexpected commit for {repo}@{tag}: {head}')
    return Path(dest)


def stage_hardware_headers(work, deps):
    """NVENC(ffnvcodec)·AMF 헤더를 고정 커밋으로 받아 내용 해시를 확인하고 deps 접두사에 설치한다."""
    deps = Path(deps)
    nv = _git_checkout(NVCODEC_REPO, NVCODEC_TAG, NVCODEC_COMMIT, work / 'nv-codec-headers')
    if tree_digest(nv / 'include') != NVCODEC_TREE_SHA256:
        raise ValueError('nv-codec-headers content SHA256 mismatch')
    amf = _git_checkout(AMF_REPO, AMF_TAG, AMF_COMMIT, work / 'amf-headers',
                        sparse=('/amf/public/include', '/LICENSE.txt'))
    if tree_digest(amf / 'amf/public/include') != AMF_TREE_SHA256 or digest(amf / 'LICENSE.txt') != AMF_LICENSE_SHA256:
        raise ValueError('AMF header content SHA256 mismatch')
    shutil.copytree(nv / 'include/ffnvcodec', deps / 'include/ffnvcodec')
    shutil.copytree(amf / 'amf/public/include', deps / 'include/AMF')
    # nv-codec-headers Makefile과 같은 결과(Windows는 cygpath -m 형식 'D:/...' 경로).
    (deps / 'lib/pkgconfig').mkdir(parents=True)
    (deps / 'lib/pkgconfig/ffnvcodec.pc').write_text(
        (nv / 'ffnvcodec.pc.in').read_text(encoding='utf-8').replace('@@PREFIX@@', deps.as_posix()), encoding='utf-8')
    return nv, amf


def compiler_extract(archive, work):
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            p = Path(info.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in info.filename or not p.parts or p.parts[0] != COMPILER_NAME:
                raise ValueError('invalid compiler archive path')
        z.extractall(work)
    return work / COMPILER_NAME


def source_materials(root, work):
    source = download(SOURCE_URL, SOURCE_SHA256, work / 'ffmpeg-source.tar.gz')
    mingw = download(MINGW_URL, MINGW_SHA256, work / 'mingw-source.tar.gz')
    with tarfile.open(source) as archive:
        archive.extractall(work, filter='data')
    with tarfile.open(mingw) as archive:
        archive.extractall(work, filter='data')
    return source, mingw, work / ('FFmpeg-n' + VERSION)


def package_sources(root, work, install, compiler, headers=None):
    source = work / ('FFmpeg-n' + VERSION)
    notices = ['This product runs FFmpeg ' + VERSION + ' as a separate process.\n'
        'FFmpeg libraries: LGPL-2.1-or-later; GPL/nonfree/version3 and external codec libraries disabled.\n'
        'NVIDIA NVENC / AMD AMF encoders are built from MIT-licensed headers (nv-codec-headers ' + NVCODEC_TAG
        + ', AMF ' + AMF_TAG + '). Their runtime DLLs come with the user GPU driver and are not bundled.\n'
        'FFmpeg source is unmodified. Build configuration and complete source are in corresponding-source.zip.\n'
        'Windows Media Foundation/GPU components are supplied by Windows and the user GPU driver, not bundled.\n'
        'This notice does not grant codec patent rights or assert that no royalties apply.\n'
        'IJG credit: This software is based in part on the work of the Independent JPEG Group.\n']
    notice_files = [(source / 'COPYING.LGPLv2.1', 'FFmpeg-LICENSE.txt'),
                    (compiler / 'LICENSE.TXT', 'LLVM-LICENSE.txt')]
    mingw = work / ('mingw-w64-' + MINGW_COMMIT)
    for p in sorted(mingw.rglob('*')):
        if p.is_file() and p.name in ('COPYING', 'COPYING.txt', 'DISCLAIMER'):
            notices += ['\nMinGW-w64 ' + str(p.relative_to(mingw)) + '\n', p.read_text(errors='replace')]
    for p, name in notice_files:
        shutil.copyfile(p, install / name)
        notices += ['\n' + name + '\n', p.read_text(errors='replace')]
    if headers is not None:
        nv, amf = headers
        nv_header = (nv / 'include/ffnvcodec/nvEncodeAPI.h').read_text(errors='replace')
        notices += ['\nnv-codec-headers ' + NVCODEC_TAG + ' (' + NVCODEC_COMMIT + ') license notice\n',
                    nv_header[:nv_header.find('*/') + 2]]
        notices += ['\nAMF ' + AMF_TAG + ' (' + AMF_COMMIT + ') LICENSE.txt\n',
                    (amf / 'LICENSE.txt').read_text(errors='replace')]
    (install / 'THIRD-PARTY-NOTICES.txt').write_text('\n'.join(notices), encoding='utf-8')
    with zipfile.ZipFile(install / 'corresponding-source.zip', 'w', zipfile.ZIP_STORED) as z:
        z.writestr('REBUILD.txt', 'Extract ffmpeg-source.tar.gz, then run ffmpeg_minimal.sh from FFmpeg-n8.1.3.\n'
            'Arguments: installation prefix, absolute LLVM-MinGW bin/x86_64-w64-mingw32- prefix,\n'
            'hardware header prefix (nv-codec-headers ' + NVCODEC_TAG + ' include+ffnvcodec.pc, AMF ' + AMF_TAG
            + ' include as include/AMF; both in hardware-headers.zip).\n'
            'On Windows use MSYS2 bash and GNU make; compiler source URLs/hashes are in ffmpeg_source.py.\n'
            'On Linux use the corresponding Linux LLVM-MinGW toolchain. No FFmpeg source patches.\n'
            'config.h/config.mak record this build. Compiler runtimes retain their supplied licenses.\n'
            'No app source or user recordings are included. Bit-identical cross-host output is not claimed.\n')
        for p in (work/'ffmpeg-source.tar.gz', work/'mingw-source.tar.gz', root/'packaging/ffmpeg_minimal.sh',
                  root/'packaging/ffmpeg_source.py', source/'config.h', source/'ffbuild/config.mak',
                  install/'THIRD-PARTY-NOTICES.txt'):
            z.write(p, p.name)
        if headers is not None:
            nv, amf = headers
            for base, prefix in ((nv, 'nv-codec-headers/'), (amf, 'amf/')):
                for p in sorted(x for x in base.rglob('*') if x.is_file() and '.git' not in x.relative_to(base).parts):
                    z.write(p, 'hardware-headers/' + prefix + p.relative_to(base).as_posix())
    compiler_url, compiler_sha256 = COMPILER_URL, COMPILER_SHA256
    if compiler.name == 'llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64':
        compiler_url = 'https://github.com/mstorsjo/llvm-mingw/releases/download/20261020/' + compiler.name + '.tar.xz'
        compiler_sha256 = '55064b60b991a1e1e8090b8c2f84e82b22cfe5903d12c159d65064cf5e8ae335'
    elif compiler.name != COMPILER_NAME:
        raise ValueError('unrecorded compiler provenance')
    (install / 'redistribution.json').write_text(json.dumps(dict(
        license='LGPL-2.1-or-later', version=VERSION, source_url=SOURCE_URL, source_sha256=SOURCE_SHA256,
        compiler_url=compiler_url, compiler_sha256=compiler_sha256,
        mingw_url=MINGW_URL, mingw_sha256=MINGW_SHA256,
        nvcodec=dict(repo=NVCODEC_REPO, tag=NVCODEC_TAG, commit=NVCODEC_COMMIT, tree_sha256=NVCODEC_TREE_SHA256),
        amf=dict(repo=AMF_REPO, tag=AMF_TAG, commit=AMF_COMMIT, tree_sha256=AMF_TREE_SHA256),
        corresponding_source_sha256=digest(install/'corresponding-source.zip'),
        notices_sha256=digest(install/'THIRD-PARTY-NOTICES.txt'),
        binaries={name:digest(install/name) for name in BINARIES}), indent=2), encoding='utf-8')


def msys_build_env(bash, environ=None):
    env = dict(os.environ if environ is None else environ)
    env['PATH'] = str(bash.parent) + os.pathsep + env.get('PATH', '')
    # Native LLVM needs MSYS POSIX temporary paths converted to Windows paths.
    env['MSYS2_ARG_CONV_EXCL'] = ''
    return env


def build(root, work, output):
    work.mkdir(parents=True, exist_ok=False)
    _, _, source = source_materials(root, work)
    compiler = compiler_extract(download(COMPILER_URL, COMPILER_SHA256, work/'compiler.zip'), work)
    bash = Path('C:/msys64/usr/bin/bash.exe')
    if not bash.is_file():
        raise RuntimeError('Build machine requires MSYS2 bash/make (GitHub windows-2022 provides MSYS2)')
    env = msys_build_env(bash)
    # Build tools only, never installed on the user's machine or shipped with the app.
    subprocess.run([str(bash), '--noprofile', '--norc', '-c',
        'command -v make >/dev/null || pacman -Sy --needed --noconfirm make; '
        'command -v pkg-config >/dev/null || pacman -Sy --needed --noconfirm pkgconf'], check=True, env=env)
    headers = stage_hardware_headers(work, work / 'hardware-deps')
    prefix = (compiler/'bin/x86_64-w64-mingw32-').as_posix()
    subprocess.run([str(bash), '--noprofile', '--norc', (root/'packaging/ffmpeg_minimal.sh').as_posix(),
                    output.as_posix(), prefix, (work / 'hardware-deps').as_posix()], cwd=source, check=True, env=env)
    # Only runtime binaries, not tools/headers/import libraries, go into the app.
    for name in BINARIES:
        shutil.copyfile(output/'bin'/name, output/name)
    for folder in ('bin', 'lib', 'include', 'share'):
        shutil.rmtree(output/folder, ignore_errors=True)
    package_sources(root, work, output, compiler, headers)
