"""Policy preconditions must not be mistaken for dialogue or OCR failures."""

from pathlib import Path

import pytest

from mabinogi_addon import config, feature_access, image_io
from test_support.regressions.tuarim_low_range import pipeline, sample, hundred


@pytest.mark.parametrize('user',[None, {'id':'ordinary'}])
@pytest.mark.parametrize('case,expected',[('16',16),('19',19),('100',None)])
def test_reader_display_requires_creator_but_keeps_real_values(pipeline,monkeypatch,user,case,expected):
    pump,d = pipeline
    if case == '16':
        image = sample('v06_7466.png')
    elif case == '100':
        image = hundred()
    else:
        source = image_io.imread(Path(__file__).parent/'data'/'스크린샷 2026-10-18 124011.png')
        assert source is not None
        image = source[85:101,1265:1307].copy()
    monkeypatch.setattr(config,'load_discord_user',lambda:user)
    d._apply_gate()
    assert not d.percent_requested()
    assert d._percent_control.isHidden()
    with pytest.raises(AssertionError):
        pump(image)
    monkeypatch.setattr(config,'load_discord_user',lambda:{'id':feature_access.CREATOR_DISCORD_ID})
    d._apply_gate()
    d._percent_control.setChecked(False)
    d._percent_control.setChecked(True)
    assert d.percent_requested()
    result = pump(image)
    assert result['overlay'] == expected
    if expected is None:
        assert '--%' in result['label']
    else:
        assert result['raw'] == result['stable'] == expected
