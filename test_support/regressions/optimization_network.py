"""Selected GUID representation and safe shell failure contracts.

The original QA's regex modeled only the removed string predicate. Structural
GUID comparisons are checked here; native PowerShell execution lives in tests/windows.
"""
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from mabinogi_addon.system.optimization import WindowsOptimization

GUID='12345678-1234-1234-1234-123456789abc'


@pytest.mark.parametrize('raw',[GUID,GUID.upper(),'{'+GUID.upper()+'}'])
def test_enumerated_adapter_matches_structural_predicate(raw):
    b=WindowsOptimization()
    with patch.object(b,'_ps',return_value=dict(Name='Ethernet',InterfaceGuid=raw,ifIndex=7)):
        normalized=b.adapters()[0]['InterfaceGuid']
    assert normalized==GUID
    script=b._adapter(normalized)
    assert "$wanted=[guid]'"+GUID+"'" in script
    assert '[guid]::TryParse([string]$_.InterfaceGuid,[ref]$parsed)' in script
    assert '$parsed -eq $wanted' in script and '$a.Count -ne 1' in script
    assert '[string]$_.InterfaceGuid -eq' not in script
    assert 'Select-Object -First' not in script


def test_distinct_shell_failures_leave_distinguishable_diagnostics(caplog):
    b=WindowsOptimization();diagnostics=[]
    for code,message in [(1,b'adapter unavailable'),(5,b'Access is denied')]:
        caplog.clear()
        with patch.object(b,'_windows'),patch('mabinogi_addon.system.optimization.subprocess.run',
                return_value=SimpleNamespace(returncode=code,stdout=b'',stderr=message)):
            with pytest.raises(OSError) as error: b._ps('read-only probe')
        diagnostics.append((str(error.value),error.value.errno,caplog.text))
    assert diagnostics[0]!=diagnostics[1],diagnostics
