from zipfile import ZipFile
from pathlib import Path

import cv2
import numpy as np
import pytest

from mabinogi_addon.detect.halo_timer import read_seconds
from scripts.build_halo_templates import TRAIN

TIMES='''14:41 14:39 14:38 14:37 14:36 14:35 14:34 14:33 14:32 14:31
14:29 14:28 14:27 14:26 14:24 14:23 14:22 14:21 14:20 14:19
14:17 14:16 14:15 14:14 14:13 14:12 14:11 14:09 14:08 14:07
14:06 14:05 14:03 13:47 13:45 13:44 13:43 13:42 13:40 13:39
13:38 13:37 13:36 13:34 13:33 13:32 13:31 13:30 13:28 13:27
13:26 13:25 13:24 13:23 13:22 13:21 13:20 13:18 13:17 13:16
13:15 13:13 13:12 13:11 13:10 13:09 13:07 13:06 13:05 13:04
13:03 13:02 13:01 13:00'''.split()
ROOT=Path(__file__).resolve().parents[1]


def frame(index):
    with ZipFile(ROOT/'tests/data/0058.zip') as archive:
        return cv2.imdecode(np.frombuffer(archive.read(f'{index:04}/frame.png'),np.uint8),cv2.IMREAD_COLOR)


@pytest.mark.parametrize('index,text',list(enumerate(TIMES,1)))
def test_qa_raw_timer(index,text):
    minutes,seconds=map(int,text.split(':'))
    observed=read_seconds(frame(index))
    # Hold the ambiguous frame; do not substitute clock predictions or its QA label.
    assert observed == (None if index==16 else minutes*60+seconds)


def test_training_and_holdout_are_separate():
    assert len(TRAIN)==8 and '0016' not in TRAIN
    assert len(TIMES)==74


def test_no_timer_is_not_zero():
    assert read_seconds(frame(75)) is None
    assert read_seconds(np.zeros((42,119,3),np.uint8)) is None
    assert read_seconds(np.full((42,119,3),255,np.uint8)) is None


def test_ambiguous_two_timers_are_rejected():
    assert read_seconds(np.concatenate([frame(1),frame(1)],axis=1)) is None


@pytest.mark.parametrize('bad',[None,np.zeros((3,3),np.uint8),np.zeros((42,119,4),np.uint8)])
def test_malformed_input_is_held(bad):
    assert read_seconds(bad) is None
