"""Задание №2: построить групповой код для M кодовых комбинаций, исправляющий ошибки кратности s.

План (как строят такие коды в учебниках):
    1. Число информационных разрядов k = ⌈log2 M⌉ — чтобы 2^k ≥ M разных комбинаций хватило.
    2. Минимальное кодовое расстояние d0 = 2s + 1 — чтобы исправлять все ошибки кратности ≤ s.
    3. Число контрольных разрядов r оцениваем границами:
         граница Хэмминга (необходимое условие):  2^r ≥ C(n,0) + C(n,1) + … + C(n,s);
         граница Варшамова–Гильберта (достаточное): 2^r > C(n−1,0) + … + C(n−1,d0−2);
         граница Грисмера (необходимое для линейных кодов): n ≥ d0 + ⌈d0/2⌉ + … + ⌈d0/2^(k−1)⌉.
       Код с меньшим r, чем по Хэммингу, невозможен; с r по Варшамову–Гильберту — точно существует.
    4. Подбираем проверочную матрицу P (k строк по r разрядов). Комбинация, составленная
       из j строк G, имеет в информационной части ровно j единиц, поэтому её контрольная часть
       должна иметь вес не меньше d0 − j:
         вес каждой строки P ≥ d0 − 1,
         вес суммы любых двух строк ≥ d0 − 2,
         вес суммы любых трёх строк ≥ d0 − 3, и т. д.
       Тогда вес любой ненулевой комбинации ≥ d0, а значит, и кодовое расстояние ≥ d0.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from itertools import combinations
from math import ceil, comb, log2

from .gf2 import identity
from .group_code import GroupCode


class SearchTimeout(Exception):
    pass


@dataclass
class BoundRow:
    """Одна строка таблицы оценки числа контрольных разрядов."""
    n: int
    r: int
    hamming_sum: int        # Σ C(n, i), i = 0 … s — сколько синдромов нужно для исправления
    hamming_ok: bool        # 2^r ≥ hamming_sum
    vg_sum: int             # Σ C(n−1, i), i = 0 … d0−2
    vg_ok: bool             # 2^r > vg_sum
    search: str             # 'found' — код найден, 'none' — перебор доказал, что кода нет,
                            # 'griesmer' — невозможно по границе Грисмера,
                            # 'timeout' — перебор не уложился во время, '' — не проверялось


@dataclass
class Design:
    M: int
    s: int
    k: int
    d: int
    rows: list[BoundRow] = field(default_factory=list)
    code: GroupCode | None = None
    subset_check: list[tuple[int, int, int]] = field(default_factory=list)  # (j строк, требуемый вес, минимум)


def info_bits(M: int) -> int:
    """k = ⌈log2 M⌉: наименьшее k, при котором 2^k ≥ M."""
    return max(1, ceil(log2(M))) if M > 1 else 1


def hamming_sum(n: int, s: int) -> int:
    """Число векторов ошибок кратности 0 … s: каждому нужен свой синдром."""
    return sum(comb(n, i) for i in range(s + 1))


def vg_sum(n: int, d: int) -> int:
    """Сумма из границы Варшамова–Гильберта: Σ C(n−1, i), i = 0 … d−2."""
    return sum(comb(n - 1, i) for i in range(d - 1))


def griesmer_sum(k: int, d: int) -> int:
    """Граница Грисмера для линейных кодов: n ≥ d + ⌈d/2⌉ + ⌈d/4⌉ + … (k слагаемых)."""
    return sum(-(-d // 2 ** i) for i in range(k))


def _popcount(x: int) -> int:
    return bin(x).count('1')


def search_check_part(k: int, r: int, d: int, time_limit: float = 3.0) -> list[list[int]] | None:
    """Перебор с возвратом: ищем k строк по r бит, удовлетворяющих условиям на веса сумм строк.

    Возвращает строки P или None, если такой матрицы нет. SearchTimeout — если не уложились во время.
    Перестановка столбцов не меняет свойств кода, поэтому первая строка берётся вида 11…100…0.
    """
    deadline = time.monotonic() + time_limit
    counter = [0]

    def extend(rows: list[int], sums: list[tuple[int, int]], start: int):
        if len(rows) == k:
            return rows
        for v in range(start, 1 << r):
            counter[0] += 1
            if counter[0] % 4096 == 0 and time.monotonic() > deadline:
                raise SearchTimeout
            if _popcount(v) < d - 1:
                continue
            if any(_popcount(v ^ x) < d - 1 - j for x, j in sums):
                continue
            new = sums + [(v ^ x, j + 1) for x, j in sums if j + 1 <= d - 2] + [(v, 1)]
            found = extend(rows + [v], new, v + 1)
            if found:
                return found
        return None

    for w in range(d - 1, r + 1):
        first = ((1 << w) - 1) << (r - w)          # единицы в старших разрядах: 11110000
        found = extend([first], [(first, 1)], 1)
        if found:
            ordered = sorted(found, reverse=True)
            return [[int(b) for b in format(v, f'0{r}b')] for v in ordered]
    return None


def check_subsets(P, d: int) -> list[tuple[int, int, int]]:
    """Для j = 1 … d−1: (j, требуемый вес d − j, фактический минимальный вес суммы любых j строк P)."""
    out = []
    k = len(P)
    for j in range(1, min(k, d - 1) + 1):
        least = min(sum(sum(col) % 2 for col in zip(*(P[i] for i in rows)))
                    for rows in combinations(range(k), j))
        out.append((j, d - j, least))
    return out


def design_code(M: int, s: int, time_limit: float = 3.0, max_r: int = 24) -> Design:
    """Подобрать код минимальной длины для M комбинаций, исправляющий ошибки кратности ≤ s."""
    if M < 2:
        raise ValueError('число комбинаций должно быть не меньше 2')
    if s < 1:
        raise ValueError('кратность исправляемых ошибок должна быть не меньше 1')
    k = info_bits(M)
    d = 2 * s + 1
    res = Design(M, s, k, d)
    for r in range(1, max_r + 1):
        n = k + r
        hs, vs = hamming_sum(n, s), vg_sum(n, d)
        row = BoundRow(n, r, hs, 2 ** r >= hs, vs, 2 ** r > vs, '')
        res.rows.append(row)
        if not row.hamming_ok:
            continue                                  # граница Хэмминга: такой код невозможен
        if n < griesmer_sum(k, d):
            row.search = 'griesmer'                   # граница Грисмера: линейного кода нет
            continue
        try:
            P = search_check_part(k, r, d, time_limit)
        except SearchTimeout:
            row.search = 'timeout'
            continue
        if P is None:
            row.search = 'none'
            continue
        row.search = 'found'
        res.code = GroupCode(identity(k), P, f'({n},{k})')
        res.subset_check = check_subsets(P, d)
        break
    return res
