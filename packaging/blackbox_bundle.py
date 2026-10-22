"""Build-only blackbox dependencies. No downloads or capture during app startup."""
import json
from pathlib import Path
import shutil
import subprocess

def reviewed_inputs(root):
    policy = root / 'packaging/blackbox-product.json'
    if not policy.is_file():
        raise RuntimeError('Blackbox release blocked: approved blackbox-product.json is required; no validation defaults')
    return policy


def prepare(root, output):
    policy = reviewed_inputs(root)
    from ffmpeg_source import build as build_ffmpeg, digest, VERSION
    native = output.parent / 'blackbox-native-build'
    subprocess.run(['cmake', '-S', str(root / 'native/blackbox'), '-B', str(native),
                    '-A', 'x64'], check=True, cwd=root)
    subprocess.run(['cmake', '--build', str(native), '--config', 'Release', '--parallel', '2'],
                   check=True, cwd=root)
    # Fail on SDK/compiler errors before downloading and building FFmpeg.
    build_ffmpeg(root, output.parent / 'ffmpeg-work', output)
    for name in ('mabinogi_blackbox.dll', 'blackbox_codec_host.exe'):
        shutil.copyfile(native / 'Release' / name, output / name)
    shutil.copyfile(policy, output / 'product.json')
    # Safe executable inspection: no devices, media inputs, or hardware sessions.
    info = subprocess.run([str(output / 'ffmpeg.exe'), '-version'], check=True,
                          capture_output=True, text=True, timeout=15).stdout
    if '--enable-gpl' in info or '--enable-nonfree' in info or '--enable-version3' in info or '--enable-libx264' in info:
        raise ValueError('non-approved FFmpeg license configuration')
    if VERSION not in info:
        raise ValueError('unexpected FFmpeg version')
    encoders = subprocess.run([str(output / 'ffmpeg.exe'), '-hide_banner', '-encoders'],
        check=True, capture_output=True, text=True, timeout=15).stdout
    for name in ('h264_nvenc', 'h264_amf', 'h264_mf'):  # 제품 후보 인코더가 모두 빌드됐는지
        if not any(f' {name} ' in line for line in encoders.splitlines()):
            raise ValueError(f'required hardware encoder {name} was not built')
    (output / 'ffmpeg-build.txt').write_text(info + '\n' + encoders, encoding='utf-8')
    (output / 'manifest.json').write_text(json.dumps({p.name: digest(p) for p in output.iterdir()
        if p.is_file()}, indent=2), encoding='utf-8')
    # Validate all required policy fields before producing an app candidate.
    import sys
    sys.path.insert(0, str(root / 'src'))
    try:
        from mabinogi_addon.blackbox_bundle import load_product_profile
        load_product_profile(bundle=output, data=output.parent / 'profile-check',
                             videos=output.parent / 'videos-check')
    finally:
        sys.path.pop(0)
    return ['--add-data', str(output) + ';blackbox']
