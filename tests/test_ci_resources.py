from pathlib import Path
import os
import subprocess
import sys
import time

import pytest
import yaml

from scripts import ci_resources

ROOT = Path(__file__).resolve().parents[1]


def test_sample_keeps_top_processes_and_cgroup_limits_without_command_arguments(tmp_path, monkeypatch):
    cgroup = tmp_path/'cgroup'
    group = cgroup/'owned'
    group.mkdir(parents=True)
    proc = tmp_path/'proc/self'
    proc.mkdir(parents=True)
    (proc/'cgroup').write_text('0::/owned\n', encoding='utf-8')
    for name, value in [('memory.current', '1234'), ('memory.max', '4096'),
                        ('memory.events', 'oom 2\noom_kill 1')]:
        (group/name).write_text(value, encoding='utf-8')
    calls = []
    def run(command, **kw):
        calls.append((command, kw))
        return subprocess.CompletedProcess(command, 0, '\n'.join(f'process-{n}' for n in range(100)), '')
    monkeypatch.setattr(ci_resources.subprocess, 'run', run)
    lines = []
    ci_resources.sample(proc=proc.parent, cgroups=cgroup, emit=lines.append)
    output = '\n'.join(lines)
    assert 'memory.current=1234' in output and 'memory.max=4096' in output
    assert 'oom_kill 1' in output
    processes = next(line for line in lines if 'processes exit=' in line)
    assert 'process-15' in processes and 'process-16' not in processes
    assert calls[-1][0] == ['ps', '-eo', 'pid,ppid,rss,pcpu,etime,comm', '--sort=-rss']
    assert all(kw['timeout'] == 3 for _, kw in calls)


@pytest.mark.parametrize('error', [FileNotFoundError(), subprocess.TimeoutExpired('free', 3)])
def test_unavailable_sample_does_not_hide_the_other_measurements(tmp_path, monkeypatch, error):
    def run(*args, **kw):
        raise error
    monkeypatch.setattr(ci_resources.subprocess, 'run', run)
    lines = []
    ci_resources.sample(proc=tmp_path, cgroups=tmp_path, emit=lines.append)
    output = '\n'.join(lines)
    assert all(name+' unavailable=' in output for name in ('memory','disk','processes'))
    assert 'memory.events unavailable' in output


def test_cgroup_path_cannot_escape_the_configured_mount(tmp_path, monkeypatch):
    (tmp_path/'self').mkdir()
    (tmp_path/'self/cgroup').write_text('0::/../../private\n', encoding='utf-8')
    monkeypatch.setattr(ci_resources.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess([], 0, '', ''))
    lines = []
    ci_resources.sample(proc=tmp_path, cgroups=tmp_path/'mount', emit=lines.append)
    assert not any('cgroup=../' in line for line in lines)


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux CI process groups')
@pytest.mark.parametrize('exit_code', [0, 7])
def test_workflow_trap_reaps_sampler_group_and_preserves_regression_result(tmp_path, exit_code):
    workflow = yaml.load((ROOT/'.github/workflows/windows.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    step = next(s for s in workflow['jobs']['regression']['steps'] if s.get('id') == 'unit')
    producer = tmp_path/'sampler.py'
    ready = tmp_path/'ready'
    producer.write_text(
        'import os,sys,subprocess,threading\nfrom pathlib import Path\n'
        'child=subprocess.Popen([sys.executable,"-c","import threading; threading.Event().wait(30)"])\n'
        f'Path({str(ready)!r}).write_text(str(os.getpid())+","+str(child.pid),encoding="utf-8")\n'
        'threading.Event().wait(30)\n', encoding='utf-8')
    fake_uv = tmp_path/'uv'
    fake_uv.write_text(
        f'#!{sys.executable}\nimport sys,time\nfrom pathlib import Path\n'
        'deadline=time.monotonic()+3\n'
        f'while not Path({str(ready)!r}).exists():\n'
        '    assert time.monotonic()<deadline\n    time.sleep(.01)\n'
        f'sys.exit({exit_code})\n', encoding='utf-8')
    fake_uv.chmod(0o755)
    script = step['run'].replace('setsid .venv/bin/python -u -m scripts.ci_resources &',
                                 f'setsid "{sys.executable}" -u "{producer}" &')
    env = os.environ.copy()
    env['PATH'] = str(tmp_path) + os.pathsep + env['PATH']
    result = subprocess.run(['bash', '-c', script], env=env, cwd=ROOT,
                            capture_output=True, text=True, timeout=8)
    assert result.returncode == exit_code, result.stdout+result.stderr
    for pid in map(int, ready.read_text(encoding='utf-8').split(',')):
        path = Path(f'/proc/{pid}/stat')
        deadline = time.monotonic()+2
        while path.exists() and path.read_text(encoding='utf-8').split(') ', 1)[1][0] != 'Z':
            assert time.monotonic() < deadline, f'sampler process still running: {pid}'
            time.sleep(.01)
