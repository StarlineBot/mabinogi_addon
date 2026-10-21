"""Read topology and change only an owned disposable child's affinity on Windows."""
import os
import subprocess
import sys
import pytest
from mabinogi_addon.optimization.session import Recovery
from mabinogi_addon.system.optimization import WindowsOptimization
from mabinogi_addon.system.presentmon import executable

pytestmark = [pytest.mark.windows_integration,
              pytest.mark.skipif(sys.platform!='win32',reason='Requires Windows native APIs')]


def test_owned_child_affinity_write_verify_and_restore(tmp_path):
    backend=WindowsOptimization()
    child=subprocess.Popen([sys.executable,'-c','import sys; sys.stdin.readline()'],stdin=subprocess.PIPE,
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    recovery=None
    try:
        info=backend.process_info(child.pid)
        assert info['same_user'] and info['same_session'] and not info['protected']
        target=info['target']
        original=backend.read('cpu',target)
        first=original & -original
        recovery=Recovery(tmp_path/'child.json',backend,lambda:True)
        recovery.apply('cpu',target,first)
        assert backend.read('cpu',target)==first
        assert recovery.restore()==[]
        assert backend.read('cpu',target)==original
    finally:
        if recovery is not None: recovery.restore()
        if child.stdin: child.stdin.close()
        try: child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill();child.wait(timeout=3)


def test_bundled_collector_exposes_pinned_cli_without_install():
    result=subprocess.run([str(executable()),'--help'],capture_output=True,timeout=5,
                          creationflags=0x08000000)
    assert result.returncode==1  # Upstream PrintUsage exits via ParseCommandLine(false).
    assert b'--process_id' in result.stderr
    assert b'--session_name' in result.stderr


def test_job_close_terminates_only_the_owned_child():
    from mabinogi_addon.system.process_job import ProcessJob
    child=subprocess.Popen([sys.executable,'-c','import sys; sys.stdin.readline()'],stdin=subprocess.PIPE,
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    job=None
    try:
        job=ProcessJob(child.pid)
        assert child.poll() is None
        job.close()
        child.wait(timeout=3)
        assert child.returncode is not None
    finally:
        if job is not None: job.close()
        if child.stdin: child.stdin.close()
        if child.poll() is None:
            child.kill();child.wait(timeout=3)


@pytest.mark.parametrize('raw',[
    '12345678-1234-1234-1234-123456789abc',
    '12345678-1234-1234-1234-123456789ABC',
    '{12345678-1234-1234-1234-123456789ABC}',
])
def test_adapter_structural_lookup_executes_in_powershell(raw):
    """Run the production predicate with synthetic objects; never change a NIC."""
    import uuid
    backend=WindowsOptimization();guid='12345678-1234-1234-1234-123456789abc'
    fake="@([pscustomobject]@{InterfaceGuid='"+raw+"';Name='selected'},[pscustomobject]@{InterfaceGuid='22345678-1234-1234-1234-123456789abc';Name='other'},[pscustomobject]@{InterfaceGuid='bad';Name='invalid'})"
    script=backend._adapter(guid).replace('Get-NetAdapter -Physical',fake)
    result=backend._ps(script+"$a.InterfaceGuid | ConvertTo-Json -Compress",'읽기 전용/식별 계약')
    assert uuid.UUID(result)==uuid.UUID(guid)


@pytest.mark.parametrize('ids',[[],['12345678-1234-1234-1234-123456789abc']*2,
    ['22345678-1234-1234-1234-123456789abc'],['not a guid']])
def test_adapter_missing_duplicate_or_replaced_fails_closed_in_powershell(ids):
    from mabinogi_addon.system.optimization import WindowsCommandError
    backend=WindowsOptimization();guid='12345678-1234-1234-1234-123456789abc'
    fake='@('+','.join("[pscustomobject]@{InterfaceGuid='"+g+"'}" for g in ids)+')'
    script=backend._adapter(guid).replace('Get-NetAdapter -Physical',fake)
    with pytest.raises(WindowsCommandError) as caught: backend._ps(script,'읽기 전용/식별 계약')
    assert caught.value.category==('AdapterAmbiguous' if len(ids)==2 else 'AdapterMissing')


def test_real_adapter_enumeration_and_selected_guid_lookup_are_read_only():
    import uuid
    backend=WindowsOptimization()
    for row in backend.adapters():
        result=backend._ps(backend._adapter(row['InterfaceGuid'])+
            '$a.InterfaceGuid | ConvertTo-Json -Compress','읽기 전용/실제 장치 식별')
        assert uuid.UUID(result)==uuid.UUID(row['InterfaceGuid'])
