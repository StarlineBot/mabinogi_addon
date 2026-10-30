"""테마 개인화 색 계산(테마 개인화 명세 5절). Qt와 무관한 순수 함수라 맥에서도 테스트한다.

입력: 고른 배경·강조색, 내용 칸 톤(자동/어둡게/밝게).
출력: 틀(머리줄·1단 탭 줄·홈 배경) 색과 그 위 글자색, 내용 칸 바탕과 단계 색, 색 이름 8가지의 실제 값, 조정 여부.

- 틀 = 고른 배경 그대로. 내용 칸 = 배경을 섞은 읽기용 바탕(어두운 톤 배경 20%+#161616, 밝은 톤 배경 18%+#FFFFFF).
- 대비(WCAG 상대 휘도): 본문 4.5:1, 보조 글자·상태색·강조색·탭 글자 3:1. 미달이면 색조·채도는 두고 밝기만 가장 가깝게 옮긴다.
"""
from __future__ import annotations

import colorsys

DEFAULT = {"background": "#202020", "accent": "#00C9A2", "content": "auto"}
CONTENT_TONES = ("auto", "dark", "light")
BG_PRESETS = (("그레이", "#202020"), ("남색", "#141A26"), ("자주밤", "#1E1620"),
              ("진한 핑크", "#C2185B"), ("하늘", "#A5D8FF"), ("크림", "#F5EFE3"))
ACCENT_PRESETS = (("민트", "#00C9A2"), ("하늘", "#38BDF8"), ("파랑", "#5B8DEF"),
                  ("보라", "#A78BFA"), ("분홍", "#F472B6"), ("살구", "#F59E7B"))
WHITE_TEXT, BLACK_TEXT = "#F2F2F2", "#111111"
BODY, OTHER = 4.5, 3.0
# 내용 칸 톤별 시작 값(0.29.0 palette의 다크/라이트 값과 같다)
TONE_NAMES = {
    "dark": {"accent": "#00C9A2", "on-accent": "#062F28", "accent-soft": "#8FDCCC", "muted": "#8A8F98",
             "ok": "#2ECC71", "warn": "#E67E22", "danger": "#E5534B", "brand": "#3A0729"},
    "light": {"accent": "#00A884", "on-accent": "#FFFFFF", "accent-soft": "#1F8A7A", "muted": "#6B7280",
              "ok": "#1E9E57", "warn": "#C2610F", "danger": "#C0392B", "brand": "#3A0729"},
}


def parse(value) -> tuple[int, int, int] | None:
    """'#RRGGBB' → (r, g, b). 잘못된 값은 None."""
    if not isinstance(value, str):
        return None
    text = value.strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def to_hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def normalize(value, default):
    rgb = parse(value)
    return to_hex(rgb) if rgb is not None else default


def luminance(value) -> float:
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = parse(value)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a, b) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def mix(a, b, t: float) -> str:
    """a를 t만큼, b를 1-t만큼 섞는다."""
    ra, rb = parse(a), parse(b)
    return to_hex(tuple(x * t + y * (1 - t) for x, y in zip(ra, rb)))


def _hls(value):
    r, g, b = parse(value)
    return colorsys.rgb_to_hls(r / 255, g / 255, b / 255)


def with_lightness(value, lightness: float) -> str:
    h, _l, s = _hls(value)
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, lightness)), s)
    return to_hex((r * 255, g * 255, b * 255))


def shift(value, delta: float) -> str:
    """밝기(HLS L)만 delta만큼 옮긴다."""
    return with_lightness(value, _hls(value)[1] + delta)


def fit(value, backgrounds, ratio: float) -> tuple[str, bool]:
    """모든 바탕에서 ratio 이상이 되게, 색조·채도는 두고 밝기만 가장 가까운 값으로. (값, 조정했는지)."""
    if all(contrast(value, bg) >= ratio for bg in backgrounds):
        return value, False
    base = _hls(value)[1]
    best, best_score = value, min(contrast(value, bg) for bg in backgrounds)
    for step in range(1, 201):
        for sign in (1, -1):
            candidate = with_lightness(value, base + sign * step / 200)
            score = min(contrast(candidate, bg) for bg in backgrounds)
            if score >= ratio:
                return candidate, True
            if score > best_score:
                best, best_score = candidate, score
    return best, best != value


def text_on(value) -> str:
    """바탕 위 글자: 흰 글자·검은 글자 중 대비가 큰 쪽."""
    return WHITE_TEXT if contrast(WHITE_TEXT, value) >= contrast(BLACK_TEXT, value) else BLACK_TEXT


def tone_for(background, content="auto") -> str:
    if content in ("dark", "light"):
        return content
    return "dark" if text_on(background) == WHITE_TEXT else "light"


def compute(background=None, accent=None, content="auto") -> dict:
    """개인화 결과. 잘못된 값은 기본값(되돌리기 값)으로 읽는다."""
    bg = normalize(background, DEFAULT["background"])
    accent = normalize(accent, DEFAULT["accent"])
    content = content if content in CONTENT_TONES else "auto"
    tone = tone_for(bg, content)
    dark = tone == "dark"
    base = mix(bg, "#161616", 0.20) if dark else mix(bg, "#FFFFFF", 0.18)
    text = "#E8E8E8" if dark else "#1F1F1F"
    text, adj_text = fit(text, [base], BODY)
    # 내용 칸 단계 색(입력칸·버튼·테두리·구분선): 바탕에서 밝기를 단계적으로 옮긴다
    step = 1 if dark else -1
    roles = {
        "window": base,
        "base": shift(base, 0.05) if dark else mix(base, "#FFFFFF", 0.35),
        "alternate": shift(base, 0.03 * step),
        "button": shift(base, 0.07) if dark else mix(base, "#FFFFFF", 0.55),
        "midlight": shift(base, 0.10 * step),
        "mid": shift(base, 0.22 * step),
        "dark": shift(base, -0.06 if dark else -0.30),
        "light": shift(base, 0.16) if dark else "#FFFFFF",
        "text": text,
        "disabled": mix(text, base, 0.45),
    }
    adjusted = adj_text
    names = dict(TONE_NAMES[tone])
    frame_text = text_on(bg)
    frame_dark = frame_text == WHITE_TEXT
    # 강조색: 고른 값 그대로, 3:1 미만이면 밝기만. 내용 칸(잠금됨·스위치·링크·2단 이하)과 틀(1단 선택 탭·머리줄)에서 따로 맞춘다
    # — 중간 밝기 틀과 어두운 내용 칸처럼 한 값으로 둘 다 맞출 수 없는 조합이 있어서.
    names["accent"], adj = fit(accent, [base], OTHER)
    adjusted |= adj
    frame_accent, adj = fit(accent, [bg], OTHER)
    adjusted |= adj
    names["on-accent"] = "#062F28" if contrast("#062F28", names["accent"]) >= contrast("#FFFFFF", names["accent"]) else "#FFFFFF"
    # 연한 강조(2단 탭 선택): 강조색에서 한 단계 약하게 + 내용 칸 대비 3:1
    soft = (TONE_NAMES[tone]["accent-soft"] if names["accent"] == TONE_NAMES[tone]["accent"]
            else mix(names["accent"], text, 0.55 if dark else 0.65))
    names["accent-soft"], adj = fit(soft, [base], OTHER)
    adjusted |= adj
    for name in ("muted", "ok", "warn", "danger"):
        names[name], adj = fit(names[name], [base], OTHER)
        adjusted |= adj
    on_frame = {}
    for name in ("muted", "ok", "warn", "danger"):
        start = TONE_NAMES["dark" if frame_dark else "light"][name]
        on_frame[name], _ = fit(start, [bg], OTHER)
    on_frame["accent"] = frame_accent
    on_frame["text"] = frame_text
    names = _unique(names)
    return {
        "background": bg, "accent_input": accent, "content": content, "tone": tone,
        "frame": bg, "frame_bottom": shift(bg, -0.05), "frame_text": frame_text, "on_frame": on_frame,
        "roles": roles, "names": names,
        "subtab_underline": mix(names["accent"], base, 0.55),
        "adjusted": adjusted,
    }


def _unique(names: dict) -> dict:
    """이름 색끼리 값이 같으면 1만 옮긴다(화면 다시 칠하기가 값으로 이름을 찾기 때문, 눈에는 같은 색)."""
    seen = {}
    out = {}
    for name, value in names.items():
        while value.upper() in seen and name != "brand":
            r, g, b = parse(value)
            value = to_hex((r, g, b + 1 if b < 255 else b - 1))
        seen[value.upper()] = name
        out[name] = value
    return out
