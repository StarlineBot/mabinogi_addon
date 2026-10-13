"""사라짐 경고(buff_controller 고스트) 테스트.

'사라짐 경고' 켠 버프가 사라지면(직전 틱엔 있었는데 이번 틱에 없음) 오버레이에
3초간 고스트(gone) 칸을 띄우고, 다시 걸리면 즉시 해제한다. 켜지 않은 버프는 무시.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from mabinogi_addon.catalog import BuffDef
from mabinogi_addon.tracker.engine import OverlayEntry
from mabinogi_addon.ui import buff_controller as bc_mod
from mabinogi_addon.ui.buff_controller import BuffController
from mabinogi_addon.ui.overlay import BuffOverlay

_ICON = Path("src/mabinogi_addon/assets/buff/icon")


def _app():
    return QApplication.instance() or QApplication([])


def _controller():
    _app()
    catalog = {
        "march": BuffDef("march", "행진곡", _ICON / "march.png", None),
        "han_adrenaline": BuffDef(
            "han_adrenaline", "햄 버닝", _ICON / "han_adrenaline.png", None
        ),
        "manashield": BuffDef("manashield", "마나실드", _ICON / "manashield.png", None),
    }
    c = BuffController(BuffOverlay(), catalog, show_duration={})
    c.set_order(["march", "han_adrenaline", "manashield"])
    return c


def _entry(bid, remaining=120.0):
    return OverlayEntry(bid, remaining, False)


def _gone_ids(controller):
    return {i for i, it in enumerate(controller._items) if it.gone}


def test_warn_gone_confirms_after_3s_then_shows_and_clears(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(bc_mod.time, "monotonic", lambda: clock["t"])
    c = _controller()
    c.set_warn_gone_ids({"han_adrenaline"})

    # 1) 둘 다 있음 → 고스트 없음
    c._on_updated([_entry("march"), _entry("han_adrenaline")])
    assert not any(it.gone for it in c._items)

    # 2) han 사라짐 — 아직 확정 전(3초 안)이라 아이콘 없음
    clock["t"] = 10.0
    c._on_updated([_entry("march")])
    assert not any(it.gone for it in c._items)
    clock["t"] = 12.9
    c._on_updated([_entry("march")])
    assert not any(it.gone for it in c._items)

    # 3) 3초 연속 없음 → 확정 → 아이콘 노출(제자리)
    clock["t"] = 13.0
    c._on_updated([_entry("march")])
    assert [it.gone for it in c._items] == [False, True]  # march 정상, han 경고

    # 4) 노출 시간(확정 후 _GONE_SHOW_SEC) 안엔 유지. 확정 시각 = 13.0.
    clock["t"] = 13.0 + bc_mod._GONE_SHOW_SEC - 0.1
    c._on_updated([_entry("march")])
    assert any(it.gone for it in c._items)

    # 5) 노출 시간 경과 → 사라짐(march만)
    clock["t"] = 13.0 + bc_mod._GONE_SHOW_SEC + 0.1
    c._on_updated([_entry("march")])
    assert not any(it.gone for it in c._items)
    assert len(c._items) == 1


def test_warn_gone_reappear_within_3s_no_warning(monkeypatch):
    """3초 확정 전에 다시 뜨면 오탐으로 보고 아이콘·소리 모두 없음."""
    clock = {"t": 0.0}
    monkeypatch.setattr(bc_mod.time, "monotonic", lambda: clock["t"])
    c = _controller()
    c.set_warn_gone_ids({"han_adrenaline"})
    c._on_updated([_entry("march"), _entry("han_adrenaline")])
    clock["t"] = 1.0
    c._on_updated([_entry("march")])  # 잠깐 사라짐(확정 전)
    assert not any(it.gone for it in c._items)
    clock["t"] = 2.0
    c._on_updated([_entry("march"), _entry("han_adrenaline")])  # 3초 안에 복귀
    assert not any(it.gone for it in c._items)
    # 그 뒤로도 경고 안 뜸(확정 대기 취소됨)
    clock["t"] = 6.0
    c._on_updated([_entry("march"), _entry("han_adrenaline")])
    assert not any(it.gone for it in c._items)


def test_unflagged_buff_no_ghost(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(bc_mod.time, "monotonic", lambda: clock["t"])
    c = _controller()
    c.set_warn_gone_ids(set())  # 아무도 경고 안 켬
    c._on_updated([_entry("march"), _entry("han_adrenaline")])
    clock["t"] = 10.0
    c._on_updated([_entry("march")])  # han 사라져도 경고 꺼짐
    clock["t"] = 14.0  # 확정 시간이 지나도
    c._on_updated([_entry("march")])
    assert not any(it.gone for it in c._items)


def test_fast_gone_buff_confirms_quickly(monkeypatch):
    """즉시 종료형(마나실드)은 짧은 확정 대기(_GONE_CONFIRM_FAST_SEC)로 빠르게 경고.

    같은 틱에서 일반 버프(han)는 아직 확정 전이어야 한다(견고 유지)."""
    clock = {"t": 0.0}
    monkeypatch.setattr(bc_mod.time, "monotonic", lambda: clock["t"])
    assert "manashield" in bc_mod._FAST_GONE_IDS
    c = _controller()
    c.set_warn_gone_ids({"han_adrenaline", "manashield"})

    # 셋 다 있음(마나실드는 시간 없음 → remaining None)
    c._on_updated(
        [_entry("march"), _entry("han_adrenaline"), _entry("manashield", None)]
    )
    assert not any(it.gone for it in c._items)

    # han + mana 동시에 사라짐
    clock["t"] = 10.0
    c._on_updated([_entry("march")])
    assert not any(it.gone for it in c._items)  # 아직 아무도 확정 전

    # 빠른 확정 시간만 지남 → 마나실드만 확정, han은 아직 대기 중(견고 3초)
    clock["t"] = 10.0 + bc_mod._GONE_CONFIRM_FAST_SEC + 0.01
    c._on_updated([_entry("march")])
    assert "manashield" in c._gone_show_until  # 확정됨
    assert "han_adrenaline" not in c._gone_show_until  # 아직
    assert "han_adrenaline" in c._absent_since  # 여전히 대기 중

    # 견고 확정 시간까지 지나면 han도 확정
    clock["t"] = 10.0 + bc_mod._GONE_CONFIRM_SEC + 0.01
    c._on_updated([_entry("march")])
    assert "han_adrenaline" in c._gone_show_until


def test_warn_gone_suppressed_when_not_foreground(monkeypatch):
    """게임이 포그라운드가 아니면 '사라짐 경고'를 판정·노출하지 않는다(비포커스 거짓
    경고 방지). 탐지·표시는 계속되지만 경고(고스트)는 포커스일 때만."""
    clock = {"t": 0.0}
    monkeypatch.setattr(bc_mod.time, "monotonic", lambda: clock["t"])
    c = _controller()
    c.set_warn_gone_ids({"han_adrenaline"})
    c._game_active = False  # 비포커스
    c._on_updated([_entry("march"), _entry("han_adrenaline")])
    clock["t"] = 10.0
    c._on_updated([_entry("march")])  # han 사라짐(비포커스)
    clock["t"] = 14.0  # 확정 시간이 지나도
    c._on_updated([_entry("march")])
    assert not any(it.gone for it in c._items)  # 비포커스 → 경고 안 뜸
