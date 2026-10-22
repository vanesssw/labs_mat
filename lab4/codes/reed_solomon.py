"""Код Рида–Соломона над GF(256) — защита данных QR-кода от ошибок.

Это циклический код (как в ЛР №3), только «символ» — не бит, а байт (элемент GF(256)).
Блок из k байтов данных дополняется n байтами коррекции (ECC):

    g(x) = (x − α⁰)(x − α¹)…(x − αⁿ⁻¹)          — образующий многочлен степени n;
    R(x) = D(x)·xⁿ mod g(x)                        — остаток, это и есть байты коррекции;
    C(x) = D(x)·xⁿ + R(x)                          — кодовое слово, делится на g(x).

Значит, C(αⁱ) = 0 для i = 0 … n−1. Если приняли C(x) + E(x), то синдромы Sᵢ = R(αⁱ) = E(αⁱ)
зависят только от ошибки. Код исправляет до ⌊n/2⌋ ошибочных байтов в блоке, причём
неважно, сколько бит в байте испорчено, — поэтому он хорошо переносит «кляксы».

Исправление (классическая схема):
    1) синдромы Sᵢ = r(αⁱ);
    2) алгоритм Берлекэмпа–Мэсси — многочлен локаторов ошибок Λ(x) = ∏(1 − Xₖ·x);
    3) поиск Ченя — перебором находим корни Λ: Xₖ⁻¹ = α⁻ᵖ ⇒ ошибка в байте при степени p;
    4) алгоритм Форни — величина ошибки Yₖ = Xₖ·Ω(Xₖ⁻¹) / Λ′(Xₖ⁻¹), где Ω = S·Λ mod xⁿ.

Многочлены кодового слова хранятся старшим коэффициентом вперёд; Λ, Ω и S — младшим вперёд
(так проще записывать формулы).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .gf256 import EXP, div, inv, mul, poly_eval, poly_mul


class RSError(Exception):
    """Ошибок больше, чем код может исправить."""


def generator_poly(n: int) -> list[int]:
    """g(x) = ∏ (x − αⁱ), i = 0 … n−1. В GF(2⁸) минус = плюс, поэтому множители (x + αⁱ)."""
    g = [1]
    for i in range(n):
        g = poly_mul(g, [1, EXP[i]])
    return g


def remainder(data: list[int], n: int) -> list[int]:
    """Байты коррекции: остаток от деления D(x)·xⁿ на g(x) — деление «столбиком», как в ЛР №3."""
    g = generator_poly(n)
    rem = list(data) + [0] * n
    for i in range(len(data)):
        coef = rem[i]
        if coef:
            for j in range(1, len(g)):
                rem[i + j] ^= mul(g[j], coef)
    return rem[len(data):]


def encode(data: list[int], n: int) -> list[int]:
    """Кодовое слово = данные + n байтов коррекции."""
    return list(data) + remainder(data, n)


def syndromes(word: list[int], n: int) -> list[int]:
    """Sᵢ = r(αⁱ), i = 0 … n−1. Все нули — ошибок не обнаружено."""
    return [poly_eval(word, EXP[i]) for i in range(n)]


def _eval_low(p: list[int], x: int) -> int:
    """Значение многочлена, записанного младшим коэффициентом вперёд."""
    y = 0
    for c in reversed(p):
        y = mul(y, x) ^ c
    return y


def berlekamp_massey(s: list[int]) -> list[int]:
    """Наименьший многочлен Λ(x) (младшим вперёд), порождающий последовательность синдромов.

    Идём по синдромам и считаем «невязку» d — насколько текущий Λ ошибается в предсказании
    очередного синдрома. Если d ≠ 0, исправляем Λ, прибавляя сдвинутую копию прошлого варианта B.
    """
    lam, prev = [1], [1]
    length, shift, b = 0, 1, 1
    for k in range(len(s)):
        d = s[k]
        for i in range(1, length + 1):
            if i < len(lam):
                d ^= mul(lam[i], s[k - i])
        if d == 0:
            shift += 1
            continue
        coef = div(d, b)
        correction = [0] * shift + [mul(coef, c) for c in prev]
        new = [a ^ c for a, c in zip(lam + [0] * (len(correction) - len(lam)),
                                     correction + [0] * (len(lam) - len(correction)))]
        if 2 * length <= k:
            prev, length, b, shift = lam, k + 1 - length, d, 1
        else:
            shift += 1
        lam = new
    while len(lam) > 1 and lam[-1] == 0:
        lam.pop()
    return lam


@dataclass
class Correction:
    """Результат исправления одного блока."""
    word: list[int]                                      # исправленное кодовое слово
    syndromes: list[int]
    locator: list[int] = field(default_factory=list)     # Λ(x), младшим вперёд
    positions: list[int] = field(default_factory=list)   # номера испорченных байтов (с 0, слева)
    magnitudes: list[int] = field(default_factory=list)  # величины ошибок Yₖ (XOR-маски байтов)

    @property
    def errors(self) -> int:
        return len(self.positions)


def decode(word: list[int], n: int) -> Correction:
    """Исправить до ⌊n/2⌋ ошибочных байтов. RSError — если ошибок больше."""
    word = list(word)
    total = len(word)
    s = syndromes(word, n)
    if not any(s):
        return Correction(word, s)
    lam = berlekamp_massey(s)
    errors = len(lam) - 1
    if 2 * errors > n:
        raise RSError(f'обнаружено не меньше {errors} ошибок, а код исправляет только {n // 2}')
    # Поиск Ченя: ошибка в байте j (степень p = total−1−j), если Λ(α⁻ᵖ) = 0
    positions = [j for j in range(total) if _eval_low(lam, EXP[(255 - (total - 1 - j)) % 255]) == 0]
    if len(positions) != errors:
        raise RSError('многочлен локаторов не раскладывается на множители — ошибок слишком много')
    # Алгоритм Форни: Ω(x) = S(x)·Λ(x) mod xⁿ, Yₖ = Xₖ·Ω(Xₖ⁻¹) / Λ′(Xₖ⁻¹)
    omega = [0] * n
    for i, si in enumerate(s):
        for j, lj in enumerate(lam):
            if i + j < n:
                omega[i + j] ^= mul(si, lj)
    deriv = [lam[i] if i % 2 else 0 for i in range(1, len(lam))]   # формальная производная в GF(2⁸)
    magnitudes = []
    for j in positions:
        x = EXP[(total - 1 - j) % 255]
        x_inv = inv(x)
        y = mul(x, div(_eval_low(omega, x_inv), _eval_low(deriv, x_inv)))
        magnitudes.append(y)
        word[j] ^= y
    if any(syndromes(word, n)):
        raise RSError('после исправления синдромы не нулевые — ошибок слишком много')
    return Correction(word, s, lam, positions, magnitudes)
