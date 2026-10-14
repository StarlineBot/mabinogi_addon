"""Guard the test inputs against Windows path and default-codepage regressions."""

import ast
import io
import json
from pathlib import Path
import textwrap

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io


def _test_trees():
    for path in sorted(Path(__file__).parent.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        yield path.name, tree
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if ".read_text(" not in node.value and ".write_text(" not in node.value:
                    continue
                try:
                    embedded = ast.parse(textwrap.dedent(node.value))
                except SyntaxError:
                    continue
                yield f"{path.name}:embedded@{node.lineno}", embedded


def test_test_images_use_unicode_safe_io():
    violations = []
    for filename, tree in _test_trees():
        modules, direct = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.asname or "cv2" for alias in node.names if alias.name == "cv2")
            elif isinstance(node, ast.ImportFrom) and node.module == "cv2":
                direct.update(alias.asname or alias.name for alias in node.names
                              if alias.name in ("imread", "imwrite"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (isinstance(func, ast.Name) and func.id in direct or
                    isinstance(func, ast.Attribute) and func.attr in ("imread", "imwrite") and
                    isinstance(func.value, ast.Name) and func.value.id in modules):
                violations.append(f"{filename}:{node.lineno}")
    assert not violations, f"Use image_io for Unicode test paths: {violations}"


def test_test_text_files_declare_encoding():
    violations = []
    for filename, tree in _test_trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in ("read_text", "write_text"):
                continue
            encoding = next((kw.value for kw in node.keywords if kw.arg == "encoding"), None)
            if encoding is None or isinstance(encoding, ast.Constant) and encoding.value is None:
                violations.append(f"{filename}:{node.lineno}")
    assert not violations, f"Declare the text encoding (including subprocess snippets): {violations}"


@pytest.mark.parametrize("flags", [cv2.IMREAD_COLOR, cv2.IMREAD_GRAYSCALE])
def test_unicode_parent_path_does_not_use_native_image_io(tmp_path, monkeypatch, flags):
    directory = tmp_path / "\ud55c\uae00 \uc0ac\uc6a9\uc790"
    directory.mkdir()
    path = directory / "sample.png"
    shape = (20, 30, 3) if flags == cv2.IMREAD_COLOR else (20, 30)
    original = np.random.default_rng(29).integers(0, 256, shape, np.uint8)
    native_imread = cv2.imread
    native_imwrite = cv2.imwrite

    def restricted(filename, *args, **kwargs):
        if not str(filename).isascii():
            return None
        return native_imread(filename, *args, **kwargs)

    monkeypatch.setattr(cv2, "imread", restricted)
    def restricted_write(filename, *args, **kwargs):
        if not str(filename).isascii():
            return False
        return native_imwrite(filename, *args, **kwargs)

    monkeypatch.setattr(cv2, "imwrite", restricted_write)
    assert not restricted_write(str(path), original)
    assert image_io.imwrite(path, original)
    assert restricted(str(path), flags) is None
    np.testing.assert_array_equal(image_io.imread(path, flags), original)


def test_explicit_utf8_survives_cp1252_default(tmp_path, monkeypatch):
    original_open = io.open

    def cp1252_open(file, mode="r", buffering=-1, encoding=None, errors=None,
                    newline=None, closefd=True, opener=None):
        if "b" not in mode and encoding in (None, "locale"):
            encoding = "cp1252"
        return original_open(file, mode, buffering, encoding, errors, newline, closefd, opener)

    monkeypatch.setattr(io, "open", cp1252_open)
    data = {"memo": {"text": "\uba54\ubaa8", "locked": True}}
    settings = tmp_path / "settings.json"
    text = json.dumps(data, ensure_ascii=False)
    with pytest.raises(UnicodeEncodeError):
        settings.write_text(text, encoding="cp1252")
    settings.write_text(text, encoding="utf-8")
    assert json.loads(settings.read_text(encoding="utf-8")) == data
    log = tmp_path / "logs.txt"
    message = "\uc790\ub3d9\ucc3e\uae30 \uc9c4\ub2e8"
    log.write_text(message, encoding="utf-8")
    with pytest.raises(UnicodeDecodeError):
        log.read_text(encoding="cp1252")
    assert log.read_text(encoding="utf-8") == message
