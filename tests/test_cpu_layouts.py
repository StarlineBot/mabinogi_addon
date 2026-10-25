"""최적화 명세 13.11: CPU 배치 옵션 이름·추천 순서·3D 캐시 감지·화면(체크박스 제거, 콤보 두 줄 설명)."""
import json
import struct

import pytest

from mabinogi_addon.optimization.engine import Engine
from mabinogi_addon.optimization.layouts import find, layouts, x3d_group
from mabinogi_addon.optimization.session import Core, Recovery, Topology
from mabinogi_addon.system.optimization import parse_l3
from mabinogi_addon.ui import optimization_controller as module
from test_navigation import window  # noqa: F401  (픽스처)
from test_optimization import Backend, TARGET, _wait

MB = 1024 * 1024


def smt_cores(n, start=0, performance=True):
    return tuple(Core(start + i, (2 * (start + i), 2 * (start + i) + 1), performance) for i in range(n))


def mask(cpus):
    return sum(1 << c for c in cpus)


X9800 = Topology('AMD Ryzen 7 9800X3D', smt_cores(8), ((96 * MB, tuple(range(16))),))
X7950 = Topology('AMD Ryzen 9 7950X3D', smt_cores(16), ((96 * MB, tuple(range(16))), (32 * MB, tuple(range(16, 32)))))
R7950 = Topology('AMD Ryzen 9 7950X', smt_cores(16), ((32 * MB, tuple(range(16))), (32 * MB, tuple(range(16, 32)))))
HYBRID = Topology('Intel Core i9-13900K', smt_cores(8) + tuple(Core(8 + i, (16 + i,), False) for i in range(16)))
HYBRID_NO_SMT = Topology('Intel Core Ultra 9 285K', tuple(Core(i, (i,)) for i in range(8))
                         + tuple(Core(8 + i, (8 + i,), False) for i in range(16)))
SIX = Topology('AMD Ryzen 5 7600', smt_cores(6))


def keys(topology):
    return [layout.key for layout in layouts(topology)]


@pytest.mark.parametrize('topology, expected', [
    (X9800, ['focus', 'max_focus', 'smt_single', 'none']),      # 단일 묶음 8코어 이상
    (R7950, ['focus', 'max_focus', 'smt_single', 'none']),      # 2-CCD지만 3D 캐시 아님(L3 같음)
    (X7950, ['x3d', 'none']),                                    # 2-CCD X3D
    (HYBRID, ['pcore', 'pcore_smt', 'none']),                    # 하이브리드 + P코어 SMT
    (HYBRID_NO_SMT, ['pcore', 'none']),                          # 하이브리드, SMT 없음
    (SIX, ['none', 'focus']),                                    # 6코어 이하: 배치 안 함 추천
])
def test_options_follow_cpu_kind_in_recommended_order(topology, expected):
    options = layouts(topology)
    assert [o.key for o in options] == expected
    assert [o.recommended for o in options] == [True] + [False] * (len(options) - 1)


def test_9800x3d_names_numbers_and_masks():
    focus, max_focus, smt, none = layouts(X9800)
    assert focus.label() == '게임 집중 (추천) · 6+2' and focus.allocation == '게임 6코어 · 그 외 2코어 (6+2)'
    assert focus.game == mask(range(12)) and focus.background == mask(range(12, 16))
    assert max_focus.label() == '게임 최대 집중 · 7+1' and max_focus.background == mask((14, 15))
    assert smt.name == '게임 코어 단독 사용' and smt.game == mask(range(0, 16, 2)) and smt.background is None
    assert none.name == '배치 안 함' and not none.applies
    assert '리서치 7.8' in focus.basis and '7.7' in smt.basis


def test_hybrid_masks_split_performance_and_efficiency():
    pcore, pcore_smt, _ = layouts(HYBRID)
    assert pcore.game == mask(range(16)) and pcore.background == mask(range(16, 32)) and pcore.short == 'P8+E16'
    assert pcore_smt.game == mask(range(0, 16, 2)) and pcore_smt.background == pcore.background


def test_3d_cache_group_detected_only_when_clearly_bigger():
    x3d = find(X7950, 'x3d')
    assert x3d.game == mask(range(16)) and x3d.background == mask(range(16, 32)) and '미검증' in x3d.allocation
    assert x3d_group(R7950) is None and x3d_group(X9800) is None
    unsure = Topology('?', smt_cores(16), ((48 * MB, tuple(range(16))), (32 * MB, tuple(range(16, 32)))))
    assert x3d_group(unsure) is None and 'x3d' not in keys(unsure)  # 불확실하면 보이지 않음
    partial = Topology('?', smt_cores(16), ((96 * MB, tuple(range(16))),  (32 * MB, tuple(range(16, 30)))))
    assert x3d_group(partial) is None


def test_six_core_focus_keeps_one_core_and_recommended_is_none():
    none, focus = layouts(SIX)
    assert none.recommended and focus.allocation == '게임 5코어 · 그 외 1코어 (5+1)'
    assert find(SIX, 'recommended').key == 'none' and find(X9800, None).key == 'focus'


def test_parse_l3_from_windows_cache_records():
    def record(level, size, cpus):
        data = bytearray(56)
        struct.pack_into('<II', data, 0, 2, 56)
        data[8] = level
        struct.pack_into('<I', data, 12, size)
        struct.pack_into('<H', data, 38, 1)
        struct.pack_into('<QH', data, 40, mask(cpus), 0)
        return bytes(data)
    buffer = record(2, MB, range(2)) + record(3, 96 * MB, range(16)) + record(3, 32 * MB, range(16, 32))
    assert parse_l3(buffer) == ((96 * MB, tuple(range(16))), (32 * MB, tuple(range(16, 32))))
    with pytest.raises(ValueError):
        parse_l3(struct.pack('<II', 2, 4))


# ---- 엔진 ----

class LayoutBackend(Backend):
    def __init__(self, topology):
        super().__init__()
        self.topology = lambda: topology
        self.game = lambda: TARGET
        self.alive = lambda target: True
        self.governor_running = lambda: False
        other = {'pid': 900, 'birth': '1'}
        self.processes = lambda: [dict(target=other, name='other.exe')]
        self.background_candidate = lambda p, game: True
        self.values[('cpu', json.dumps(TARGET, sort_keys=True))] = 0xFFFF
        self.values[('cpu', json.dumps(other, sort_keys=True))] = 0xFFFF
        self.values[('priority', json.dumps(TARGET, sort_keys=True))] = 0x20


def _run(tmp_path, topology, layout):
    b = LayoutBackend(topology)
    r = Recovery(tmp_path / 'j.json', b, lambda: True)
    e = Engine(b, r, lambda: True)
    assert e.start(dict(cpu=True, count=None, layout=layout, adapter=None, tcp=False, rss=False, priority=True))
    assert _wait(lambda: any(kind == 'priority' for kind, *_ in b.writes))
    _wait(lambda: False, 0.3)
    e.stop(); e.thread.join(5)
    return [(kind, target['pid'], value) for kind, target, value in b.writes]


def test_engine_applies_named_layout_masks(tmp_path):
    writes = _run(tmp_path, X9800, 'focus')
    assert ('cpu', 123, mask(range(12))) in writes and ('cpu', 900, mask(range(12, 16))) in writes


def test_engine_smt_single_leaves_other_programs_untouched(tmp_path):
    writes = _run(tmp_path, X9800, 'smt_single')
    assert ('cpu', 123, mask(range(0, 16, 2))) in writes and not any(pid == 900 for _k, pid, _v in writes)


@pytest.mark.parametrize('topology, layout', [(X9800, 'none'), (SIX, 'recommended')])
def test_engine_none_layout_sets_only_priority(tmp_path, topology, layout):
    writes = _run(tmp_path, topology, layout)
    assert writes and all(kind == 'priority' for kind, _p, _v in writes)


# ---- 화면 ----

def test_panel_has_no_cpu_checkbox_and_combo_shows_names_with_numbers(window, monkeypatch):
    from mabinogi_addon.ui.optimization_panel import POPUP_ROLE
    w = window[0]
    c = w.optimization_tools; c.timer.stop()
    monkeypatch.setattr(module, 'optimization_available', lambda: True); c.refresh_access()
    d = c.panel
    assert not hasattr(d, 'cpu')
    labels = [label.text() for label in d.findChildren(type(d.split_detail))]
    assert 'CPU 배치' in labels and '물리 코어 배분' not in labels
    c._apply_inspection(X9800, [])
    assert [d.split.itemText(i) for i in range(d.split.count())] == [
        '게임 집중 (추천) · 6+2', '게임 최대 집중 · 7+1', '게임 코어 단독 사용 · SMT 8×1', '배치 안 함 · 기본']
    assert d.split.itemData(0, POPUP_ROLE) == '게임 집중 · 추천\n게임 6코어 · 그 외 2코어 (6+2)'
    assert d.split_detail.text() == '게임 6코어 · 그 외 2코어 (6+2)'  # 13.15: 근거 줄 삭제
    d.split.setCurrentIndex(3)
    assert d.split_detail.text().startswith('Windows 기본 배치') and not c._cpu_selected()
    from mabinogi_addon import config
    assert config.load_optimization_selection()['layout'] == 'none'


def test_badge_and_fps_record_use_layout_name(window, monkeypatch):
    w = window[0]
    c = w.optimization_tools; c.timer.stop()
    monkeypatch.setattr(module, 'optimization_available', lambda: True); c.refresh_access()
    started = []
    monkeypatch.setattr(c.engine, 'start', lambda options: started.append(options) or True)
    c._apply_inspection(X9800, [])
    c.panel.tcp.setChecked(False)  # 연결 없이 시작(13.14 기본은 패스트핑 포함)
    c._start_optimization()
    assert started[-1]['layout'] == 'focus' and started[-1]['cpu'] is True
    assert c._badge_split == '· 게임 집중'
    assert c._summary_requested['layout_name'] == '게임 집중' and c._summary_requested['layout_allocation'] == '6+2'
    from types import SimpleNamespace as NS
    recovery = NS(corrupt=False, pending=[dict(kind='cpu', state='applied')], restart_targets=set())
    engine = NS(busy=True, task='session', cancel=NS(is_set=lambda: False), held=False)
    assert module.optimization_badge(recovery, engine, c._badge_split) == ('최적화: 적용 중 · 게임 집중', 'neutral')
