"""적용·복구 결과 요약(최적화 명세 13.13, 2026-10-25 사용자 결정). Qt·OS 없이 테스트한다.

결과 영역은 **지금 상태 한 줄 + 항목마다 한 줄**만 보여준다(쌓이지 않음). 프로세스 수·PID·마스크·다른 프로그램과의 충돌은
요약에 쓰지 않고 상세(자세히 보기·app.log)에만 둔다. 단 게임 프로세스 자체를 다른 도구가 바꿨으면 요약에 보인다.
성능 향상 문구는 쓰지 않는다(13.5).
"""
from __future__ import annotations

from .session import PROCESS_KINDS

COLORS = {'ok': '#2ecc71', 'neutral': '#8a8f98', 'warn': '#e67e22', 'error': '#e74c3c'}
IDLE = '시작 전 · 시스템 설정을 변경하지 않았어요.'
NOTHING_TO_RESTORE = '원래부터 같은 값이라 되돌릴 것이 없어요.'


def _labels(requested, layout_label):
    labels = {}
    if requested.get('priority'):
        labels['priority'] = '게임 우선순위 높음'
    if requested.get('cpu'):
        labels['cpu'] = f'CPU 배치 · {layout_label}' if layout_label else 'CPU 배치'
    if requested.get('tcp'):
        labels['tcp'] = '패스트핑'
    return labels


def _line(key, label, state, reason):
    short = {'priority': '게임 우선순위', 'cpu': 'CPU 배치', 'tcp': '패스트핑'}[key]
    if state == 'ok':
        return f'✓ {label}'
    if state == 'same':
        return f"✓ {label} · {'이미 높음이라 그대로 뒀어요' if key == 'priority' else '이미 목표값이라 그대로 뒀어요'}"
    if state == 'restored':
        return f'↺ {short} · 되돌림'
    if state == 'deferred':
        return f'• {label} · {reason}'
    return f'! {short} · {reason}'  # fail·released


def summarize(engine, recovery, requested=None, *, layout_label=None, kept_on=False, restore_wait=False):
    """(첫 줄, 등급 'ok'|'neutral'|'warn'|'error', 항목 줄 목록)."""
    requested = requested or {}
    if recovery.corrupt:
        return '복구 기록이 손상돼 새 적용을 막았어요. 추정값으로 되돌리지 않아요.', 'error', []
    network_left = any(i['kind'] not in PROCESS_KINDS for i in recovery.pending) or bool(recovery.restart_targets)
    network_line = '• 패스트핑 · 적용 중 (최적화를 끄면 되돌려요)'
    outcome = getattr(engine, 'outcome', {}) or {}
    labels = _labels(requested, layout_label)
    if engine.busy and engine.task != 'inspect':
        if engine.cancel.is_set() or engine.task == 'restore':
            return '원래대로 되돌리는 중…', 'neutral', []
        phase = getattr(engine, 'phase', None)
        if phase == 'held':
            return 'Process Lasso가 실행 중이라 잠시 멈췄어요 · 끄면 다시 적용해요', 'neutral', []
        if phase == 'ended':
            lines = [_line(key, labels.get(key, ''), 'restored', '') for key in ('priority', 'cpu')
                     if outcome.get(key, ('',))[0] == 'restored']
            if 'tcp' in outcome and 'tcp' in labels:  # 13.15: 미룬 패스트핑은 게임이 끝나면 적용 — 결과 줄을 남긴다
                lines.append(_line('tcp', labels['tcp'], *outcome['tcp']))
            elif network_left:
                lines.append(network_line)
            return '게임이 끝나 원래대로 되돌렸어요', 'neutral', lines
        if phase != 'applied':
            auto = requested.get('auto')
            return ('마비노기를 기다리는 중 · 켜지면 자동으로 적용해요' if auto else '마비노기를 기다리는 중 · 켜지면 적용해요'), 'neutral', []
        return _applied(outcome, labels)
    if getattr(engine, 'status', '').startswith('작업을 완료하지 못했어요') or '\n작업을 완료하지 못했어요' in getattr(engine, 'status', ''):
        return '작업을 완료하지 못했어요 · 자세히 보기에서 이유를 확인해 주세요', 'warn', []
    if network_left:
        if restore_wait:
            return '네트워크 원복 대기 · 연결을 끊어도 될 때 최적화 버튼을 다시 눌러 주세요', 'warn', []
        return '최적화 적용 중', 'ok', [network_line if 'tcp' not in outcome else _line('tcp', '패스트핑', *outcome['tcp'])]
    if kept_on:
        return _applied(outcome, labels)
    if getattr(engine, 'status', '') == NOTHING_TO_RESTORE:
        return NOTHING_TO_RESTORE, 'neutral', []
    if getattr(engine, 'ran', False):
        return '원래대로 되돌렸어요', 'neutral', []
    return IDLE, 'neutral', []


def _applied(outcome, labels):
    lines, failed = [], False
    for key in ('priority', 'cpu', 'tcp'):
        if key not in labels or key not in outcome:
            continue
        state, reason = outcome[key]
        failed |= state in ('fail', 'released')
        lines.append(_line(key, labels[key], state, reason))
    return ('일부 항목을 적용하지 못했어요', 'warn', lines) if failed else ('최적화 적용 중', 'ok', lines)
