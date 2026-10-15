"""Линейный групповой (n, k)-код.

Обозначения (как в методичке):
    k = nи    — число информационных разрядов (a1 … ak);
    r = nк    — число контрольных (проверочных) разрядов (b1 … br);
    n = k + r — длина кодовой комбинации;
    G = [A | P] — образующая (порождающая) матрица k×n:
        A — информационная часть («Группа 1» — единичная матрица, «Группа 2» — обратная диагональ),
        P — проверочная (дополнительная) матрица k×r из табл. 2.1;
    H — проверочная матрица r×n; каждая её строка — одно контрольное соотношение;
    S = H·vᵀ — синдром (контрольный синдром, опознаватель) принятой комбинации v.

Главные факты:
    * код линейный: сумма двух кодовых комбинаций — снова кодовая комбинация;
    * поэтому минимальное кодовое расстояние d0 = минимальному весу ненулевой комбинации;
    * код обнаруживает r = d0 − 1 ошибок и исправляет s = ⌊(d0 − 1)/2⌋ ошибок;
    * синдром зависит только от вектора ошибки e: S(c ⊕ e) = S(c) ⊕ S(e) = S(e),
      а синдром одиночной ошибки в i-м разряде — это i-й столбец матрицы H.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from itertools import combinations

from .gf2 import (all_vectors, anti_identity, dot, error_patterns, identity, inverse, mat_mul,
                  to_str, transpose, vec_mat, weight, xor)


@dataclass
class Decoded:
    """Результат проверки и исправления принятой комбинации."""
    received: list[int]
    syndrome: list[int]          # для циклического кода — остаток от деления
    status: str                  # 'ok' — ошибок нет, 'corrected' — исправлено, 'detected' — только обнаружено
    positions: tuple[int, ...]   # разряды, которые декодер счёл ошибочными (нумерация с 1)
    corrected: list[int]         # комбинация после исправления
    info: list[int]              # информационная часть после исправления

    @property
    def message(self) -> str:
        if self.status == 'ok':
            return 'синдром нулевой — ошибок не обнаружено'
        if self.status == 'corrected':
            where = ', '.join(map(str, self.positions))
            return f'ошибка в разряде {where} — исправлена' if len(self.positions) == 1 else \
                f'ошибки в разрядах {where} — исправлены'
        return 'синдром не соответствует исправимой ошибке — ошибка обнаружена, но не исправлена'


class GroupCode:
    """Групповой код, заданный образующей матрицей G = [A | P]."""

    def __init__(self, info_part, check_part, name: str = '') -> None:
        if len(info_part) != len(check_part):
            raise ValueError('у информационной и проверочной частей разное число строк')
        self.A = [list(row) for row in info_part]
        self.P = [list(row) for row in check_part]
        self.k = len(self.A)
        self.r = len(self.P[0])
        self.n = self.k + self.r
        self.name = name or f'({self.n},{self.k})'
        self.G = [a + p for a, p in zip(self.A, self.P)]
        self.A_inv = inverse(self.A)
        # Комбинация c = (u | b), где u = a·A — информационные разряды в том виде, как они стоят
        # в комбинации, а b = a·P = u·A⁻¹·P. Обозначим Q = A⁻¹·P, тогда b = u·Q.
        self.Q = mat_mul(self.A_inv, self.P)
        # Проверочная матрица H = [Qᵀ | I]: G·Hᵀ = 0, то есть каждая кодовая комбинация
        # удовлетворяет всем контрольным соотношениям.
        self.H = [q + e for q, e in zip(transpose(self.Q), identity(self.r))]

    @classmethod
    def from_variant(cls, check_part, group: int = 1, name: str = '') -> GroupCode:
        """Код по варианту из табл. 2.1: group = 1 (единичная матрица) или 2 (обратная диагональ)."""
        k = len(check_part)
        info = identity(k) if group == 1 else anti_identity(k)
        return cls(info, check_part, name)

    # --- обозначения разрядов ---
    def label(self, pos: int) -> str:
        """Номер разряда (с 1) → обозначение: a1…ak — информационные, b1…br — контрольные."""
        return f'a{pos}' if pos <= self.k else f'b{pos - self.k}'

    def relation_terms(self, j: int) -> list[int]:
        """Номера информационных разрядов, входящих в j-е контрольное соотношение (j с 1)."""
        return [i + 1 for i in range(self.k) if self.Q[i][j - 1]]

    def relation_text(self, j: int) -> str:
        """j-е контрольное соотношение: «b1 = a3 ⊕ a4 ⊕ a5»."""
        terms = self.relation_terms(j)
        return f'b{j} = ' + (' ⊕ '.join(f'a{i}' for i in terms) if terms else '0')

    def check_text(self, j: int) -> str:
        """j-й разряд синдрома: «S1 = b1 ⊕ a3 ⊕ a4 ⊕ a5» (= 0 у правильной комбинации)."""
        return f'S{j} = b{j}' + ''.join(f' ⊕ a{i}' for i in self.relation_terms(j))

    # --- кодирование и проверка ---
    def encode(self, info) -> list[int]:
        """Кодовая комбинация = сумма по модулю 2 строк G, где в информационной части стоят единицы."""
        if len(info) != self.k:
            raise ValueError(f'информационная часть должна содержать {self.k} разрядов')
        return vec_mat(info, self.G)

    def info_of(self, word) -> list[int]:
        """Информационная часть сообщения a = u·A⁻¹ (в «Группе 1» это просто первые k разрядов)."""
        return vec_mat(word[:self.k], self.A_inv)

    def syndrome(self, word) -> list[int]:
        """Синдром S = H·vᵀ: каждый разряд — проверка одного контрольного соотношения."""
        if len(word) != self.n:
            raise ValueError(f'комбинация должна содержать {self.n} разрядов')
        return [dot(row, word) for row in self.H]

    def column(self, pos: int) -> list[int]:
        """Столбец H с номером pos — синдром одиночной ошибки в этом разряде."""
        return [row[pos - 1] for row in self.H]

    def syndrome_of_errors(self, positions) -> list[int]:
        """Синдром вектора ошибки = сумма столбцов H в ошибочных разрядах."""
        s = [0] * self.r
        for p in positions:
            s = xor(s, self.column(p))
        return s

    # --- свойства кода ---
    def codewords(self) -> list[tuple[list[int], list[int]]]:
        """Все 2^k пар (информационная часть, кодовая комбинация)."""
        return [(a, self.encode(a)) for a in all_vectors(self.k)]

    @cached_property
    def min_distance(self) -> int:
        """d0 = минимальный вес ненулевой комбинации (свойство группового кода)."""
        return min(weight(c) for a, c in self.codewords() if any(a))

    @property
    def detects(self) -> int:
        """Гарантированно обнаруживаемая кратность ошибок: r = d0 − 1."""
        return self.min_distance - 1

    @property
    def corrects(self) -> int:
        """Гарантированно исправляемая кратность ошибок: s = ⌊(d0 − 1)/2⌋."""
        return (self.min_distance - 1) // 2

    def errors_with_syndrome(self, syndrome, multiplicity: int) -> list[tuple[int, ...]]:
        """Все наборы из multiplicity ошибочных разрядов, дающие заданный синдром."""
        return [pos for pos in combinations(range(1, self.n + 1), multiplicity)
                if self.syndrome_of_errors(pos) == list(syndrome)]

    def identifier_table(self, max_weight: int) -> list[tuple[tuple[int, ...], list[int]]]:
        """Таблица опознавателей: (ошибочные разряды, синдром) для всех ошибок кратности ≤ max_weight."""
        return [(pos, self.syndrome_of_errors(pos)) for pos in error_patterns(self.n, max_weight)]

    @cached_property
    def _decoder(self) -> dict[str, tuple[int, ...]]:
        """Синдром → ошибочные разряды для всех исправимых ошибок (кратность ≤ s)."""
        table: dict[str, tuple[int, ...]] = {}
        for pos, s in self.identifier_table(self.corrects):
            table.setdefault(to_str(s), pos)
        return table

    def decode(self, word) -> Decoded:
        """Проверить комбинацию по синдрому и исправить ошибку, если её кратность ≤ s."""
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
