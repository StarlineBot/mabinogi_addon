"""Spec extension preserves packaging settings and fails on upstream contract changes."""

import ast
import os
from pathlib import Path
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def builder():
    return runpy.run_path(str(ROOT / "packaging/build_windows.py"))


def test_spec_extension_preserves_all_other_nodes_and_keeps_positional_image_first(
    builder, tmp_path
):
    source = """
from PyInstaller.utils.hooks import collect_all
assets = [('C:/app/assets', 'assets')]
a = Analysis(['C:/app/entry.py'], datas=assets, hiddenimports=['pyi_splash', 'win32gui'])
splash = Splash('C:/app/startup.png', binaries=a.binaries, datas=a.datas)
exe = EXE(a.scripts, splash, splash.binaries, a.binaries, a.datas,
          name='mabinogi-addon', console=False, uac_admin=False,
          version='C:/app/version.txt', icon=['C:/app/logo.ico'])
"""
    path = tmp_path / "test.spec"
    path.write_text(source, encoding="utf-8")
    before = ast.parse(source)
    builder["extend_spec"](path, ROOT)
    after = ast.parse(path.read_text(encoding="utf-8"))
    # Five preamble statements import/alias our spec-local class.
    original = after.body[-len(before.body) :]
    expected = before.body[-2].value
    expected.keywords.append(
        ast.keyword(arg="minify_script", value=ast.Constant(False))
    )
    assert [ast.dump(node) for node in original] == [
        ast.dump(node) for node in before.body
    ]
    assert "Splash = splash_type(Splash, messages=MESSAGES)" in path.read_text(
        encoding="utf-8"
    )
    assert "probe=True" not in path.read_text(encoding="utf-8")
    compile(path.read_text(encoding="utf-8"), str(path), "exec")


@pytest.mark.parametrize(
    "source", ["a = Analysis([])", 's = Splash("a"); other = Splash("b")']
)
def test_changed_spec_contract_fails_without_writing_partial_file(
    builder, tmp_path, source
):
    path = tmp_path / "changed.spec"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(RuntimeError, match="contract changed"):
        builder["extend_spec"](path, ROOT)
    assert path.read_text(encoding="utf-8") == source


def test_build_uses_temporary_spec_with_absolute_assets_and_preserves_existing_flags(
    builder, tmp_path, monkeypatch
):
    root = tmp_path / "app with spaces"
    root.mkdir()
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs == dict(cwd=root, check=True)
        if command[2] == "PyInstaller.utils.cliutils.makespec":
            output = (
                Path(command[command.index("--specpath") + 1]) / "mabinogi-addon.spec"
            )
            output.write_text(
                'a = Analysis([])\nsplash = Splash("image.png", datas=a.datas)',
                encoding="utf-8",
            )
        else:
            spec = Path(command[-1])
            assert spec.exists() and "splash_type" in spec.read_text(encoding="utf-8")
            compile(spec.read_text(encoding="utf-8"), str(spec), "exec")

    monkeypatch.setattr(builder["subprocess"], "run", run)
    builder["build"](root)
    generated = commands[0]
    assert (
        "--onefile" in generated
        and "--windowed" in generated
        and "--uac-admin" in generated  # 항상 관리자 실행(UIPI 단축키 수신, 0.11.3 사용자 결정)
    )
    assert generated[generated.index("--splash") + 1] == str(
        root / "src/mabinogi_addon/assets/startup_background.png"
    )
    assert generated[generated.index("--version-file") + 1] == str(
        root / "packaging/version_info.txt"
    )
    assert generated[generated.index("--icon") + 1] == str(root / "packaging/logo.ico")
    data = [
        generated[index + 1]
        for index, value in enumerate(generated)
        if value == "--add-data"
    ]
    assert data == [
        str(root / "src/mabinogi_addon/assets") + os.pathsep + "assets",
        str(root / "src/mabinogi_addon/detect/templates")
        + os.pathsep
        + "mabinogi_addon/detect/templates",
    ]
    assert "dxcam" in generated and "comtypes" in generated and "certifi" in generated
    assert "pyi_splash" in generated and "win32gui" in generated
    assert generated[-1] == str(root / "packaging/entry.py")
    assert not Path(commands[1][-1]).exists()


def test_existing_main_build_entry_calls_bundle_preparation_before_pyinstaller(builder, tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    root = tmp_path / 'repo'
    root.mkdir()
    events = []
    def prepare(actual_root, output):
        assert actual_root == root
        events.append('prepare-native-and-codec')
        return ['--add-data', str(output) + ';blackbox']
    def build(actual_root, *, blackbox_options):
        assert actual_root == root and blackbox_options[-1].endswith(';blackbox')
        events.append('pyinstaller')
        (root/'dist').mkdir()
        (root/'dist/mabinogi-addon.exe').write_bytes(b'mocked exe')
    namespace = builder['main'].__globals__
    monkeypatch.setitem(namespace, '__file__', str(root/'packaging/build_windows.py'))
    monkeypatch.setitem(namespace, 'build', build)
    monkeypatch.setitem(sys.modules, 'blackbox_bundle', SimpleNamespace(prepare=prepare))
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(sys, 'argv', ['build_windows.py', '--version', '0.11.0'])
    monkeypatch.setattr(builder['subprocess'], 'run', lambda *a, **k: events.append('version'))
    builder['main']()
    assert events == ['version', 'prepare-native-and-codec', 'pyinstaller']
