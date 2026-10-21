"""Narrow shell-boundary model and subprocess-error probes, not native Windows tests."""
import re
from types import SimpleNamespace
from unittest.mock import patch
import uuid

import pytest

from mabinogi_addon.system.optimization import WindowsOptimization


GUID = '12345678-1234-1234-1234-123456789abc'


@pytest.mark.parametrize('raw', [GUID, GUID.upper(), '{' + GUID.upper() + '}'])
def test_enumerated_adapter_matches_generated_string_predicate(raw):
    backend = WindowsOptimization()
    with patch.object(backend, '_ps', return_value=dict(Name='Ethernet', InterfaceGuid=raw, ifIndex=7)):
        normalized = backend.adapters()[0]['InterfaceGuid']
    assert uuid.UUID(raw) == uuid.UUID(normalized)
    script = backend._adapter(normalized)
    # Only model the exact current predicate, not a general PowerShell evaluator.
    predicate = re.search(r"\[string\]\$_\.InterfaceGuid -eq '([^']+)'", script)
    assert predicate is not None, 'Generated predicate changed; review this narrow model before reuse.'
    selected = raw.casefold() == predicate.group(1).casefold()
    assert selected, dict(raw=raw, stored=normalized, predicate=predicate.group(0))


def test_distinct_shell_failures_leave_distinguishable_diagnostics(caplog):
    backend = WindowsOptimization()
    diagnostics = []
    for code, message in [(1, b'adapter unavailable'), (5, b'Access is denied')]:
        caplog.clear()
        with patch.object(backend, '_windows'), patch(
                'mabinogi_addon.system.optimization.subprocess.run',
                return_value=SimpleNamespace(returncode=code, stdout=b'', stderr=message)):
            with pytest.raises(OSError) as error:
                backend._ps('read-only probe')
        diagnostics.append((str(error.value), error.value.errno, caplog.text))
    assert diagnostics[0] != diagnostics[1], diagnostics
