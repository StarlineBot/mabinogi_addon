"""CPU 배치 옵션: 이름과 추천 순서(최적화 명세 13.11, 2026-10-25 사용자 결정). OS 호출 없음(맥에서 테스트).

감지한 CPU 구조(물리 코어·성능/효율 구분·SMT·L3 캐시 묶음)로 목록을 만든다. 해당 없는 옵션은 넣지 않는다.
맨 앞이 추천이다. 효과 확정이 아니며(13.5) 알파 자료가 쌓이면 순서를 바꿀 수 있다. 우선순위 높음(13.7)은 별개.
"""
from __future__ import annotations

from dataclasses import dataclass

# (이름, 근거) — 명세 13.11 표
NAMES = {
    'focus': ('게임 집중', '개발 PC(9800X3D) 측정에서 무거운 장면 1% low가 좋아지는 방향(리서치 7.8)'),
    'max_focus': ('게임 최대 집중', '미측정 · 블랙박스 등 배경 작업이 1코어에 몰려요'),
    'smt_single': ('게임 코어 단독 사용', '커뮤니티 권장 · 개발 PC에선 이득 없음(리서치 7.7)'),
    'pcore': ('성능 코어 전용', '하이브리드 CPU에 널리 권하는 방식 · 우리 측정 없음'),
    'pcore_smt': ('성능 코어 전용 + 게임 코어 단독 사용', '성능 코어 전용에 SMT 끔 효과를 더함 · 우리 측정 없음'),
    'x3d': ('3D 캐시 코어 전용', '2-CCD X3D에 널리 권하는 방식 · 실기 미검증'),
    'none': ('배치 안 함', 'Windows 기본 배치 · 기준(우선순위만 적용)'),
}
SMALL_CPU = 6  # 이 이하 물리 코어는 '배치 안 함'을 추천(게임 몫을 줄이는 손해가 더 클 수 있음)


@dataclass(frozen=True)
class Layout:
    key: str
    name: str
    game: int | None  # 게임 프로세스 선호도 마스크(None = 바꾸지 않음)
    background: int | None  # 그 외 프로그램 마스크(None = 바꾸지 않음)
    allocation: str  # 실제 배분(알파 동안 표시)
    short: str  # 닫힌 목록·상단 상태 옆 숫자
    basis: str
    recommended: bool = False

    @property
    def applies(self) -> bool:
        return self.game is not None

    def label(self) -> str:
        """닫힌 콤보 문구: `이름 (추천) · 6+2`."""
        return f"{self.name}{' (추천)' if self.recommended else ''} · {self.short}"


def _mask(cpus) -> int:
    return sum(1 << cpu for cpu in cpus)


def x3d_group(topology):
    """3D V-Cache 코어 묶음(2-CCD X3D): L3가 둘 이상이고 가장 큰 L3가 나머지보다 확실히 클 때만 그 L3의 논리 CPU.
    감지 실패·불확실(크기가 같거나 묶음이 하나)이면 None — 항목을 보이지 않는다."""
    groups = [(size, tuple(sorted(cpus))) for size, cpus in getattr(topology, 'l3', ()) if size > 0 and cpus]
    if len(groups) < 2:
        return None
    groups.sort(reverse=True)
    biggest, rest = groups[0], groups[1:]
    if any(size * 2 > biggest[0] for size, _ in rest):  # 3D 캐시 묶음은 보통 3배(96MB vs 32MB). 2배 이하면 불확실
        return None
    covered = {cpu for _, cpus in groups for cpu in cpus}
    every = {cpu for core in topology.cores for cpu in core.cpus}
    if covered != every or len(biggest[1]) >= len(every):
        return None
    return biggest[1]


def layouts(topology) -> list[Layout]:
    """이 CPU에서 고를 수 있는 배치를 추천 순으로. 맨 앞에 recommended=True."""
    cores = topology.cores
    every = [cpu for core in cores for cpu in core.cpus]
    perf = [core for core in cores if core.performance]
    eff = [core for core in cores if not core.performance]
    smt = any(len(core.cpus) > 1 for core in perf)
    out = []

    def add(key, game, background, allocation, short):
        name, basis = NAMES[key]
        out.append(Layout(key, name, game, background, allocation, short, basis))

    none = ('none', None, None, 'Windows 기본 배치 · 게임 우선순위만 적용', '기본')
    if eff and perf:  # 하이브리드(P/E)
        p = [cpu for core in perf for cpu in core.cpus]
        e = [cpu for core in eff for cpu in core.cpus]
        add('pcore', _mask(p), _mask(e), f'게임 성능 코어 {len(perf)}개 · 그 외 효율 코어 {len(eff)}개 (P{len(perf)}+E{len(eff)})',
            f'P{len(perf)}+E{len(eff)}')
        if smt:
            add('pcore_smt', _mask(core.cpus[0] for core in perf), _mask(e),
                f'게임 성능 코어 {len(perf)}개(코어당 1스레드) · 그 외 효율 코어 {len(eff)}개', f'P{len(perf)}×1+E{len(eff)}')
        add(*none)
    elif (cache := x3d_group(topology)) is not None:  # 2-CCD X3D
        game = [cpu for cpu in every if cpu in cache]
        other = [cpu for cpu in every if cpu not in cache]
        g = len({core.index for core in cores if set(core.cpus) <= set(cache)})
        add('x3d', _mask(game), _mask(other), f'게임 3D 캐시 코어 {g}개 · 그 외 {len(cores) - g}코어 (미검증)',
            f'3D {g}+{len(cores) - g}')
        add(*none)
    elif len(cores) <= SMALL_CPU:
        add(*none)
        if len(cores) >= 2:
            plan = topology.plan(len(cores) - 1)
            add('focus', plan['game'], plan['background'], f'게임 {len(cores) - 1}코어 · 그 외 1코어 ({len(cores) - 1}+1)',
                f'{len(cores) - 1}+1')
    else:  # 단일 묶음 7코어 이상(9800X3D 등)
        for key, rest in (('focus', 2), ('max_focus', 1)):
            plan = topology.plan(len(cores) - rest)
            add(key, plan['game'], plan['background'], f'게임 {len(cores) - rest}코어 · 그 외 {rest}코어 ({len(cores) - rest}+{rest})',
                f'{len(cores) - rest}+{rest}')
        if smt:
            add('smt_single', _mask(core.cpus[0] for core in cores), None,
                f'게임 {len(cores)}코어 · 코어당 1스레드 · 그 외 배치 그대로', f'SMT {len(cores)}×1')
        add(*none)
    if out:
        out[0] = Layout(**{**out[0].__dict__, 'recommended': True})
    return out


def find(topology, key) -> Layout | None:
    """key의 배치. 'recommended'(또는 None)는 이 CPU의 추천(맨 앞)."""
    options = layouts(topology)
    if key in (None, 'recommended'):
        return options[0] if options else None
    return next((layout for layout in options if layout.key == key), None)
