"""Свойства датчиков, которые не сводятся к p-значению: период, линейная сложность, «плоскости».

    period_brent    — длина цикла и длина «хвоста» до него (алгоритм Брента, память O(1));
    hull_dobell     — условия максимального периода ЛКГ (теорема Халла–Добелла);
    linear_complexity — длина кратчайшего РСЛОС, порождающего биты (алгоритм Берлекэмпа–Мэсси):
                      у случайной последовательности ≈ n/2, у РСЛОС — степень его многочлена;
    randu_planes    — у RANDU 9xₖ − 6xₖ₊₁ + xₖ₊₂ ≡ 0 (mod 2³¹): тройки лежат на 15 плоскостях.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import gcd

import numpy as np


@dataclass
class Period:
    length: int | None           # длина цикла (None — не найден за max_steps)
    tail: int | None             # сколько шагов до входа в цикл
    steps: int


def period_brent(step, x0, max_steps: int = 2_000_000) -> Period:
    """Алгоритм Брента: «черепаха» стоит на месте, «заяц» уходит на 1, 2, 4, 8… шагов,
    пока не встретит черепаху; тогда длина цикла λ известна. Затем ищется начало цикла μ."""
    power = lam = 1
    tortoise, hare = x0, step(x0)
    steps = 1
    while tortoise != hare:
        if power == lam:
            tortoise = hare
            power *= 2
            lam = 0
        hare = step(hare)
        lam += 1
        steps += 1
        if steps > max_steps:
            return Period(None, None, steps)
    tortoise = hare = x0
    for _ in range(lam):
        hare = step(hare)
    mu = 0
    while tortoise != hare:
        tortoise, hare = step(tortoise), step(hare)
        mu += 1
    return Period(lam, mu, steps)


def _prime_factors(n: int) -> set[int]:
    out, d = set(), 2
    while d * d <= n:
        while n % d == 0:
            out.add(d)
            n //= d
        d += 1
    if n > 1:
        out.add(n)
    return out


def hull_dobell(a: int, c: int, m: int) -> list[tuple[str, bool]]:
    """Теорема Халла–Добелла: период ЛКГ равен m тогда и только тогда, когда
    1) c и m взаимно просты; 2) a − 1 делится на все простые делители m; 3) если 4 | m, то 4 | (a − 1)."""
    checks = [(f'НОД(c, m) = НОД({c}, {m}) = {gcd(c, m)} = 1', gcd(c, m) == 1)]
    primes = sorted(_prime_factors(m)) if m < 10 ** 12 else []
    checks.append((f'a − 1 = {a - 1} делится на все простые делители m ({", ".join(map(str, primes))})',
                   all((a - 1) % p == 0 for p in primes)))
    if m % 4 == 0:
        checks.append((f'm делится на 4 ⇒ a − 1 = {a - 1} тоже делится на 4', (a - 1) % 4 == 0))
    return checks


def linear_complexity(bits) -> int:
    """Алгоритм Берлекэмпа–Мэсси над GF(2): длина L кратчайшего РСЛОС, порождающего последовательность."""
    s = [int(b) for b in bits]
    n = len(s)
    c, b = [0] * (n + 1), [0] * (n + 1)
    c[0] = b[0] = 1
    length, m = 0, -1
    for i in range(n):
        d = s[i]
        for j in range(1, length + 1):
            d ^= c[j] & s[i - j]
        if d:
            t = c[:]
            shift = i - m
            for j in range(n - shift + 1):
                c[j + shift] ^= b[j]
            if 2 * length <= i:
                length, m, b = i + 1 - length, i, t
    return length


def randu_planes(u: np.ndarray) -> np.ndarray:
    """Значения 9uₖ − 6uₖ₊₁ + uₖ₊₂ для троек подряд. У RANDU это почти целые числа (≤ 15 значений)."""
    return 9 * u[:-2] - 6 * u[1:-1] + u[2:]


def lcg_low_bit_period(gen, bit: int = 0, n: int = 64) -> list[int]:
    """Первые n значений младшего бита ЛКГ: при m = 2ᵏ бит номер j имеет период не больше 2^(j+1)."""
    return [(gen.next() >> bit) & 1 for _ in range(n)]
