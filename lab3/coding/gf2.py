"""Арифметика по модулю 2 — фундамент всех двоичных помехоустойчивых кодов.

Поле GF(2) состоит из двух элементов {0, 1}. Правила (как в методичке):
    сложение по модулю 2 (⊕):  0⊕0 = 0,  0⊕1 = 1,  1⊕0 = 1,  1⊕1 = 0;
    умножение:                 0·0 = 0,  0·1 = 0,  1·0 = 0,  1·1 = 1.
Вычитание совпадает со сложением (1 − 1 = 0 = 1 ⊕ 1), поэтому «разность»
кодовых векторов — это тоже их сумма по модулю 2.

Вектор (кодовая комбинация) хранится как список нулей и единиц: [1, 0, 1, 1].
Матрица — список строк-векторов. Разряды нумеруются слева направо с единицы.
"""
from __future__ import annotations

from itertools import combinations, product


def bits(text: str) -> list[int]:
    """Строка '1 0 1 1' или '1011' → список [1, 0, 1, 1] (пробелы игнорируются)."""
    clean = ''.join(text.split())
    if not clean or any(ch not in '01' for ch in clean):
        raise ValueError(f'ожидалась строка из нулей и единиц, а получено «{text.strip()}»')
    return [int(ch) for ch in clean]


def to_str(v, sep: str = '') -> str:
    """[1, 0, 1, 1] → '1011' (sep — разделитель между разрядами)."""
    return sep.join(str(b) for b in v)


def xor(u, v) -> list[int]:
    """Поразрядная сумма по модулю 2: 1011 ⊕ 0110 = 1101."""
    if len(u) != len(v):
        raise ValueError('векторы разной длины')
    return [a ^ b for a, b in zip(u, v)]


def weight(v) -> int:
    """Вес Хэмминга w(v) — число ненулевых (единичных) разрядов: w(1011) = 3."""
    return sum(v)


def distance(u, v) -> int:
    """Кодовое расстояние Хэмминга d(u, v) = w(u ⊕ v) — в скольких разрядах векторы различаются."""
    return weight(xor(u, v))


def dot(u, v) -> int:
    """Скалярное произведение по модулю 2: (u1·v1 ⊕ u2·v2 ⊕ …). Равно 1, если общих единиц нечётное число."""
    return sum(a & b for a, b in zip(u, v)) % 2


def vec_mat(v, m) -> list[int]:
    """Вектор × матрица = сумма по модулю 2 тех строк m, напротив которых в v стоит 1.

    Именно так строится кодовая комбинация группового кода: складываются строки
    образующей матрицы, соответствующие единицам информационной части.
    """
    out = [0] * len(m[0])
    for b, row in zip(v, m):
        if b:
            out = xor(out, row)
    return out


def mat_mul(a, b) -> list[list[int]]:
    """Произведение матриц по модулю 2."""
    return [vec_mat(row, b) for row in a]


def transpose(m) -> list[list[int]]:
    """Транспонирование: строки становятся столбцами."""
    return [list(col) for col in zip(*m)]


def identity(k: int) -> list[list[int]]:
    """Единичная матрица k×k (единицы на главной диагонали) — «Группа 1» в методичке."""
    return [[int(i == j) for j in range(k)] for i in range(k)]


def anti_identity(k: int) -> list[list[int]]:
    """Единицы на побочной диагонали — «Группа 2» в методичке."""
    return [[int(i + j == k - 1) for j in range(k)] for i in range(k)]


def inverse(m) -> list[list[int]]:
    """Обратная матрица по модулю 2 (метод Гаусса–Жордана). Ошибка, если матрица вырождена."""
    k = len(m)
    work = [list(row) + e for row, e in zip(m, identity(k))]
    for col in range(k):
        pivot = next((r for r in range(col, k) if work[r][col]), None)
        if pivot is None:
            raise ValueError('информационная часть образующей матрицы вырождена: строки линейно зависимы')
        work[col], work[pivot] = work[pivot], work[col]
        for r in range(k):
            if r != col and work[r][col]:
                work[r] = xor(work[r], work[col])
    return [row[k:] for row in work]


def all_vectors(k: int):
    """Все 2^k двоичных векторов длины k по порядку: 00…0, 00…1, …, 11…1."""
    return (list(v) for v in product((0, 1), repeat=k))


def error_vector(n: int, positions) -> list[int]:
    """Вектор ошибки длины n с единицами в указанных разрядах (нумерация с 1)."""
    e = [0] * n
    for p in positions:
        e[p - 1] ^= 1
    return e


def error_patterns(n: int, max_weight: int):
    """Все наборы ошибочных разрядов кратности 1, 2, …, max_weight (кортежи номеров с 1)."""
    for t in range(1, max_weight + 1):
        yield from combinations(range(1, n + 1), t)
