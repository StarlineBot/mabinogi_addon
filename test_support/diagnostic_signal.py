"""Run-scoped loopback notification independent of disk and pytest fd capture."""
import json
import os
import secrets
import socket
import threading

ENVIRONMENT = 'MABINOGI_TEST_FAILURE_CHANNEL'


class FailureChannel:
    def __init__(self, failed, root):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.bind(('127.0.0.1', 0))
            self.socket.settimeout(.1)
        except OSError:
            self.socket.close()
            raise
        self.token = secrets.token_hex(16).encode('ascii')
        self.endpoint = json.dumps(dict(port=self.socket.getsockname()[1],
                                       token=self.token.decode('ascii'), root=str(root)))
        self.stopped = threading.Event()
        self.failed = failed
        self.thread = threading.Thread(target=self._receive, daemon=True)
        self.thread.start()

    def _receive(self):
        while not self.stopped.is_set():
            try:
                data, _ = self.socket.recvfrom(1024)
                if secrets.compare_digest(data, self.token):
                    self.failed.set()
            except socket.timeout:
                continue
            except OSError:
                if not self.stopped.is_set():
                    self.failed.set()
                break

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=1)
        self.socket.close()


def notify_failure(root):
    try:
        endpoint = json.loads(os.environ.get(ENVIRONMENT, '{}'))
        # Synthetic journals and nested supervisors must not signal another run.
        if os.path.normcase(os.path.abspath(endpoint['root'])) != os.path.normcase(os.path.abspath(root)):
            return
        port, token = endpoint['port'], endpoint['token']
        if type(port) is not int or not 0 < port < 65536:
            return
        if not isinstance(token, str) or len(token) != 32:
            return
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as stream:
            stream.settimeout(.2)
            stream.sendto(token.encode('ascii'), ('127.0.0.1', port))
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        # Existing marker, stderr and wall-clock deadlines remain independent fallbacks.
        return
