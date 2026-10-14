"""Opt-in Linux reproduction of two Windows I/O failure conditions.

Use PYTHONUTF8=0 and put this directory in PYTHONPATH for verification only.
This is not Windows execution and must not be enabled as a production/CI fix.
"""

import builtins
import io
import os

import cv2


def _cp1252_open(original):
    def open_file(file, mode="r", buffering=-1, encoding=None, errors=None,
                  newline=None, closefd=True, opener=None):
        if "b" not in mode and encoding in (None, "locale"):
            encoding = "cp1252"
        return original(file, mode, buffering, encoding, errors, newline, closefd, opener)
    return open_file


builtins.open = _cp1252_open(builtins.open)
io.open = _cp1252_open(io.open)
_imread = cv2.imread
_imwrite = cv2.imwrite


def _windows_imread(filename, *args, **kwargs):
    if not os.fsdecode(filename).isascii():
        return None
    return _imread(filename, *args, **kwargs)


cv2.imread = _windows_imread


def _windows_imwrite(filename, *args, **kwargs):
    if not os.fsdecode(filename).isascii():
        return False
    return _imwrite(filename, *args, **kwargs)


cv2.imwrite = _windows_imwrite
