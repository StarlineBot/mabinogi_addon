"""합성 영상만 사용하는 수동 기술 검증. 제품 FFmpeg/소프트웨어 인코더 도입이 아니다.

uv run python -m scripts.probe_blackbox_export /tmp/new-blackbox-export-probe
지정 출력 폴더는 없어야 한다. ffmpeg/ffprobe가 PATH에 있어야 하며 외부 소스를 받지 않는다.
"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from mabinogi_addon.blackbox import ReplayBuffer, Segment
from mabinogi_addon.blackbox_export import ExportJob
from mabinogi_addon.blackbox_budget import DiskBudget
from mabinogi_addon.blackbox_queue import ExportQueue
from mabinogi_addon.blackbox_spool import DiskSpool
from mabinogi_addon.blackbox_runtime import BlackboxRuntime
from mabinogi_addon.blackbox_session import BlackboxSession, CaptureContext


def probe(root: Path):
    root.mkdir(parents=True, exist_ok=False)
    commands = []

    def run(command):
        commands.append(command)
        return subprocess.run(command, check=True, capture_output=True, timeout=30).stdout

    def inspect(path):
        return json.loads(run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,r_frame_rate,duration,nb_read_frames',
            '-of', 'json', str(path)]))['streams'][0]

    version = run(['ffmpeg', '-version']).decode().splitlines()[0]
    sources = {name: root / f'{name}.mp4' for name in ('a', 'b')}
    for name, source in sources.items():
        run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'lavfi', '-i',
            f'color=c={"red" if name == "a" else "blue"}:size=320x180:rate=60',
            '-t', '2', '-an', '-c:v', 'libx264', '-threads', '1', '-g', '60', '-bf', '0',
            '-keyint_min', '60', '-sc_threshold', '0', str(source)])

    replay = ReplayBuffer('synthetic', max_bytes=1_000_000, max_segments=10,
                          max_saves=2, retention_us=3_500_000)
    for name, start in (('a', 0), ('b', 7_000_000)):
        replay.append(Segment('synthetic', name, start, start + 2_000_000,
                              sources[name].stat().st_size, '320x180-60-video-only'))
    plan = replay.request_save(9_000_000)
    # 저장 접수 뒤의 자료는 이미 고정한 plan에 포함되지 않아야 한다.
    replay.append(Segment('synthetic', 'later', 9_000_000, 11_000_000, 100,
                          '320x180-60-video-only'))

    def seconds(value):
        return f'{value // 1_000_000}.{value % 1_000_000:06d}'

    def encode(request, sink):
        command = ['ffmpeg', '-v', 'error', '-nostdin']
        filters = []
        for index, part in enumerate(request.slices):
            command += ['-i', str(sources[part.segment.source])]
            filters.append(f'[{index}:v]trim=start={seconds(part.offset_us)}:'
                f'duration={seconds(part.duration_us)},setpts=PTS-STARTPTS[v{index}]')
        filters.append(''.join(f'[v{i}]' for i in range(len(request.slices)))
                       + f'concat=n={len(request.slices)}:v=1:a=0[out]')
        command += ['-filter_complex', ';'.join(filters), '-map', '[out]', '-an',
            '-r', '60', '-fps_mode', 'cfr', '-c:v', 'libx264', '-threads', '1', '-bf', '0',
            '-movflags', 'frag_keyframe+empty_moov+default_base_moof', '-f', 'mp4', 'pipe:1']
        # 작은 고정 합성 자료 전용. 제품 어댑터에서는 유한 큐로 스트림 전송해야 한다.
        sink.write(run(command))

    observed = {}

    def validate(path, request):
        stream = inspect(path)
        assert int(stream['nb_read_frames']) == 210, stream
        assert abs(float(stream['duration']) - request.duration_us / 1_000_000) < 0.001, stream
        run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path), '-f', 'null', '-'])
        observed.update(stream)

    output = root / 'saved.mp4'
    job = ExportJob(plan, output, max_output_bytes=1_000_000)
    # 이 작은 합성 fixture의 예산일 뿐 제품 기본값이 아니다.
    budget = DiskBudget(max_bytes=2_000_000, min_free_bytes=1_000_000, max_entries=4)
    source_tokens = [budget.retain_existing(source) for source in sources.values()]
    queue = ExportQueue(budget, max_workers=1, max_jobs=1, creator_check=lambda: True)
    ticket = queue.submit(job, encode, validate)
    queue.begin_close()
    assert queue.wait_idle(60), 'synthetic encoder did not finish'
    result = queue.acknowledge(ticket)
    assert queue.finish_close()
    for token in source_tokens:
        budget.release(token)
    assert budget.accounted_bytes == 0 and budget.entry_count == 0
    assert result.completed, result
    original_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    duplicate = ExportJob(plan, output, max_output_bytes=1_000_000).run(encode, validate)
    assert not duplicate.completed and hashlib.sha256(output.read_bytes()).hexdigest() == original_hash
    failed_job = ExportJob(plan, root / 'failed.mp4', max_output_bytes=100)

    def fail(request, sink):
        sink.write(b'incomplete encoding')
        raise TimeoutError('synthetic encoder timeout')

    failed = failed_job.run(fail, validate)
    assert not failed.completed and not failed.validated and failed.partial.is_file()
    assert not (root / 'failed.mp4').exists()

    # 승인된 디스크 저장소→세션→1처리/1대기 runtime→원본 정리 전체 연결.
    integrated_budget = DiskBudget(max_bytes=2_000_000, min_free_bytes=1_000_000, max_entries=8)
    spool = DiskSpool(root, integrated_budget)
    integrated_replay = ReplayBuffer('integration', max_bytes=1_000_000, max_segments=10,
                                     max_saves=2, retention_us=3_500_000)
    session = BlackboxSession(integrated_replay, enabled=True, persist_enabled=lambda v: None,
                              creator_check=lambda: True)
    session.update_context(CaptureContext('integration', foreground=True, ready=True))
    for name, start in (('a', 0), ('b', 7_000_000)):
        data = sources[name].read_bytes()
        source = spool.write(lambda sink: sink.write(data), max_bytes=100_000)
        sources[source] = spool.resolve(source)
        session.append(session.capture_permit(), Segment('integration', source, start,
                       start + 2_000_000, len(data), '320x180-60-video-only'))
    runtime = BlackboxRuntime(session, integrated_budget, max_output_bytes=1_000_000,
                              encode=encode, validate=validate, retire=spool.retire,
                              creator_check=lambda: True)
    ticket = runtime.request_save(9_000_000, root / 'runtime-saved.mp4')
    runtime.begin_close()
    assert runtime.queue.wait_idle(60)
    integrated_result = runtime.accept_completed(ticket)
    assert integrated_result.completed and integrated_result.cleanup_error is None
    assert runtime.finish_close()
    spool.close()
    assert integrated_budget.accounted_bytes == 0 and not spool.directory.exists()

    manifest = root / 'copy.ffconcat'
    manifest.write_text('ffconcat version 1.0\nfile a.mp4\ninpoint 0.5\noutpoint 2.0\nfile b.mp4\n')
    copy = root / 'copy.mp4'
    run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-f', 'concat', '-safe', '1',
         '-i', str(manifest), '-c', 'copy', str(copy)])
    copied = inspect(copy)
    report = dict(version=version, requested_us=plan.duration_us, simulated_pause_us=5_000_000,
        exported=observed, copied=copied, duplicate_rejected=True, queue_and_budget_released=True, disk_runtime_completed_and_cleaned=True,
        incomplete_is_success=False, partial=str(failed.partial), sha256=original_hash,
        commands=commands, scope='Linux synthetic video; no capture/audio/Windows/hardware validation')
    (root / 'results.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key != 'commands'}, indent=2))


if __name__ == '__main__':
    probe(Path(sys.argv[1]).absolute())
