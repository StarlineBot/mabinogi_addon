"""음악 버프 계산 참고 구현(기획 세션, 2026-11-16) — 개발은 이 공식·표를 앱 코드로 옮기고 아래 검증값을 테스트로 쓴다.

출처: It's 마비노기 음악 버프 계산기 스크립트의 계산 함수를 읽고 다시 쓴 것(코드 복사 아님).
앱 고정 조건(사용자 결정 11-16): 스킬 7종 1랭, 악기 개조·등급 보너스 최대(악기 기본값), 곡마다 그 곡 마스터 타이틀 +8,
지속시간·풍년가·이벤트 숫자 입력 없음. `master_title=False`로 부르면 사이트 기본 화면과 같은 조건(타이틀 없음)이 된다.
"""
from __future__ import annotations

import json
from pathlib import Path

T = json.loads((Path(__file__).with_name("music_buff_tables.json")).read_text(encoding="utf-8"))


def _find(lst, id_):
    return next((e for e in lst if e["id"] == id_), None) if id_ else None


def _lv(reforges, effect):
    """세공 줄 목록 [(effect_id, level), …]에서 그 옵션 레벨 합."""
    return sum(lv for eff, lv in reforges if eff == effect)


def calc(s: dict, *, master_title: bool = True) -> dict:
    inst = _find(T["instruments"], s.get("instrument", "lyre"))
    ir, a1r, a2r, sr, er = (s.get(k, []) for k in ("inst_reforge", "acc1_reforge", "acc2_reforge", "shoes_reforge", "eco_reforge"))
    en = T["enchants"]

    def ench(slot, part, key):
        e = _find(en.get(slot, {}).get(part, []), s.get(key))
        return e["buff"] if e else 0

    total = sum(T["fixed"]["skill_rank_buff"].values()) + inst["defaultModBonus"]
    total += ench("instrument", "prefix", "inst_prefix") + ench("instrument", "suffix", "inst_suffix")
    total += max(_lv(ir, "inst_music_buff"), _lv(er, "eco_music_buff"))
    total += ench("head", "equipment", "head_equipment") + ench("head", "suffix", "head_suffix")
    total += ench("armor", "prefix", "armor_prefix") + ench("gloves", "prefix", "gloves_prefix") + ench("shoes", "prefix", "shoes_prefix")
    for n in (1, 2):
        total += ench("accessory", "prefix", f"acc{n}_prefix") + ench("accessory", "suffix", f"acc{n}_suffix")
    t2 = _find(T["secondary_titles"], s.get("secondary_title"))
    total += t2["buff"] if t2 else 0
    farm = T["farm_installations"]
    for key, grp in (("extra_miniature", "extra"), ("normal_miniature", "normal")):
        e = _find(farm[grp], s.get(key)); total += e["buff"] if e else 0
    if s.get("cloud_cushion"): total += farm["other"][0]["buff"]
    for key, grp in (("horn", "horn"), ("doll_bag", "doll_bag")):
        e = _find(T[grp], s.get(key)); total += e["buff"] if e else 0
    checks = {c["id"]: c["buff"] for c in T["checkbox"]}
    for cid in ("music_boost_potion", "rose_couple_bracelet", "saint_bard_arcana"):
        if s.get(cid): total += checks[cid]
    if s.get("grandmaster"): total += T["fixed"]["grandmaster_buff"]
    total += s.get("murias_holy_water", 0)
    pet = _find(T["pets"], s.get("pet")) or {"baseBuff": 0, "harmonyBonus": 0, "skill": None}
    total += pet["baseBuff"]
    total += s.get("relic_prefix_count", 0)
    song_total = total + (T["fixed"]["master_title_buff"] if master_title else 0)

    special = (T["special_mod_bonus"][str(s.get("special_mod", 0))] + inst["defaultGradeBonus"]
               + s.get("brirehe_attack", 0) + s.get("tala_attack", 0) + 0.3 * s.get("relic_suffix_count", 0))

    def best(inst_or_shoes, effect_suffix, src="inst"):
        base = _lv(inst_or_shoes, f"{src}_{effect_suffix}") + _lv(a1r, f"acc_{effect_suffix}") + _lv(a2r, f"acc_{effect_suffix}")
        return max(base, _lv(er, f"eco_{effect_suffix}"))

    n_eff, e_eff, d_eff = best(ir, "normal_effect"), best(ir, "excellent_effect"), best(ir, "divine_effect")
    u = lambda v: 5 + (v - 1) * 2 if v > 0 else 0
    ex_rate = max(u(_lv(ir, "inst_excellent_rate") + _lv(a1r, "acc_excellent_rate") + _lv(a2r, "acc_excellent_rate")), u(_lv(er, "eco_excellent_rate")))
    dv_rate = best(ir, "divine_rate")
    mult = {"normal": 1 + n_eff / 100, "excellent": 1.1 + e_eff / 100, "divine": 1.3 + d_eff / 100}

    saint = bool(s.get("saint_bard_arcana"))
    if saint:
        if 10 * dv_rate >= 120: prob = {"normal": 0, "excellent": 0, "divine": 100}
        elif 10 * ex_rate >= 350: prob = {"normal": 0, "excellent": 100, "divine": 0}
        else:
            ew, dw = 5 + 10 * ex_rate, 1 + 10 * dv_rate; tot = 24 + ew + dw
            prob = {"normal": 24 / tot * 100, "excellent": ew / tot * 100, "divine": dw / tot * 100}
    else:
        q = T["fixed"]["quality_weights"]; nw, ew, dw = q["normal"], q["excellent"] + ex_rate, q["divine"] + dv_rate
        tot = nw + ew + dw
        prob = {"normal": nw / tot * 100, "excellent": ew / tot * 100, "divine": dw / tot * 100}

    tm, sm = 1 + song_total / 100, 1 + special / 100
    harmony = lambda song: pet["harmonyBonus"] if pet["skill"] == song else 0
    ov, vv, mv = (T["effects_rank1"][k] for k in ("overture", "vivace", "march"))
    out = {"prob": prob, "overture": {}, "vivace": {}, "march": {}}
    for q, m in mult.items():
        h = harmony("overture"); dmg = ov["damage"] * tm * sm * m + ov["damage"] * h * sm
        out["overture"][q] = {"damage": dmg, "critical": ov["critical"] * tm * m + ov["critical"] * h,
                              "bonus_damage": 0.1 * dmg if saint else None}
        h = harmony("vivace"); mag = vv["magicAttack"] * tm * m * sm + vv["magicAttack"] * h * sm
        sp = {k: vv["speed"] + best(sr, k, "shoes") for k in ("vivace_magic", "vivace_attack", "vivace_alchemy")}
        out["vivace"][q] = {"magic_attack": mag, "magic_cast_speed": sp["vivace_magic"] * tm * m + sp["vivace_magic"] * h,
                            "attack_speed": sp["vivace_attack"] * tm * m + sp["vivace_attack"] * h,
                            "alchemy_cast_speed": sp["vivace_alchemy"] * tm * m + sp["vivace_alchemy"] * h,
                            "bonus_damage": 0.1 * mag if saint else None}
        out["march"][q] = {"move_speed": (mv["moveSpeed"] + best(sr, "march_move", "shoes")) * tm * m}
    return out


if __name__ == "__main__":
    r2 = lambda v: f"{v:.2f}"
    # 1) 사이트 기본 화면 재현(타이틀 없음): 서곡 33.17/36.49/43.12, 크리 17.05/18.76/22.17, 행진곡 18.60/20.46/24.18, 확률 80.0/16.7/3.3
    site = calc({}, master_title=False)
    got = ([r2(site["overture"][q]["damage"]) for q in ("normal", "excellent", "divine")],
           [r2(site["overture"][q]["critical"]) for q in ("normal", "excellent", "divine")],
           [r2(site["vivace"][q]["magic_attack"]) for q in ("normal", "excellent", "divine")],
           [r2(site["vivace"][q]["attack_speed"]) for q in ("normal", "excellent", "divine")],
           [r2(site["march"][q]["move_speed"]) for q in ("normal", "excellent", "divine")],
           [f"{site['prob'][q]:.1f}" for q in ("normal", "excellent", "divine")])
    want = (["33.17", "36.49", "43.12"], ["17.05", "18.76", "22.17"], ["33.17", "36.49", "43.12"],
            ["17.05", "18.76", "22.17"], ["18.60", "20.46", "24.18"], ["80.0", "16.7", "3.3"])
    assert got == want, got
    print("사이트 기본 화면 재현: 일치", got)
    # 2) 앱 기본(곡별 마스터 +8, 나머지 없음)
    app = calc({})
    print("앱 기본 서곡", [r2(app["overture"][q]["damage"]) for q in ("normal", "excellent", "divine")])
