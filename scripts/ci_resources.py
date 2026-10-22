"""Read-only Linux CI sampler. Its process group is owned by the workflow step."""

from datetime import datetime, timezone
from pathlib import Path
import subprocess
import time

COMMANDS = (
    ('memory', ['free', '-m']),
    ('disk', ['df', '-h', '/tmp', '.']),
    ('processes', ['ps', '-eo', 'pid,ppid,rss,pcpu,etime,comm', '--sort=-rss']),
)


def sample(*, proc=Path('/proc'), cgroups=Path('/sys/fs/cgroup'), emit=print):
    emit('[ci-resources] ' + datetime.now(timezone.utc).isoformat())
    for name, command in COMMANDS:
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=3)
            text = result.stdout[:8192]
            if name == 'processes':
                text = '\n'.join(text.splitlines()[:16])
            emit(f'[ci-resources] {name} exit={result.returncode}\n{text}')
        except (OSError, subprocess.TimeoutExpired) as error:
            emit(f'[ci-resources] {name} unavailable={type(error).__name__}')
    locations = [cgroups]
    try:
        for line in (proc/'self/cgroup').read_text(encoding='utf-8').splitlines():
            hierarchy, controllers, relative = line.split(':', 2)
            if hierarchy == '0' and not controllers:
                candidate = cgroups/relative.lstrip('/')
                if candidate.resolve().is_relative_to(cgroups.resolve()) and candidate not in locations:
                    locations.append(candidate)
    except (OSError, ValueError):
        pass
    for location in locations:
        for name in ('memory.current', 'memory.max', 'memory.events'):
            try:
                with (location/name).open(encoding='utf-8') as stream:
                    text = stream.read(2048).strip()
                emit(f'[ci-resources] cgroup={location.relative_to(cgroups)} {name}={text}')
            except OSError:
                emit(f'[ci-resources] {name} unavailable')


def main():
    while True:
        sample(emit=lambda text: print(text, flush=True))
        time.sleep(30)


if __name__ == '__main__':
    main()
