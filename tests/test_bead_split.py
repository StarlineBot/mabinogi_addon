"""구슬 분배 계산(bead_split) 순수 함수 테스트."""

from mabinogi_addon import bead_split


def test_total_beads_doubles_sum():
    # 브리레흐 1관3 + 2관4 + 3관2 = 9 → x2 = 18
    assert bead_split.total_beads([3, 4, 2]) == 18
    # 탈라가흐 한 칸 20 → x2 = 40
    assert bead_split.total_beads([20]) == 40
    assert bead_split.total_beads([0, 0, 0]) == 0


def test_total_beads_ignores_negative():
    assert bead_split.total_beads([-5, 3]) == 6  # 음수는 0으로


def test_per_person_floor_division():
    # 구슬금액 300,000 × 총 18개 ÷ 6명 = 900,000
    assert bead_split.per_person(18, 300_000, 6) == 900_000
    # 나누어떨어지지 않으면 내림
    assert bead_split.per_person(18, 300_000, 7) == 771_428  # 5,400,000 // 7


def test_per_person_guards_empty_inputs():
    assert bead_split.per_person(0, 300_000, 6) == 0  # 갯수 0
    assert bead_split.per_person(18, 0, 6) == 0  # 금액 0
    assert bead_split.per_person(18, 300_000, 0) == 0  # 인원 0
