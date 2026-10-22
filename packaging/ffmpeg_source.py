"""Minimal LGPL FFmpeg build from pinned official source; no third-party codecs."""
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


def package_sources(root, work, install, compiler):
    source = work / ('FFmpeg-n' + VERSION)
    notices = ['This product runs FFmpeg ' + VERSION + ' as a separate process.\n'
        'FFmpeg libraries: LGPL-2.1-or-later; GPL/nonfree/version3 and external codec libraries disabled.\n'
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
    (install / 'THIRD-PARTY-NOTICES.txt').write_text('\n'.join(notices), encoding='utf-8')
    with zipfile.ZipFile(install / 'corresponding-source.zip', 'w', zipfile.ZIP_STORED) as z:
        z.writestr('REBUILD.txt', 'Extract ffmpeg-source.tar.gz, then run ffmpeg_minimal.sh from FFmpeg-n8.1.3.\n'
            'Arguments: installation prefix, absolute LLVM-MinGW bin/x86_64-w64-mingw32- prefix.\n'
            'On Windows use MSYS2 bash and GNU make; compiler source URLs/hashes are in ffmpeg_source.py.\n'
            'On Linux use the corresponding Linux LLVM-MinGW toolchain. No FFmpeg source patches.\n'
            'config.h/config.mak record this build. Compiler runtimes retain their supplied licenses.\n'
            'No app source or user recordings are included. Bit-identical cross-host output is not claimed.\n')
        for p in (work/'ffmpeg-source.tar.gz', work/'mingw-source.tar.gz', root/'packaging/ffmpeg_minimal.sh',
                  root/'packaging/ffmpeg_source.py', source/'config.h', source/'ffbuild/config.mak',
                  install/'THIRD-PARTY-NOTICES.txt'):
            z.write(p, p.name)
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
        'command -v make >/dev/null || pacman -Sy --needed --noconfirm make'], check=True, env=env)
    prefix = (compiler/'bin/x86_64-w64-mingw32-').as_posix()
    subprocess.run([str(bash), '--noprofile', '--norc', (root/'packaging/ffmpeg_minimal.sh').as_posix(),
                    output.as_posix(), prefix], cwd=source, check=True, env=env)
    # Only runtime binaries, not tools/headers/import libraries, go into the app.
    for name in BINARIES:
        shutil.copyfile(output/'bin'/name, output/name)
    for folder in ('bin', 'lib', 'include', 'share'):
        shutil.rmtree(output/folder, ignore_errors=True)
    package_sources(root, work, output, compiler)
