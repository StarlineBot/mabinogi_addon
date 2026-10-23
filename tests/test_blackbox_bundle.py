import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile
import pytest
from mabinogi_addon.blackbox_bundle import load_product_profile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('blackbox_packager', ROOT/'packaging/blackbox_bundle.py')
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


def test_missing_reviewed_product_inputs_fail_before_build_or_download(tmp_path):
    with pytest.raises(RuntimeError, match='release blocked'):
        packager.prepare(tmp_path, tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_source_hash_rejects_unpinned_cached_source(tmp_path):
    spec = importlib.util.spec_from_file_location('source_builder', ROOT/'packaging/ffmpeg_source.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    archive = tmp_path/'source.tar.gz';archive.write_bytes(b'bad')
    with pytest.raises(ValueError, match='SHA256'):
        builder.download('https://invalid.invalid/no-network-needed', '0'*64, archive)


def test_compiler_archive_traversal_is_rejected(tmp_path):
    spec = importlib.util.spec_from_file_location('source_builder', ROOT/'packaging/ffmpeg_source.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    archive = tmp_path/'compiler.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr(builder.COMPILER_NAME+'/../outside',b'bad')
    with pytest.raises(ValueError,match='archive path'):
        builder.compiler_extract(archive,tmp_path/'out')
    assert not (tmp_path/'outside').exists()


def test_frozen_missing_bundle_is_explicit_error(tmp_path):
    with pytest.raises(FileNotFoundError):load_product_profile(bundle=tmp_path,data=tmp_path/'user')
    assert not (tmp_path/'user').exists()


def test_product_paths_are_bundled_and_missing_policy_is_not_defaulted(tmp_path):
    names=['product.json','mabinogi_blackbox.dll','blackbox_codec_host.exe','ffmpeg.exe','ffprobe.exe',
           'redistribution.json','THIRD-PARTY-NOTICES.txt','corresponding-source.zip','FFmpeg-LICENSE.txt', 'avcodec-62.dll','avformat-62.dll',
           'avutil-60.dll','avfilter-11.dll','swscale-9.dll','swresample-6.dll']
    for name in names:(tmp_path/name).write_bytes(b'{}')
    (tmp_path/'product.json').write_text(json.dumps({'codec':{'encoder':'libx264'},'audio':'process'}), encoding="utf-8")
    manifest={n:hashlib.sha256((tmp_path/n).read_bytes()).hexdigest() for n in names}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError,match='하드웨어'):load_product_profile(bundle=tmp_path,data=tmp_path/'user')
    (tmp_path/'ffmpeg.exe').write_bytes(b'changed')
    with pytest.raises(ValueError,match='확인 실패'):load_product_profile(bundle=tmp_path,data=tmp_path/'user')


def test_complete_product_profile_resolves_paths_without_device_access(tmp_path):
    policy = dict(max_bytes=1000000, min_free_bytes=0, max_entries=20,
        max_buffer_bytes=100000, max_segments=10, max_output_bytes=200000, cursor=False,
        producer=dict(segment_frames=2, queued_segments=2, max_frame_bytes=64,
            max_raw_bytes=1024, max_segment_bytes=10000, frame_tolerance_us=1000, max_width=1920, max_height=1080,
            max_input_width=3840, max_input_height=2160),
        codec=dict(encoder='h264_mf', bitrate=100000, fps=60, timeout=10,
            tolerance_us=100000, audio_bitrate=64000), hotkey_modifiers=3, hotkey_vk=0x75,
        audio='process', audio_settings=dict(audio_rate=48000, audio_channels=2,
            max_audio_bytes=1024, activation_timeout_ms=1000, audio_buffer_bytes=4096))
    names=['product.json','mabinogi_blackbox.dll','blackbox_codec_host.exe','ffmpeg.exe','ffprobe.exe',
           'redistribution.json','THIRD-PARTY-NOTICES.txt','corresponding-source.zip','FFmpeg-LICENSE.txt', 'avcodec-62.dll','avformat-62.dll',
           'avutil-60.dll','avfilter-11.dll','swscale-9.dll','swresample-6.dll']
    for name in names:(tmp_path/name).write_bytes(b'{}')
    (tmp_path/'product.json').write_text(json.dumps(policy), encoding="utf-8")
    (tmp_path/'manifest.json').write_text(json.dumps({n:hashlib.sha256((tmp_path/n).read_bytes()).hexdigest() for n in names}), encoding="utf-8")
    profile=load_product_profile(bundle=tmp_path,data=tmp_path/'user',videos=tmp_path/'redirected-videos')
    assert profile['codec']['ffmpeg']==str(tmp_path/'ffmpeg.exe')
    assert profile['codec']['host']==str(tmp_path/'blackbox_codec_host.exe')
    assert Path(profile['temp_parent']).is_dir() and Path(profile['output_folder']).is_dir()
    assert profile['codec']['fps']==60
    notices=list((tmp_path/'user/third_party').glob('*/corresponding-source.zip'))
    assert len(notices)==1 and notices[0].read_bytes()==(tmp_path/'corresponding-source.zip').read_bytes()
    assert Path(profile['output_folder']).parent==tmp_path/'redirected-videos'

    manifest=json.loads((tmp_path/'manifest.json').read_text(encoding="utf-8"))
    del manifest['avcodec-62.dll']
    (tmp_path/'manifest.json').write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError,match='누락'):
        load_product_profile(bundle=tmp_path,data=tmp_path/'user',videos=tmp_path/'videos')


def test_prepare_builds_and_validates_complete_bundle_from_approved_policy(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    monkeypatch.syspath_prepend(str(ROOT/'packaging'))
    import ffmpeg_source
    root=tmp_path/'repo';(root/'packaging').mkdir(parents=True)
    (root/'packaging/blackbox-product.json').write_bytes((ROOT/'packaging/blackbox-product.json').read_bytes())
    events=[]
    def build(actual_root, work, output):
        events.append('source-build');output.mkdir()
        for name in (*ffmpeg_source.BINARIES, 'corresponding-source.zip', 'THIRD-PARTY-NOTICES.txt',
                     'FFmpeg-LICENSE.txt', 'redistribution.json'):
            (output/name).write_bytes(b'synthetic packaging input')
    def run(command, **kwargs):
        if command[0]=='cmake':
            events.append('native-build')
            if '--build' in command:
                release=Path(command[2])/'Release';release.mkdir(parents=True)
                for name in ('mabinogi_blackbox.dll','blackbox_codec_host.exe'):
                    (release/name).write_bytes(b'synthetic native input')
            return SimpleNamespace(stdout='')
        assert command[1] in ('-version','-hide_banner')
        if command[1]=='-version':
            return SimpleNamespace(stdout='ffmpeg version 8.1.3 --disable-gpl')
        return SimpleNamespace(stdout=LISTINGS[command[2]])
    monkeypatch.setattr(ffmpeg_source,'build',build)
    monkeypatch.setattr(packager.subprocess,'run',run)
    output=tmp_path/'bundle'
    assert packager.prepare(root,output)==['--add-data',str(output)+';blackbox']
    manifest=json.loads((output/'manifest.json').read_text(encoding="utf-8"))
    assert 'mabinogi_blackbox.dll' in manifest and 'corresponding-source.zip' in manifest
    assert json.loads((output/'product.json').read_text(encoding="utf-8"))['codec']['bitrate']==12000000
    assert events==['native-build','native-build','source-build']


LISTINGS = {
    '-encoders': ' V..... h264_nvenc NVIDIA\n V..... h264_amf AMD\n V..... h264_mf hardware encoder\n A..... aac AAC',
    '-bsfs': 'Bitstream filters:\nh264_mp4toannexb\nnull',
    '-demuxers': ' D  concat  Virtual concatenation script\n D  mov,mp4,m4a  QuickTime\n D  rawvideo raw\n D  wav WAV',
    '-muxers': '  E mp4  MP4 (MPEG-4 Part 14)',
}


def test_bundle_requires_concat_bitstream_filter_and_build_enables_every_component():
    # 0.13.0 실사용: 번들 FFmpeg에 h264_mp4toannexb가 없어 concat 저장이 항상 실패했다.
    spec = importlib.util.spec_from_file_location('bundle_checks', ROOT/'packaging/blackbox_bundle.py')
    checks = importlib.util.module_from_spec(spec); spec.loader.exec_module(checks)
    full = {kind.lstrip('-'): text for kind, text in LISTINGS.items()}
    assert checks.missing_components(full) == []
    broken = dict(full, bsfs='Bitstream filters:\nnull')
    assert checks.missing_components(broken) == [('bsfs', 'h264_mp4toannexb')]
    recipe = (ROOT/'packaging/ffmpeg_minimal.sh').read_text(encoding='utf-8')
    flags = {'encoders': 'encoders', 'bsfs': '--enable-bsf=', 'demuxers': '--enable-demuxer=', 'muxers': '--enable-muxer='}
    for kind, names in checks.REQUIRED_COMPONENTS.items():
        line = next(l for l in recipe.splitlines() if flags[kind] in l)
        for name in names:
            assert name in line or (kind == 'encoders' and name in recipe), (kind, name)


def test_msys_native_compiler_path_conversion_is_enabled():
    spec = importlib.util.spec_from_file_location('source_builder', ROOT/'packaging/ffmpeg_source.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    original = {'PATH': 'existing-tools', 'MSYS2_ARG_CONV_EXCL': '*'}
    env = builder.msys_build_env(Path('C:/msys64/usr/bin/bash.exe'), original)
    assert env['MSYS2_ARG_CONV_EXCL'] == ''
    assert env['PATH'].endswith('existing-tools')
    assert original['MSYS2_ARG_CONV_EXCL'] == '*'


@pytest.mark.parametrize("diagnostic_fails", [False, True])
def test_configure_failure_keeps_compiler_diagnostic_and_exit_status(tmp_path, diagnostic_fails):
    import shutil
    import subprocess
    bash = shutil.which('bash')
    assert bash, 'recipe diagnostic test requires bash'
    (tmp_path/'ffbuild').mkdir()
    configure = tmp_path/'configure'
    configure.write_text('#!/usr/bin/env bash\nprintf "compiler probe failed\\n" > ffbuild/config.log\nexit 7\n', encoding="utf-8")
    configure.chmod(0o755)
    import os
    env = dict(os.environ)
    if diagnostic_fails:
        tail = tmp_path/'tail'
        tail.write_text('#!/usr/bin/env bash\nexit 9\n', encoding="utf-8")
        tail.chmod(0o755)
        env['PATH'] = str(tmp_path) + os.pathsep + env['PATH']
    result = subprocess.run([bash, str(ROOT/'packaging/ffmpeg_minimal.sh'), str(tmp_path/'out')],
                            cwd=tmp_path, capture_output=True, text=True, env=env)
    assert result.returncode == 7
    if not diagnostic_fails:
        assert 'compiler probe failed' in result.stderr
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize("failed_call", [1, 2])
def test_native_failure_prevents_ffmpeg_download(tmp_path, monkeypatch, failed_call):
    import subprocess
    monkeypatch.syspath_prepend(str(ROOT/'packaging'))
    import ffmpeg_source
    root=tmp_path/'repo'; (root/'packaging').mkdir(parents=True)
    (root/'packaging/blackbox-product.json').write_text('{}', encoding="utf-8")
    calls=[]
    def run(command, **kwargs):
        calls.append(command)
        if len(calls)==failed_call:
            raise subprocess.CalledProcessError(7, command)
    def forbidden(*args):
        pytest.fail('FFmpeg must not download/build after native failure')
    monkeypatch.setattr(packager.subprocess, 'run', run)
    monkeypatch.setattr(ffmpeg_source, 'build', forbidden)
    with pytest.raises(subprocess.CalledProcessError) as error:
        packager.prepare(root, tmp_path/'bundle')
    assert error.value.returncode==7
    assert len(calls)==failed_call


@pytest.mark.parametrize('change', [dict(max_input_width=None, max_input_height=None),
                                    dict(max_input_width=2560, max_input_height=1440),
                                    dict(max_width=2560, max_height=1440)])
def test_product_profile_requires_1080p_output_and_4k_input(tmp_path, change):
    """사용자 결정: 출력 1080p 고정, 입력 최대 3840×2160(큰 창은 GPU 축소)."""
    policy = json.loads((Path(__file__).resolve().parents[1] / 'packaging' / 'blackbox-product.json').read_text(encoding='utf-8'))
    for key, value in change.items():
        if value is None:
            policy['producer'].pop(key)
        else:
            policy['producer'][key] = value
    names = ['product.json','mabinogi_blackbox.dll','blackbox_codec_host.exe','ffmpeg.exe','ffprobe.exe',
             'redistribution.json','THIRD-PARTY-NOTICES.txt','corresponding-source.zip','FFmpeg-LICENSE.txt',
             'avcodec-62.dll','avformat-62.dll','avutil-60.dll','avfilter-11.dll','swscale-9.dll','swresample-6.dll']
    for name in names: (tmp_path/name).write_bytes(b'{}')
    (tmp_path/'product.json').write_text(json.dumps(policy), encoding="utf-8")
    (tmp_path/'manifest.json').write_text(json.dumps({n: hashlib.sha256((tmp_path/n).read_bytes()).hexdigest() for n in names}), encoding="utf-8")
    with pytest.raises(ValueError, match='1920×1080|3840×2160'):
        load_product_profile(bundle=tmp_path, data=tmp_path/'user', videos=tmp_path/'v')


@pytest.mark.parametrize('codec', [dict(encoder='libx264', candidates=['libx264']),
                                   dict(encoder='h264_mf', candidates=['h264_mf', 'libx264']),
                                   dict(encoder='h264_mf', candidates=['h264_mf', 'h264_nvenc'])])
def test_product_encoder_candidates_are_hardware_only(tmp_path, codec):
    """소프트웨어 인코더 자동 전환 금지: 후보는 하드웨어 인코더만, 마지막이 기본 encoder."""
    policy = json.loads((Path(__file__).resolve().parents[1] / 'packaging' / 'blackbox-product.json').read_text(encoding='utf-8'))
    policy['codec'].update(codec)
    names = ['product.json','mabinogi_blackbox.dll','blackbox_codec_host.exe','ffmpeg.exe','ffprobe.exe',
             'redistribution.json','THIRD-PARTY-NOTICES.txt','corresponding-source.zip','FFmpeg-LICENSE.txt',
             'avcodec-62.dll','avformat-62.dll','avutil-60.dll','avfilter-11.dll','swscale-9.dll','swresample-6.dll']
    for name in names: (tmp_path/name).write_bytes(b'{}')
    (tmp_path/'product.json').write_text(json.dumps(policy), encoding="utf-8")
    (tmp_path/'manifest.json').write_text(json.dumps({n: hashlib.sha256((tmp_path/n).read_bytes()).hexdigest() for n in names}), encoding="utf-8")
    with pytest.raises(ValueError, match='하드웨어 인코더'):
        load_product_profile(bundle=tmp_path, data=tmp_path/'user', videos=tmp_path/'v')


def test_hardware_headers_are_pinned_by_commit_and_content(tmp_path, monkeypatch):
    """NVENC/AMF 헤더: 다른 커밋이나 바뀐 내용이면 빌드 전에 거부한다(압축 파일 바이트와 무관한 내용 해시)."""
    spec = importlib.util.spec_from_file_location('source_builder', ROOT/'packaging/ffmpeg_source.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    def fake_checkout(repo, tag, commit, dest, sparse=()):
        dest = Path(dest)
        if 'nv-codec' in repo:
            (dest/'include/ffnvcodec').mkdir(parents=True)
            (dest/'include/ffnvcodec/nvEncodeAPI.h').write_text('tampered', encoding="utf-8")
        return dest
    monkeypatch.setattr(builder, '_git_checkout', fake_checkout)
    with pytest.raises(ValueError, match='nv-codec-headers content SHA256 mismatch'):
        builder.stage_hardware_headers(tmp_path, tmp_path/'deps')
    assert not (tmp_path/'deps').exists()
    a, b = tmp_path/'a', tmp_path/'b'
    for d, text in ((a, 'x'), (b, 'y')):
        (d/'sub').mkdir(parents=True); (d/'sub/h.h').write_text(text, encoding="utf-8")
    assert builder.tree_digest(a) != builder.tree_digest(b) and len(builder.tree_digest(a)) == 64
    # 요구 버전(FFmpeg 8.1.3 configure): ffnvcodec >= 12.1.14.0, AMF >= 1.4.36
    assert builder.NVCODEC_TAG == 'n12.1.14.0' and builder.AMF_TAG == 'v1.4.36'


def test_build_recipe_enables_vendor_encoders_only_with_pinned_headers():
    recipe = (ROOT/'packaging/ffmpeg_minimal.sh').read_text(encoding='utf-8')
    assert '--disable-nonfree' in recipe and '--disable-gpl' in recipe  # 라이선스 설정 유지
    assert '--enable-nvenc --enable-amf' in recipe and 'encoders="h264_nvenc,h264_amf,$encoders"' in recipe
    product = json.loads((ROOT/'packaging/blackbox-product.json').read_text(encoding='utf-8'))
    assert product['codec']['candidates'] == ['h264_nvenc', 'h264_amf', 'h264_mf']


def test_header_checkout_keeps_lf_even_with_global_autocrlf(tmp_path, monkeypatch):
    """0.11.4 검증 실패: Windows Git 기본값 core.autocrlf=true가 .gitattributes 없는 헤더를 CRLF로 받아
    내용 해시가 달라졌다. 전역 autocrlf=true 환경을 만들어 로컬 저장소로 같은 경로를 재현한다(네트워크 없음)."""
    import shutil, subprocess
    if not shutil.which('git'):
        pytest.skip('git 필요')
    spec = importlib.util.spec_from_file_location('source_builder', ROOT/'packaging/ffmpeg_source.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    origin = tmp_path/'origin'
    (origin/'include/AMF').mkdir(parents=True)
    (origin/'include/AMF/Version.h').write_bytes(b'#define A 1\n#define B 2\n')
    (origin/'LICENSE.txt').write_bytes(b'MIT\n')
    git = lambda *a, cwd=origin: subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()
    git('init', '-q'); git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'init')
    git('add', '.'); git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'headers'); git('tag', 'v1')
    commit = git('rev-parse', 'HEAD')
    expected = builder.tree_digest(origin/'include')
    config = tmp_path/'gitconfig'
    config.write_text('[core]\n\tautocrlf = true\n[protocol "file"]\n\tallow = always\n', encoding="utf-8")
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(config))
    for sparse in ((), ('/include', '/LICENSE.txt')):  # nv(일반)·AMF(sparse) 두 경로 모두
        dest = tmp_path/('clone-sparse' if sparse else 'clone')
        builder._git_checkout(origin.as_uri(), 'v1', commit, dest, sparse=sparse)
        assert b'\r\n' not in (dest/'include/AMF/Version.h').read_bytes()
        assert builder.tree_digest(dest/'include') == expected


def test_tree_digest_order_does_not_depend_on_windows_case_insensitive_paths(tmp_path, monkeypatch):
    """0.11.4 3차 검증 실패: Windows의 Path 비교(대소문자 무시)로 파일 순서가 바뀌어 AMF 해시가 달랐다."""
    import pathlib
    spec = importlib.util.spec_from_file_location('source_builder', ROOT/'packaging/ffmpeg_source.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    for name in ('AB.h', 'Aa.h', 'sub/AMFXInput.h', 'sub/Ambisonic2SRenderer.h'):
        (tmp_path/name).parent.mkdir(parents=True, exist_ok=True); (tmp_path/name).write_text(name, encoding="utf-8")
    linux = builder.tree_digest(tmp_path)

    class WindowsLikePath(type(pathlib.Path())):
        """WindowsPath처럼 대소문자를 무시해 비교하는 Path(Linux에서 Windows 정렬을 흉내)."""
        def __lt__(self, other):
            return str(self).lower() < str(other).lower()
    assert sorted([WindowsLikePath(tmp_path/'AB.h'), WindowsLikePath(tmp_path/'Aa.h')])[0].name == 'Aa.h'
    monkeypatch.setattr(builder, 'Path', WindowsLikePath)
    assert builder.tree_digest(tmp_path) == linux
