"""음악 버프 계산기(docs/music-buff-calculator-spec.md 5절, 0.52.0 모든 사용자)."""
import json
import os
from pathlib import Path

import pytest

from mabinogi_addon import config
from mabinogi_addon.market import music_buff as mb

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "assets" / "music-buff-20261116"
VECTORS = json.loads((DOC / "test_vectors.json").read_text(encoding="utf-8"))


def _state(**kw):
    return mb.normalize(kw)


# ---- 계산 ----
@pytest.mark.parametrize("vec", VECTORS, ids=[v["name"][:12] for v in VECTORS])
def test_vectors_match_to_four_decimals(vec):
    got = mb.calc(mb.normalize(vec["input"]), master_title=vec["master_title"])
    exp = vec["expected"]
    for q in mb.QUALITIES:
        assert got["prob"][q] == pytest.approx(exp["prob"][q], abs=1e-4)
        for song in ("overture", "vivace", "march"):
            for key, want in exp[song][q].items():
                have = got[song][q][key]
                if want is None:
                    assert have is None, (song, q, key)
                else:
                    assert round(have, 4) == pytest.approx(want, abs=1e-4), (song, q, key)


def test_app_table_is_same_as_planning_table():
    assert json.loads(mb.tables_path().read_text(encoding="utf-8")) == json.loads(
        (DOC / "music_buff_tables.json").read_text(encoding="utf-8"))


def test_site_default_screen_rounded():
    r = mb.calc(mb.default_state(), master_title=False)
    assert [mb.fmt(r["overture"][q]["damage"]) for q in mb.QUALITIES] == ["33.17", "36.49", "43.12"]
    assert [mb.fmt(r["march"][q]["move_speed"]) for q in mb.QUALITIES] == ["18.60", "20.46", "24.18"]
    assert [f"{r['prob'][q]:.1f}" for q in mb.QUALITIES] == ["80.0", "16.7", "3.3"]


def test_saint_bard_divine_100():
    s = _state(saint_bard_arcana=True, inst_reforge=[["inst_divine_rate", 8]],
               acc1_reforge=[["acc_divine_rate", 4]])  # 12 × 10 ≥ 120
    assert mb.probabilities(s) == {"normal": 0.0, "excellent": 0.0, "divine": 100.0}
    s["acc1_reforge"][0] = ["acc_divine_rate", 3]  # 11 → 가중치
    assert mb.probabilities(s)["divine"] < 100


def test_saint_bard_excellent_100():
    # u(9+4+4=17) = 5 + 16×2 = 37 → 370 ≥ 350
    s = _state(saint_bard_arcana=True, inst_reforge=[["inst_excellent_rate", 9]],
               acc1_reforge=[["acc_excellent_rate", 4]], acc2_reforge=[["acc_excellent_rate", 4]])
    assert mb.probabilities(s) == {"normal": 0.0, "excellent": 100.0, "divine": 0.0}


def test_saint_bard_weights():
    s = _state(saint_bard_arcana=True, inst_reforge=[["inst_excellent_rate", 1], ["inst_divine_rate", 2]])
    # 보통 24, 훌륭 5 + 10×u(1)=55, 신들린 1 + 10×2 = 21 → 합 100
    assert mb.probabilities(s) == pytest.approx({"normal": 24.0, "excellent": 55.0, "divine": 21.0})
    off = dict(s, saint_bard_arcana=False)  # 꺼짐: 24 / 5+5 / 1+2
    assert mb.probabilities(off) == pytest.approx({"normal": 24 / 37 * 100, "excellent": 10 / 37 * 100,
                                                   "divine": 3 / 37 * 100})


def test_echostone_counts_only_the_bigger_side():
    inst = _state(inst_reforge=[["inst_music_buff", 20]])
    both = _state(inst_reforge=[["inst_music_buff", 20]], eco_reforge=[["eco_music_buff", 15]])
    eco = _state(inst_reforge=[["inst_music_buff", 5]], eco_reforge=[["eco_music_buff", 15]])
    assert mb.song_total(both) == mb.song_total(inst)  # 더하지 않음
    assert mb.song_total(eco) == mb.song_total(_state()) + 15
    # 연주 효과·속도도 (악기/신발 + 액세서리) 와 에코스톤 중 큰 쪽
    a = mb.calc(_state(acc1_reforge=[["acc_divine_effect", 4]], eco_reforge=[["eco_divine_effect", 3]]))
    b = mb.calc(_state(acc1_reforge=[["acc_divine_effect", 4]]))
    assert a["overture"]["divine"]["damage"] == b["overture"]["divine"]["damage"]
    c = mb.calc(_state(shoes_reforge=[["shoes_march_move", 4]], eco_reforge=[["eco_march_move", 6]]))
    d = mb.calc(_state(eco_reforge=[["eco_march_move", 6]]))
    assert c["march"]["normal"]["move_speed"] == d["march"]["normal"]["move_speed"]


def test_special_bonus_only_on_damage_and_magic_attack():
    base = mb.calc(_state())
    up = mb.calc(_state(special_mod=8, brirehe_attack=1, tala_attack=1, relic_suffix_count=3))
    for q in mb.QUALITIES:
        assert up["overture"][q]["damage"] > base["overture"][q]["damage"]
        assert up["vivace"][q]["magic_attack"] > base["vivace"][q]["magic_attack"]
        assert up["overture"][q]["critical"] == base["overture"][q]["critical"]
        for key in ("magic_cast_speed", "attack_speed", "alchemy_cast_speed"):
            assert up["vivace"][q][key] == base["vivace"][q][key]
        assert up["march"][q]["move_speed"] == base["march"][q]["move_speed"]


def test_bonus_damage_only_with_saint_bard():
    off, on = mb.calc(_state()), mb.calc(_state(saint_bard_arcana=True))
    assert off["overture"]["normal"]["bonus_damage"] is None and off["vivace"]["normal"]["bonus_damage"] is None
    for q in mb.QUALITIES:
        assert on["overture"][q]["bonus_damage"] == pytest.approx(on["overture"][q]["damage"] * 0.1)
        assert on["vivace"][q]["bonus_damage"] == pytest.approx(on["vivace"][q]["magic_attack"] * 0.1)


# ---- 표 ----
def test_tables_have_no_duration_or_harvest_options():
    t = mb.tables()
    text = json.dumps({k: v for k, v in t.items() if k != "source"}, ensure_ascii=False)
    for word in ("지속", "풍년가", "duration_", "harvest", "초록빛"):
        assert word not in text, word
    assert all(e["baseDuration"] == 0 for e in t["instruments"])


def test_every_choice_has_positive_buff_and_unique_names():
    t = mb.tables()
    for key in mb.CHOICES:
        opts = mb.options(key, t)
        assert opts and all(e["buff"] > 0 for e in opts), key
        assert len({e["name"] for e in opts}) == len(opts), key
        assert len({e["id"] for e in opts}) == len(opts), key
    for key in mb.REFORGE_LINES:
        opts = mb.reforge_options(key, t)
        assert all(o["max"] > 0 for o in opts) and len({o["name"] for o in opts}) == len(opts)
    assert all(c["buff"] > 0 for c in t["checkbox"])


# ---- 저장 ----
def test_unknown_saved_values_fall_back_to_none():
    raw = {"secondary_title": "removed_title", "inst_prefix": "inst_polyphony_7", "instrument": "harp",
           "pet": "green_fairy_dragon", "special_mod": 11, "brirehe_attack": 0.35, "murias_holy_water": 8,
           "inst_reforge": [["inst_music_buff", 99], ["gone_effect", 3], "bad"], "eco_reforge": "x",
           "saint_bard_arcana": "yes", "grandmaster": True}
    s = mb.normalize(raw)
    assert s["secondary_title"] is None and s["inst_prefix"] == "inst_polyphony_7"
    assert s["instrument"] == "lyre" and s["pet"] == "none"
    assert s["special_mod"] == 0 and s["brirehe_attack"] == 0 and s["murias_holy_water"] == 8
    assert s["inst_reforge"] == [["inst_music_buff", 25], [None, 0], [None, 0]]  # 최대까지, 모르는 옵션은 없음
    assert s["eco_reforge"] == [[None, 0]]
    assert s["saint_bard_arcana"] is False and s["grandmaster"] is True
    assert mb.normalize(None) == mb.default_state()


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_input_saves_immediately_and_survives_restart(qapp):
    from mabinogi_addon.ui.music_buff_tab import MusicBuffTab
    tab = MusicBuffTab()
    assert config.load_music_buff() == {}  # 처음 열기만 해서는 저장하지 않음
    tab.combos["secondary_title"].set_value("renen_miir")
    assert config.load_music_buff()["secondary_title"] == "renen_miir"  # 바꾸는 즉시
    tab.set_state(mb.normalize(VECTORS[2]["input"]))
    shown = {k: v.text() for k, v in tab.value_labels.items() if v.isVisibleTo(tab)}
    again = MusicBuffTab()  # 다시 켬
    assert again.state() == tab.state() == mb.normalize(VECTORS[2]["input"])
    assert {k: v.text() for k, v in again.value_labels.items() if v.isVisibleTo(again)} == shown
    assert shown[("overture", "damage")] == "51.63 · 56.80 · <b>74.35%</b>"  # 시안 예시와 같은 수치


def test_unknown_saved_value_shows_none(qapp):
    from mabinogi_addon.ui.music_buff_tab import MusicBuffTab
    config.save_music_buff({"secondary_title": "removed_title", "doll_bag": "arcana_flame_bag",
                            "acc1_reforge": [["acc_gone", 4]]})
    tab = MusicBuffTab()
    assert tab.combos["secondary_title"].currentText() == "없음"
    assert tab.combos["doll_bag"].currentText() == "아르카나 불꽃 인형 가방 (+2)"
    assert tab.reforges["acc1_reforge"][0].option.currentText() == "없음"
    assert not tab.reforges["acc1_reforge"][0].level.isEnabled()


def test_music_buff_is_exported_and_synced():
    from mabinogi_addon import cloud_sync
    config.save_music_buff({"horn": "corple_horn"})
    assert cloud_sync.strip_for_sync(config._read_local_config())["musicBuff"] == {"horn": "corple_horn"}
    assert "musicBuff" not in config._LOCAL_ONLY_KEYS
    assert json.loads(config.config_json_for_export())["musicBuff"] == {"horn": "corple_horn"}


# ---- 화면 ----
def test_screen_rows_and_bonus_line_follow_saint_bard(qapp):
    from mabinogi_addon.ui.music_buff_tab import BOTTOM_NOTE, MusicBuffTab
    tab = MusicBuffTab()
    tab.resize(766, 760)
    tab.show()
    qapp.processEvents()
    names = {k: lbl.text() for k, lbl in tab.name_labels.items() if lbl.isVisible()}
    assert names == {("overture", "damage"): "최대·최소뎀", ("overture", "critical"): "크리",
                     ("vivace", "magic_attack"): "마공·연금뎀", ("vivace", "magic_cast_speed"): "마시속",
                     ("vivace", "attack_speed"): "공속", ("vivace", "alchemy_cast_speed"): "연시속",
                     ("march", "move_speed"): "이동속도"}
    assert "확률 80.0% · 16.7% · 3.3%" in tab.prob_label.text()
    tab.checks["saint_bard_arcana"].setChecked(True)
    qapp.processEvents()
    assert tab.value_labels[("overture", "bonus_damage")].isVisible()
    assert tab.value_labels[("vivace", "bonus_damage")].isVisible()
    tab.checks["saint_bard_arcana"].setChecked(False)
    qapp.processEvents()
    assert not tab.value_labels[("overture", "bonus_damage")].isVisible()
    assert BOTTOM_NOTE in [lbl.text() for lbl in tab.findChildren(type(tab.prob_label))]
    tab.close()


def test_results_stay_fixed_while_inputs_scroll(qapp):
    from mabinogi_addon.ui.music_buff_tab import MusicBuffTab
    tab = MusicBuffTab()
    tab.resize(766, 640)
    tab.show()
    qapp.processEvents()
    top = tab.prob_label.mapTo(tab, tab.prob_label.rect().topLeft()).y()
    bar = tab.scroll.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum())
    qapp.processEvents()
    assert tab.prob_label.mapTo(tab, tab.prob_label.rect().topLeft()).y() == top
    tab.resize(766, 1150)  # 창을 키우면 스크롤 없이 다 보임
    qapp.processEvents()
    assert tab.scroll.verticalScrollBar().maximum() == 0
    tab.close()


def test_section_titles_are_14px_bold(qapp):
    from PySide6.QtWidgets import QLabel

    from mabinogi_addon.ui.music_buff_tab import MusicBuffTab
    tab = MusicBuffTab()
    titles = [lbl.text() for lbl in tab.scroll.widget().findChildren(QLabel)
              if "font-size:14px; font-weight:700" in lbl.styleSheet()]
    assert titles == ["2차 타이틀", "악기", "모자", "옷", "장갑", "신발", "액세서리 1", "액세서리 2", "에코스톤",
                      "주화 · 유물", "기타", "기타 보너스"]


def test_wheel_over_unfocused_combo_does_not_change_value(qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    from mabinogi_addon.ui.music_buff_tab import MusicBuffTab
    tab = MusicBuffTab()
    combo = tab.combos["horn"]
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    combo.wheelEvent(ev)
    assert combo.currentIndex() == 0


def test_columns_fold_only_when_too_narrow(qapp):
    from PySide6.QtWidgets import QWidget

    from mabinogi_addon.ui.music_buff_tab import MusicBuffTab
    tab = MusicBuffTab()
    tab.resize(766, 760)
    tab.show()
    qapp.processEvents()
    assert not tab.songs.folded and not tab.columns.folded  # 앱 기본 글자에선 시안대로 가로 3묶음·입력 2단
    for widget in [tab] + tab.findChildren(QWidget):
        font = widget.font()
        font.setPixelSize(20)
        widget.setFont(font)
    for _ in range(3):
        qapp.processEvents()
    assert tab.minimumSizeHint().width() <= 766
    assert tab.songs.folded or tab.columns.folded
    tab.close()


def test_reforge_level_capped_by_option_max(qapp):
    """명세 2절 보완(9ef3051): Lv 상한 = 옵션 max, 옵션 바꿔 넘치면 낮춤, '없음'이면 Lv 0·비활성."""
    from mabinogi_addon.ui.music_buff_tab import MusicBuffTab
    tab = MusicBuffTab()
    t = mb.tables()
    for key, lines in tab.reforges.items():
        for opt in mb.reforge_options(key, t):
            line = lines[0]
            line.option.set_value(opt["id"])
            assert line.level.isEnabled() and line.level.maximum() == opt["max"], (key, opt["id"])
            line.level.setValue(99)
            assert line.level.value() == opt["max"]
    line = tab.reforges["inst_reforge"][0]
    line.option.set_value("inst_music_buff")
    line.level.setValue(25)
    line.option.set_value("inst_divine_rate")  # 최대 8
    assert line.level.value() == 8 and config.load_music_buff()["inst_reforge"][0] == ["inst_divine_rate", 8]
    line.option.set_value(None)
    assert line.level.value() == 0 and not line.level.isEnabled()
    assert config.load_music_buff()["inst_reforge"][0] == [None, 0]


def test_same_option_on_two_lines_adds_levels():
    two = _state(inst_reforge=[["inst_music_buff", 10], ["inst_music_buff", 5]])
    assert mb.song_total(two) == mb.song_total(_state(inst_reforge=[["inst_music_buff", 15]]))
