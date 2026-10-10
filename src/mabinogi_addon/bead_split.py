"""구슬 분배 계산 (편의기능). 순수 계산 — Qt·네트워크 없음(맥에서도 테스트 가능).

구슬은 한 개 먹으면 2개로 친다(x2). 그래서 **총 구슬 갯수 = 입력한 갯수 합 × 2**.
- 브리레흐: 1관·2관·3관 세 칸의 합 × 2
- 탈라가흐: 한 칸 × 2
1인당 분배금 = 구슬금액 × 총 구슬 갯수 ÷ 분배 인원 (원 단위 내림).
"""

from __future__ import annotations

from collections.abc import Iterable

# 구슬 1개 = 2개로 환산
BEAD_MULTIPLIER = 2


def total_beads(counts: Iterable[int]) -> int:
    """입력한 구슬 갯수들의 합에 x2를 적용한 총 구슬 갯수."""
    return sum(max(0, int(c)) for c in counts) * BEAD_MULTIPLIER


def per_person(total_count: int, bead_price: int, people: int) -> int:
    """1인당 분배금 = 구슬금액 × 총 구슬 갯수 ÷ 인원 (내림). 입력이 비면 0."""
    if people <= 0 or total_count <= 0 or bead_price <= 0:
        return 0
    return bead_price * total_count // people
