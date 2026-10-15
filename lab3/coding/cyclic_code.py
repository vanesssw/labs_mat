"""Циклический (n, k)-код с образующим многочленом K(x).

Обозначения (как в методичке):
    K(x) — образующий (порождающий) многочлен степени r = nк;
    G(x) — информационная часть (k = nи разрядов), F(x) — кодовая комбинация (n разрядов);
    R(x) — остаток от деления.

Кодирование (систематическое, информационные разряды слева):
    F(x) = G(x)·x^r + R(x),   где R(x) = остаток от деления G(x)·x^r на K(x).
Тогда F(x) делится на K(x) без остатка — это и есть признак разрешённой комбинации.

Проверка: принятую комбинацию делят на K(x). Остаток 0 — ошибок не обнаружено.
Ненулевой остаток зависит только от ошибки: остаток(F ⊕ E) = остаток(E).
Одиночной ошибке в разряде с номером i (слева, с 1) соответствует E(x) = x^(n−i),
поэтому её остаток — x^(n−i) mod K(x).

Если K(x) делит xⁿ + 1 (n кратно периоду многочлена), код по-настоящему циклический:
циклический сдвиг разрешённой комбинации — снова разрешённая комбинация.
Если n меньше периода, код называется укороченным: это циклический код длины «период»,
у которого старшие разряды всегда нулевые и потому не передаются.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from itertools import combinations

from .gf2 import all_vectors, error_patterns, identity, to_str, vec_mat, weight, xor
from .group_code import Decoded
from .polynomials import degree, mod, monomial, mul, period, trim


@dataclass
class TrapStep:
    """Один шаг исправления ошибки циклическими сдвигами (алгоритм из методички)."""
    shift: int              # на сколько разрядов влево сдвинута комбинация
    word: list[int]         # сдвинутая комбинация
    remainder: list[int]    # остаток от её деления на K(x)
    weight: int             # вес остатка W


@dataclass
class Trapping:
    """Полный ход алгоритма «ловли» ошибки сдвигами."""
    length: int                    # длина, на которой выполняются сдвиги (n или период)
    steps: list[TrapStep]
    fixed_shifted: list[int] | None  # сдвинутая комбинация после сложения с остатком
    result: list[int] | None       # исправленная комбинация (None — исправить не удалось)


class CyclicCode:
    """Циклический (или укороченный циклический) код длины n с образующим многочленом g."""

    def __init__(self, g, n: int, name: str = '') -> None:
        self.g = trim(g)
        self.r = degree(self.g)
        if self.r < 1:
            raise ValueError('степень образующего многочлена должна быть не меньше 1')
        if self.g[-1] != 1:
            raise ValueError('у образующего многочлена свободный член должен быть равен 1')
        self.n = n
        self.k = n - self.r
        if self.k < 1:
            raise ValueError(f'длина кода n = {n} должна быть больше степени многочлена r = {self.r}')
        self.period = period(self.g)
        self.name = name or f'({self.n},{self.k})'

    # --- свойства многочлена и кода ---
    @property
    def is_cyclic(self) -> bool:
        """True, если K(x) делит xⁿ + 1 — тогда код в точности циклический."""
        return not any(mod(monomial(self.n)[:-1] + [1], self.g))

    def label(self, pos: int) -> str:
        """a1…ak — информационные разряды, b1…br — контрольные."""
        return f'a{pos}' if pos <= self.k else f'b{pos - self.k}'

    def degree_of(self, pos: int) -> int:
        """Разряд с номером pos (слева, с 1) соответствует степени x^(n − pos)."""
        return self.n - pos

    # --- кодирование ---
    def encode_parts(self, info) -> tuple[list[int], list[int], list[int]]:
        """(G(x)·x^r, остаток R(x), кодовая комбинация F(x) = G(x)·x^r + R(x))."""
        if len(info) != self.k:
            raise ValueError(f'информационная часть должна содержать {self.k} разрядов')
        shifted = list(info) + [0] * self.r
        rem = mod(shifted, self.g)
        return shifted, rem, list(info) + rem

    def encode(self, info) -> list[int]:
        return self.encode_parts(info)[2]

    def info_of(self, word) -> list[int]:
        return list(word[:self.k])

    def unit_remainders(self) -> list[tuple[int, list[int]]]:
        """Остатки от деления «единицы с нулями» x^m на K(x) для строк образующей матрицы.

        Строка i (с 1) единичной матрицы — это x^(k−i); после умножения на x^r получаем x^(n−i).
        Возвращает [(степень n − i, остаток)] для i = 1 … k.
        """
        return [(self.n - i, mod(monomial(self.n - i), self.g)) for i in range(1, self.k + 1)]

    def generator_matrix(self) -> list[list[int]]:
        """Образующая матрица по методичке: единичная матрица k×k + дополнительная из остатков."""
        return [e + rem for e, (_, rem) in zip(identity(self.k), self.unit_remainders())]

    def generator_matrix_by_multiplication(self) -> list[list[int]]:
        """Второй способ: строки — K(x)·x^(k−i), то есть многочлен, сдвинутый влево на k − i разрядов."""
        rows = []
        for i in range(1, self.k + 1):
            row = mul(self.g, monomial(self.k - i))
            rows.append([0] * (self.n - len(row)) + row)
        return rows

    # --- проверка ---
    def syndrome(self, word) -> list[int]:
        """Остаток от деления принятой комбинации на K(x) (r разрядов)."""
        if len(word) != self.n:
            raise ValueError(f'комбинация должна содержать {self.n} разрядов')
        return mod(word, self.g)

    def syndrome_of_errors(self, positions) -> list[int]:
        """Остаток вектора ошибки = сумма остатков x^(n−i) для всех ошибочных разрядов i."""
        s = [0] * self.r
        for p in positions:
            s = xor(s, mod(monomial(self.degree_of(p)), self.g))
        return s

    def single_error_table(self) -> list[tuple[int, list[int]]]:
        """[(номер разряда, остаток одиночной ошибки в нём)] для всех n разрядов."""
        return [(p, self.syndrome_of_errors((p,))) for p in range(1, self.n + 1)]

    def errors_with_syndrome(self, syndrome, multiplicity: int) -> list[tuple[int, ...]]:
        """Все наборы из multiplicity ошибочных разрядов, дающие заданный остаток."""
        return [pos for pos in combinations(range(1, self.n + 1), multiplicity)
                if self.syndrome_of_errors(pos) == list(syndrome)]

    def codewords(self) -> list[tuple[list[int], list[int]]]:
        return [(a, self.encode(a)) for a in all_vectors(self.k)]

    @cached_property
    def min_distance(self) -> int:
        """d0 — минимальный вес ненулевой комбинации (циклический код тоже групповой)."""
        if self.k > 16:
            raise ValueError('слишком много комбинаций для полного перебора')
        return min(weight(c) for a, c in self.codewords() if any(a))

    @property
    def detects(self) -> int:
        return self.min_distance - 1

    @property
    def corrects(self) -> int:
        return (self.min_distance - 1) // 2

    @cached_property
    def _decoder(self) -> dict[str, tuple[int, ...]]:
        table: dict[str, tuple[int, ...]] = {}
        for pos in error_patterns(self.n, self.corrects):
            table.setdefault(to_str(self.syndrome_of_errors(pos)), pos)
        return table

    def decode(self, word) -> Decoded:
        """Проверка по остатку и исправление ошибки кратности ≤ s по таблице остатков."""
        word = list(word)
        s = self.syndrome(word)
        if not any(s):
            return Decoded(word, s, 'ok', (), word, self.info_of(word))
        pos = self._decoder.get(to_str(s))
        if pos is None:
            return Decoded(word, s, 'detected', (), word, self.info_of(word))
        fixed = word[:]
        for p in pos:
            fixed[p - 1] ^= 1
        return Decoded(word, s, 'corrected', pos, fixed, self.info_of(fixed))

    # --- исправление сдвигами (п. 6 раздела 3.2.1.1 методички) ---
    def trap(self, word, s: int | None = None) -> Trapping:
        """Исправление ошибки циклическими сдвигами, как в методичке.

        1) Делим комбинацию на K(x) и считаем вес остатка W.
        2) Если W ≤ s — ошибка «попала» в контрольные разряды: складываем комбинацию с остатком.
        3) Иначе сдвигаем комбинацию циклически влево на 1 разряд и снова делим.
        4) После сложения с остатком сдвигаем вправо на столько же разрядов, на сколько сдвигали влево.

        Для укороченного кода сдвиги выполняются на полной длине (периоде), а недостающие
        старшие разряды равны нулю.
        """
        s = self.corrects if s is None else s
        length = self.n if self.is_cyclic or self.period is None else self.period
        v = [0] * (length - self.n) + list(word)
        steps: list[TrapStep] = []
        for t in range(length):
            shifted = v[t:] + v[:t]
            rem = mod(shifted, self.g)
            w = weight(rem)
            steps.append(TrapStep(t, shifted, rem, w))
            if w == 0 and t == 0:
                return Trapping(length, steps, shifted, list(word))
            if 0 < w <= s:
                fixed = xor(shifted, [0] * (length - self.r) + rem)
                back = fixed[length - t:] + fixed[:length - t] if t else fixed
                if any(back[:length - self.n]):
                    break                         # «исправление» вылезло за пределы укороченного кода
                return Trapping(length, steps, fixed, back[length - self.n:])
        return Trapping(length, steps, None, None)
