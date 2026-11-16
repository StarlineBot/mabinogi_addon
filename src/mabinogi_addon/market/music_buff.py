"""음악 버프 계산(docs/music-buff-calculator-spec.md 3절, 0.52.0) — Qt 없는 순수 함수.

표는 `assets/music_buff/music_buff_tables.json`(참고 사이트 스크립트의 상수 표를 글자로 읽어 정리한 것),
공식은 기획 참고 구현 `docs/assets/music-buff-20261116/reference_calc.py`를 옮긴 것.
앱 고정 조건(사용자 결정 11-16): 스킬 7종 1랭, 악기 개조·등급 보너스 최대(악기 기본값), 곡마다 그 곡 마스터 타이틀 +8.

입력(state)은 저장(config `musicBuff`)과 같은 dict. 표에 없는 값은 `normalize`가 '없음'(None·0)으로 바꾼다.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .. import paths

QUALITIES = ("normal", "excellent", "divine")
REFORGE_LINES = {"inst_reforge": 3, "shoes_reforge": 3, "acc1_reforge": 3, "acc2_reforge": 3, "eco_reforge": 1}
# 세공 줄 키 → 표의 세공 옵션 묶음
REFORGE_GROUP = {"inst_reforge": "instrument", "shoes_reforge": "shoes", "acc1_reforge": "accessory",
                 "acc2_reforge": "accessory", "eco_reforge": "ecostone"}
# 고르는 칸(id) → 표에서 후보를 꺼내는 경로
CHOICES = {
    "secondary_title": ("secondary_titles",),
    "inst_prefix": ("enchants", "instrument", "prefix"), "inst_suffix": ("enchants", "instrument", "suffix"),
    "head_equipment": ("enchants", "head", "equipment"), "head_suffix": ("enchants", "head", "suffix"),
    "armor_prefix": ("enchants", "armor", "prefix"), "gloves_prefix": ("enchants", "gloves", "prefix"),
    "shoes_prefix": ("enchants", "shoes", "prefix"),
    "acc1_prefix": ("enchants", "accessory", "prefix"), "acc1_suffix": ("enchants", "accessory", "suffix"),
    "acc2_prefix": ("enchants", "accessory", "prefix"), "acc2_suffix": ("enchants", "accessory", "suffix"),
    "extra_miniature": ("farm_installations", "extra"), "normal_miniature": ("farm_installations", "normal"),
    "horn": ("horn",), "doll_bag": ("doll_bag",),
}
CHECKS = ("cloud_cushion", "music_boost_potion", "rose_couple_bracelet", "saint_bard_arcana", "grandmaster")


def tables_path() -> Path:
    return paths.resource_dir() / "music_buff" / "music_buff_tables.json"


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def tables(path: Path | None = None) -> dict:
    return _load(str(path or tables_path()))


def options(key: str, t: dict | None = None) -> list[dict]:
    """고르는 칸 하나의 후보 [{id, name, buff}, …](없음 제외)."""
    node = t or tables()
    for part in CHOICES[key]:
        node = node[part]
    return node


def reforge_options(key: str, t: dict | None = None) -> list[dict]:
    return (t or tables())["reforge_options"][REFORGE_GROUP[key]]


def default_state() -> dict:
    s = {k: None for k in CHOICES}
    s.update({k: [[None, 0] for _ in range(n)] for k, n in REFORGE_LINES.items()})
    s.update({k: False for k in CHECKS})
    s.update(instrument="lyre", special_mod=0, brirehe_attack=0, tala_attack=0, relic_prefix_count=0,
             relic_suffix_count=0, murias_holy_water=0, pet="none")
    return s


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def normalize(raw, t: dict | None = None) -> dict:
    """저장값을 계산 입력으로. 표에 없는 id·범위 밖 숫자는 '없음'(기본값), 세공 Lv은 옵션 최대까지."""
    t = t or tables()
    s = default_state()
    if not isinstance(raw, dict):
        return s
    for key in CHOICES:
        ids = {e["id"] for e in options(key, t)}
        if raw.get(key) in ids:
            s[key] = raw[key]
    if raw.get("instrument") in {e["id"] for e in t["instruments"]}:
        s["instrument"] = raw["instrument"]
    if raw.get("pet") in {e["id"] for e in t["pets"]}:
        s["pet"] = raw["pet"]
    for key, n in REFORGE_LINES.items():
        maxima = {e["id"]: e["max"] for e in reforge_options(key, t)}
        got = raw.get(key) if isinstance(raw.get(key), list) else []
        for i, line in enumerate(got[:n]):
            if (isinstance(line, (list, tuple)) and len(line) == 2 and line[0] in maxima
                    and isinstance(line[1], int) and not isinstance(line[1], bool)):
                s[key][i] = [line[0], max(0, min(maxima[line[0]], line[1]))]
    for key in CHECKS:
        s[key] = raw.get(key) is True
    numeric = {"special_mod": [int(k) for k in t["special_mod_bonus"]],
               "brirehe_attack": t["brirehe_attack_options"], "tala_attack": t["tala_attack_options"],
               "relic_prefix_count": [e["count"] for e in t["relic_prefix_count_options"]],
               "relic_suffix_count": [e["count"] for e in t["relic_suffix_count_options"]],
               "murias_holy_water": t["murias_holy_water"]}
    for key, allowed in numeric.items():
        v = raw.get(key)
        if _num(v) and any(abs(v - a) < 1e-9 for a in allowed):
            s[key] = next(a for a in allowed if abs(v - a) < 1e-9)
    return s


def _find(lst, id_):
    return next((e for e in lst if e["id"] == id_), None) if id_ else None


def _lv(lines, effect):
    """세공 줄 [(옵션 id, Lv), …]에서 그 옵션 Lv 합."""
    return sum(lv for eff, lv in lines if eff == effect)


def song_total(s: dict, t: dict | None = None, *, master_title: bool = True) -> float:
    """곡 합계(명세 3절 1) — 음악 버프 수치 %."""
    t = t or tables()
    inst = _find(t["instruments"], s.get("instrument") or "lyre")
    total = sum(t["fixed"]["skill_rank_buff"].values()) + inst["defaultModBonus"]
    for key in CHOICES:
        e = _find(options(key, t), s.get(key))
        total += e["buff"] if e else 0
    total += max(_lv(s.get("inst_reforge", []), "inst_music_buff"), _lv(s.get("eco_reforge", []), "eco_music_buff"))
    if s.get("cloud_cushion"):
        total += t["farm_installations"]["other"][0]["buff"]
    checks = {c["id"]: c["buff"] for c in t["checkbox"]}
    for cid in ("music_boost_potion", "rose_couple_bracelet", "saint_bard_arcana"):
        if s.get(cid):
            total += checks[cid]
    if s.get("grandmaster"):
        total += t["fixed"]["grandmaster_buff"]
    total += s.get("murias_holy_water", 0) + s.get("relic_prefix_count", 0)
    total += (_find(t["pets"], s.get("pet")) or {"baseBuff": 0})["baseBuff"]
    return total + (t["fixed"]["master_title_buff"] if master_title else 0)


def special_bonus(s: dict, t: dict | None = None) -> float:
    """특수 보너스%(명세 3절 2) — 서곡 대미지·비바체 마공에만."""
    t = t or tables()
    inst = _find(t["instruments"], s.get("instrument") or "lyre")
    return (t["special_mod_bonus"][str(s.get("special_mod", 0))] + inst["defaultGradeBonus"]
            + s.get("brirehe_attack", 0) + s.get("tala_attack", 0) + 0.3 * s.get("relic_suffix_count", 0))


def probabilities(s: dict, t: dict | None = None) -> dict:
    """보통·훌륭·신들린 확률 %(명세 3절 4)."""
    t = t or tables()
    ir, a1, a2, er = (s.get(k, []) for k in ("inst_reforge", "acc1_reforge", "acc2_reforge", "eco_reforge"))

    def u(v):
        return 5 + (v - 1) * 2 if v > 0 else 0
    ex_rate = max(u(_lv(ir, "inst_excellent_rate") + _lv(a1, "acc_excellent_rate") + _lv(a2, "acc_excellent_rate")),
                  u(_lv(er, "eco_excellent_rate")))
    dv_rate = max(_lv(ir, "inst_divine_rate") + _lv(a1, "acc_divine_rate") + _lv(a2, "acc_divine_rate"),
                  _lv(er, "eco_divine_rate"))
    if s.get("saint_bard_arcana"):
        if 10 * dv_rate >= 120:
            return {"normal": 0.0, "excellent": 0.0, "divine": 100.0}
        if 10 * ex_rate >= 350:
            return {"normal": 0.0, "excellent": 100.0, "divine": 0.0}
        nw, ew, dw = 24, 5 + 10 * ex_rate, 1 + 10 * dv_rate
    else:
        q = t["fixed"]["quality_weights"]
        nw, ew, dw = q["normal"], q["excellent"] + ex_rate, q["divine"] + dv_rate
    tot = nw + ew + dw
    return {"normal": nw / tot * 100, "excellent": ew / tot * 100, "divine": dw / tot * 100}


def calc(s: dict, t: dict | None = None, *, master_title: bool = True) -> dict:
    """곡 수치(명세 3절). 반환: {"prob", "overture", "vivace", "march"}, 곡마다 품질별 값 dict.

    보너스뎀은 세인트 바드 링크 개방 10단계를 켰을 때만 숫자, 아니면 None.
    """
    t = t or tables()
    ir, a1, a2, sr, er = (s.get(k, []) for k in ("inst_reforge", "acc1_reforge", "acc2_reforge", "shoes_reforge",
                                                 "eco_reforge"))

    def best(own, suffix, src):
        base = _lv(own, f"{src}_{suffix}") + _lv(a1, f"acc_{suffix}") + _lv(a2, f"acc_{suffix}")
        return max(base, _lv(er, f"eco_{suffix}"))

    mult = {"normal": 1 + best(ir, "normal_effect", "inst") / 100,
            "excellent": 1.1 + best(ir, "excellent_effect", "inst") / 100,
            "divine": 1.3 + best(ir, "divine_effect", "inst") / 100}
    saint = bool(s.get("saint_bard_arcana"))
    tm = 1 + song_total(s, t, master_title=master_title) / 100
    sm = 1 + special_bonus(s, t) / 100
    pet = _find(t["pets"], s.get("pet")) or {"harmonyBonus": 0, "skill": None}

    def harmony(song):
        return pet["harmonyBonus"] if pet["skill"] == song else 0
    ov, vv, mv = (t["effects_rank1"][k] for k in ("overture", "vivace", "march"))
    speed = {k: vv["speed"] + best(sr, k, "shoes") for k in ("vivace_magic", "vivace_attack", "vivace_alchemy")}
    move = mv["moveSpeed"] + best(sr, "march_move", "shoes")
    out = {"prob": probabilities(s, t), "overture": {}, "vivace": {}, "march": {}}
    for q, m in mult.items():
        h = harmony("overture")
        dmg = ov["damage"] * tm * sm * m + ov["damage"] * h * sm
        out["overture"][q] = {"damage": dmg, "critical": ov["critical"] * tm * m + ov["critical"] * h,
                              "bonus_damage": 0.1 * dmg if saint else None}
        h = harmony("vivace")
        mag = vv["magicAttack"] * tm * m * sm + vv["magicAttack"] * h * sm
        out["vivace"][q] = {"magic_attack": mag,
                            "magic_cast_speed": speed["vivace_magic"] * tm * m + speed["vivace_magic"] * h,
                            "attack_speed": speed["vivace_attack"] * tm * m + speed["vivace_attack"] * h,
                            "alchemy_cast_speed": speed["vivace_alchemy"] * tm * m + speed["vivace_alchemy"] * h,
                            "bonus_damage": 0.1 * mag if saint else None}
        out["march"][q] = {"move_speed": move * tm * m}
    return out


# 위쪽 결과 줄(명세 1절): (곡 키, 곡 이름, [(값 키, 줄 이름), …]) — 보너스뎀은 세인트 바드일 때만 보임
SONGS = (
    ("overture", "전장의 서곡", (("damage", "최대·최소뎀"), ("critical", "크리"), ("bonus_damage", "보너스뎀"))),
    ("vivace", "비바체", (("magic_attack", "마공·연금뎀"), ("bonus_damage", "보너스뎀"), ("magic_cast_speed", "마시속"),
                         ("attack_speed", "공속"), ("alchemy_cast_speed", "연시속"))),
    ("march", "행진곡", (("move_speed", "이동속도"),)),
)


def fmt(v: float) -> str:
    return f"{v:.2f}"
