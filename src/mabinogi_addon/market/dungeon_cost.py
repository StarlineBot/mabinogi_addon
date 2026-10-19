"""Dungeon entry arithmetic, independent of UI and market access."""

NAMES = ("크롬바스 심연", "브리레흐", "믿음의 균열", "탈라가흐")
REWARDS = {NAMES[0]: 500_000, NAMES[1]: 1_300_000, NAMES[3]: 1_700_000}
PRICES = (100_000, 200_000, 400_000, 700_000, 1_000_000,
          2_000_000, 3_000_000, 5_000_000, 7_000_000, 10_000_000)
MATERIAL = "균열의 편린"


def ticket_rows(name: str, count: int = 11) -> list[tuple[int, int, int]]:
    reward = REWARDS[name]
    cost = 0
    rows = []
    for n in range(1, count + 1):
        price = PRICES[n - 1] if n <= len(PRICES) else 50_000_000
        cost += price
        rows.append((n, price, n * reward - cost))
    return rows


def rift_rows(price: int | None, count: int = 11):
    return [(n, max(1, n - 1),
             None if price is None else price * max(1, n - 1),
             None if price is None else price * (1 + n * (n - 1) // 2))
            for n in range(1, count + 1)]
