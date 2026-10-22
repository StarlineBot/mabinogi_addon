"""Bounded first-error tracebacks to the controller console, not public journals."""

LIMIT = 3
MAX_TRACE_BYTES = 32 * 1024


class LiveErrors:
    def __init__(self, console):
        self.console = console
        self.seen = set()

    def report(self, node, phase, traceback):
        key = (node, phase)
        if key in self.seen or len(self.seen) >= LIMIT:
            return
        self.seen.add(key)
        # Exclude captured stdout/stderr and locals; keep both traceback ends.
        body = str(traceback).encode('utf-8', errors='replace')
        if len(body) > MAX_TRACE_BYTES:
            body = body[:24*1024] + b'\n[traceback truncated]\n' + body[-8*1024:]
        header = f'\n[ci-first-error] phase={phase} node={node[:512]}\n'.encode('utf-8', errors='replace')
        data = header + body + b'\n[ci-first-error-end]\n'
        for offset in range(0, len(data), 8192):
            self.console.send(data[offset:offset+8192])
        self.console.flush()
