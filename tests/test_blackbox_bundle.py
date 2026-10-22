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
    (tmp_path/'product.json').write_text(json.dumps({'codec':{'encoder':'libx264'},'audio':'process'}))
    manifest={n:hashlib.sha256((tmp_path/n).read_bytes()).hexdigest() for n in names}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
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
    (tmp_path/'product.json').write_text(json.dumps(policy))
    (tmp_path/'manifest.json').write_text(json.dumps({n:hashlib.sha256((tmp_path/n).read_bytes()).hexdigest() for n in names}))
    profile=load_product_profile(bundle=tmp_path,data=tmp_path/'user',videos=tmp_path/'redirected-videos')
    assert profile['codec']['ffmpeg']==str(tmp_path/'ffmpeg.exe')
    assert profile['codec']['host']==str(tmp_path/'blackbox_codec_host.exe')
    assert Path(profile['temp_parent']).is_dir() and Path(profile['output_folder']).is_dir()
    assert profile['codec']['fps']==60
    notices=list((tmp_path/'user/third_party').glob('*/corresponding-source.zip'))
    assert len(notices)==1 and notices[0].read_bytes()==(tmp_path/'corresponding-source.zip').read_bytes()
    assert Path(profile['output_folder']).parent==tmp_path/'redirected-videos'

    manifest=json.loads((tmp_path/'manifest.json').read_text())
    del manifest['avcodec-62.dll']
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
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
        return SimpleNamespace(stdout='ffmpeg version 8.1.3 --disable-gpl' if command[1]=='-version'
                               else ' V..... h264_mf hardware encoder')
    monkeypatch.setattr(ffmpeg_source,'build',build)
    monkeypatch.setattr(packager.subprocess,'run',run)
    output=tmp_path/'bundle'
    assert packager.prepare(root,output)==['--add-data',str(output)+';blackbox']
    manifest=json.loads((output/'manifest.json').read_text())
    assert 'mabinogi_blackbox.dll' in manifest and 'corresponding-source.zip' in manifest
    assert json.loads((output/'product.json').read_text())['codec']['bitrate']==12000000
    assert events==['native-build','native-build','source-build']


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
    configure.write_text('#!/usr/bin/env bash\nprintf "compiler probe failed\\n" > ffbuild/config.log\nexit 7\n')
    configure.chmod(0o755)
    import os
    env = dict(os.environ)
    if diagnostic_fails:
        tail = tmp_path/'tail'
        tail.write_text('#!/usr/bin/env bash\nexit 9\n')
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
    (root/'packaging/blackbox-product.json').write_text('{}')
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
    (tmp_path/'product.json').write_text(json.dumps(policy))
    (tmp_path/'manifest.json').write_text(json.dumps({n: hashlib.sha256((tmp_path/n).read_bytes()).hexdigest() for n in names}))
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
    (tmp_path/'product.json').write_text(json.dumps(policy))
    (tmp_path/'manifest.json').write_text(json.dumps({n: hashlib.sha256((tmp_path/n).read_bytes()).hexdigest() for n in names}))
    with pytest.raises(ValueError, match='하드웨어 인코더'):
        load_product_profile(bundle=tmp_path, data=tmp_path/'user', videos=tmp_path/'v')
