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


# 블랙박스가 실행 중에 쓰는 FFmpeg 구성 요소(한곳에서 관리). ffmpeg_minimal.sh가 모두 켜고, prepare가 빌드 결과를
# `ffmpeg -<종류>` 목록으로 확인한다. 시스템 ffmpeg를 쓰는 회귀 테스트로는 번들 누락을 잡지 못한다(0.13.0 저장 실패:
# concat 저장이 h264_mp4toannexb를 자동 삽입하는데 --disable-everything으로 빠져 있었다).
REQUIRED_COMPONENTS = {
    'encoders': ('h264_nvenc', 'h264_amf', 'h264_mf', 'aac'),
    'bsfs': ('h264_mp4toannexb',),
    'demuxers': ('concat', 'mov', 'rawvideo', 'wav'),
    'muxers': ('mp4',),
}


def missing_components(listings):
    """{'encoders': `ffmpeg -encoders` 출력, ...} → 빠진 (종류, 이름) 목록."""
    missing = []
    for kind, names in REQUIRED_COMPONENTS.items():
        tokens = {token for line in listings.get(kind, '').splitlines() for token in line.replace(',', ' ').split()}  # 'mov,mp4,m4a'
        missing += [(kind, name) for name in names if name not in tokens]
    return missing


# 번들 ffmpeg가 인자 해석 단계에서 거부하는 표시(0.15.0: libx264 전용 -sc_threshold로 상주 인코더가 매번 시작 실패).
OPTION_ERRORS = ('Unrecognized option', 'Option not found', 'Error splitting the argument list')


def stream_option_failures(ffmpeg, codec, segment_frames, run=None):
    """하드웨어 후보마다 제품의 상주 인코더 명령을 빈 입력으로 실행해, 옵션을 모르는 후보를 [(후보, stderr)]로 돌려준다.

    GPU 없는 빌드 러너에서는 인코더 초기화가 실패할 수 있지만 그건 허용한다(옵션 해석은 그보다 먼저 일어난다).
    입력이 비어 있어 장치·화면을 쓰지 않는다."""
    from types import SimpleNamespace
    from mabinogi_addon.blackbox_codec import FFmpegEncoder, _PROBE_SIZE
    encoder = FFmpegEncoder.__new__(FFmpegEncoder)
    encoder.settings = SimpleNamespace(ffmpeg=Path(ffmpeg), fps=codec['fps'], bitrate=codec['bitrate'], audio_bitrate=None)
    run = run or subprocess.run
    failures = []
    for candidate in codec.get('candidates') or [codec['encoder']]:
        command = encoder.stream_command(*_PROBE_SIZE, segment_frames, encoder=candidate)
        result = run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
        stderr = result.stderr or b''
        stderr = stderr.decode('utf-8', 'replace') if isinstance(stderr, bytes) else stderr  # 콘솔 코드페이지 무관
        if any(marker in stderr for marker in OPTION_ERRORS):
            failures.append((candidate, stderr.strip()))
    return failures


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
    listings = {kind: subprocess.run([str(output / 'ffmpeg.exe'), '-hide_banner', '-' + kind],
                                     check=True, capture_output=True, text=True, timeout=15).stdout
                for kind in REQUIRED_COMPONENTS}
    missing = missing_components(listings)
    if missing:
        raise ValueError('required FFmpeg components were not built: '
                         + ', '.join(f'{kind[:-1]} {name}' for kind, name in missing))
    import sys
    sys.path.insert(0, str(root / 'src'))
    try:
        product = json.loads(policy.read_text(encoding='utf-8'))
        failures = stream_option_failures(output / 'ffmpeg.exe', product['codec'], product['producer']['segment_frames'])
    finally:
        sys.path.pop(0)
    if failures:
        raise ValueError('bundled FFmpeg rejects the blackbox stream encoder options: '
                         + '; '.join(f'{name}: {text[-300:]}' for name, text in failures))
    (output / 'ffmpeg-build.txt').write_text(info + '\n' + '\n'.join(listings.values()), encoding='utf-8')
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
