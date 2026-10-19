"""Representative failures from each of the three v0.5.0 release-gate causes."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_creator_dialogue import app, window  # noqa: E402,F401
from scripts.qa_tuarim_low_range_display import pipeline, sample  # noqa: E402,F401
from test_unicode_io_contract import test_test_text_files_declare_encoding as check_encoding  # noqa: E402


def test_dialogue_fixture_reaches_real_dialogue_path(window):
    assert window.creator_dialogue.request(), "Legacy fixture is still on the first-use guide"


def test_percent_fixture_reaches_creator_only_display(pipeline):
    pump, _ = pipeline
    assert pump(sample("v06_7466.png"))["overlay"] == 16


def test_new_collection_test_declares_text_encoding():
    check_encoding()
