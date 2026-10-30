"""테마 개인화 색 계산(테마 개인화 명세 5절·8절): 프리셋 전수 + 무작위 배경·강조 대비, 상태색 색조 유지, 잘못된 값 기본값."""
import colorsys
import random

import pytest

from mabinogi_addon import theme_colors as tc

STATUS = ("ok", "warn", "danger")


def _hue(value):
    r, g, b = tc.parse(value)
    return colorsys.rgb_to_hls(r / 255, g / 255, b / 255)[0]


def _check(result):
    base, frame, names = result["roles"]["window"], result["frame"], result["names"]
    assert tc.contrast(result["roles"]["text"], base) >= tc.BODY  # 본문 4.5:1
    for name in ("muted", "ok", "warn", "danger", "accent-soft"):
        assert tc.contrast(names[name], base) >= tc.OTHER, name  # 보조·상태·2단 탭 3:1
    assert tc.contrast(names["accent"], base) >= tc.OTHER  # 내용 칸의 강조(잠금됨·스위치·링크)
    assert tc.contrast(result["on_frame"]["accent"], frame) >= tc.OTHER  # 틀 위 1단 선택 탭
    other = "#FFFFFF" if names["on-accent"] == "#062F28" else "#062F28"
    assert tc.contrast(names["on-accent"], names["accent"]) >= tc.contrast(other, names["accent"])  # 대비가 큰 쪽
    for name, value in result["on_frame"].items():
        if name != "text":
            assert tc.contrast(value, frame) >= tc.OTHER, name  # 틀 위 탭 글자·상태색
    assert tc.contrast(result["frame_text"], frame) >= 4.0  # 흰/검은 글자 중 큰 쪽
    for name in STATUS:  # 상태색은 색조 유지(주황은 주황, 빨강은 빨강)
        start = tc.TONE_NAMES[result["tone"]][name]
        assert abs(_hue(names[name]) - _hue(start)) < 0.02, (name, names[name])
    assert names["brand"] == "#3A0729"
    values = [v.upper() for k, v in names.items()]
    assert len(set(values)) == len(values)  # 이름끼리 값이 겹치지 않음(다시 칠하기용)


@pytest.mark.parametrize("content", tc.CONTENT_TONES)
def test_every_preset_pair_meets_contrast(content):
    for _, bg in tc.BG_PRESETS:
        for _, accent in tc.ACCENT_PRESETS:
            _check(tc.compute(bg, accent, content))


def test_thousands_of_random_pairs_meet_contrast():
    rng = random.Random(20261030)
    for _ in range(3000):
        bg = tc.to_hex([rng.randrange(256) for _ in range(3)])
        accent = tc.to_hex([rng.randrange(256) for _ in range(3)])
        _check(tc.compute(bg, accent, rng.choice(tc.CONTENT_TONES)))


def test_auto_tone_and_mixed_backgrounds_follow_spec():
    assert tc.compute("#FF8FB1", "#00C9A2")["roles"]["window"] == "#FFEBF1"  # 명세 예: 연한 핑크
    assert tc.compute("#5B3FA0", "#00C9A2")["roles"]["window"] == "#241E32"
    assert tc.compute("#A5D8FF", "#00C9A2")["tone"] == "light" and tc.compute("#141A26", "#38BDF8")["tone"] == "dark"
    sky = tc.compute("#A5D8FF", "#00C9A2")
    assert sky["adjusted"] and tc.luminance(sky["names"]["accent"]) < tc.luminance("#00C9A2")  # 밝은 하늘에서 민트 → 진한 청록
    assert tc.compute("#C2185B", "#00C9A2", "light")["tone"] == "light"  # 사용자가 정한 톤 그대로


def test_reset_values_look_like_dark_theme_and_bad_values_fall_back():
    default = tc.compute(**tc.DEFAULT)
    assert default["tone"] == "dark" and default["names"]["accent"] == "#00C9A2" and not default["adjusted"]
    assert default["names"] == tc.TONE_NAMES["dark"]  # 되돌리기 = 다크 테마와 같은 이름 색
    bad = tc.compute("not-a-color", "#12", "sideways")
    assert bad["background"] == "#202020" and bad["accent_input"] == "#00C9A2" and bad["content"] == "auto"


def test_dark_light_system_palette_values_are_unchanged():
    """개인화를 쓰지 않으면 0.29.0 값 그대로(명세 8절)."""
    from mabinogi_addon.ui import palette
    palette.set_custom(None)
    for name, (dark, light) in palette.COLORS.items():
        assert palette.color(name, dark=True) == dark and palette.color(name, dark=False) == light
    assert tc.TONE_NAMES["dark"] == {k: v[0] for k, v in palette.COLORS.items()}
    assert tc.TONE_NAMES["light"] == {k: v[1] for k, v in palette.COLORS.items()}
