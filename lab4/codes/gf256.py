"""Поле Галуа GF(2⁸) = GF(256) — арифметика, на которой работает код Рида–Соломона в QR.

Элемент поля — байт 0…255. Его биты — коэффициенты многочлена степени ≤ 7 над GF(2)
(как в ЛР №3): 0b10000011 = x⁷ + x + 1.

    сложение   = XOR байтов (коэффициенты складываются по модулю 2), вычитание — то же самое;
    умножение  = умножение многочленов по модулю неприводимого многочлена
                 p(x) = x⁸ + x⁴ + x³ + x² + 1 (0x11D) — так в стандарте QR.

Элемент α = 2 (то есть x) — примитивный: его степени α⁰, α¹, …, α²⁵⁴ перебирают все 255
ненулевых элементов. Поэтому любой ненулевой элемент a = α^log(a), и умножение сводится
к сложению логарифмов: a·b = α^(log a + log b). Таблицы EXP и LOG считаются один раз.
"""
from __future__ import annotations

PRIMITIVE = 0x11D          # x⁸ + x⁴ + x³ + x² + 1

EXP = [0] * 512            # EXP[i] = αⁱ (продублировано до 511, чтобы не брать остаток при сложении логарифмов)
LOG = [0] * 256            # LOG[a] = i, если αⁱ = a (LOG[0] не определён)


def _build_tables() -> None:
    x = 1
    for i in range(255):
        EXP[i] = x
        LOG[x] = i
        x <<= 1                    # умножение на α = x
        if x & 0x100:              # степень стала 8 — вычитаем (XOR) p(x)
            x ^= PRIMITIVE
    for i in range(255, 512):
        EXP[i] = EXP[i - 255]


_build_tables()


def add(a: int, b: int) -> int:
    """Сложение = вычитание = XOR."""
    return a ^ b


def mul(a: int, b: int) -> int:
    """Умножение через логарифмы: a·b = α^(log a + log b)."""
    if a == 0 or b == 0:
        return 0
    return EXP[LOG[a] + LOG[b]]


def div(a: int, b: int) -> int:
    """Деление: a / b = α^(log a − log b)."""
    if b == 0:
        raise ZeroDivisionError('деление на ноль в GF(256)')
    if a == 0:
        return 0
    return EXP[(LOG[a] - LOG[b]) % 255]


def inv(a: int) -> int:
    """Обратный элемент: a⁻¹ = α^(255 − log a), так как α²⁵⁵ = 1."""
    return div(1, a)


def power(a: int, n: int) -> int:
    """Степень aⁿ."""
    if a == 0:
        return 0 if n else 1
    return EXP[(LOG[a] * n) % 255]


def mul_slow(a: int, b: int) -> int:
    """Умножение «в столбик» (сдвиги и XOR с приведением по p(x)) — для проверки таблиц и объяснения."""
    result = 0
    while b:
        if b & 1:
            result ^= a
        b >>= 1
        a <<= 1
        if a & 0x100:
            a ^= PRIMITIVE
    return result


# --- многочлены с коэффициентами из GF(256); старший коэффициент — первый ---

def poly_mul(p: list[int], q: list[int]) -> list[int]:
    out = [0] * (len(p) + len(q) - 1)
    for i, a in enumerate(p):
        if a:
            for j, b in enumerate(q):
                out[i + j] ^= mul(a, b)
    return out


def poly_eval(p: list[int], x: int) -> int:
    """Значение многочлена в точке x по схеме Горнера."""
    y = 0
    for c in p:
        y = mul(y, x) ^ c
    return y


def poly_add(p: list[int], q: list[int]) -> list[int]:
    n = max(len(p), len(q))
    p = [0] * (n - len(p)) + list(p)
    q = [0] * (n - len(q)) + list(q)
    return [a ^ b for a, b in zip(p, q)]


def poly_scale(p: list[int], c: int) -> list[int]:
    return [mul(a, c) for a in p]
