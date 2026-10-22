"""Датчики псевдослучайных чисел — собственная реализация.

Любой такой датчик — детерминированный автомат: состояние Sₙ₊₁ = f(Sₙ), выход xₙ = g(Sₙ).
Состояний конечное число, поэтому последовательность обязательно зацикливается: длина цикла —
период. «Псевдо» — потому что всё определяется начальным значением (зерном, seed): одно и то же
зерно даёт одну и ту же последовательность.

У каждого датчика:
    next()    — следующее целое число в диапазоне [0, modulus);
    uniform() — то же, делённое на modulus: число в [0, 1);
    bits(n)   — поток из n бит: из каждого числа берутся k = ⌊log₂ modulus⌋ старших бит.
"""
from __future__ import annotations

import os
import random
from math import floor, log2


class Generator:
    key = ''
    name = ''
    formula = ''
    modulus = 2 ** 32

    def next(self) -> int:
        raise NotImplementedError

    def numbers(self, n: int) -> list[int]:
        return [self.next() for _ in range(n)]

    def uniform(self) -> float:
        return self.next() / self.modulus

    def uniforms(self, n: int) -> list[float]:
        m = self.modulus
        return [self.next() / m for _ in range(n)]

    @property
    def word_bits(self) -> int:
        """Сколько бит даёт одно число: k = ⌊log₂ m⌋."""
        return floor(log2(self.modulus))

    def bits(self, n: int) -> list[int]:
        k = self.word_bits
        m = self.modulus
        out: list[int] = []
        while len(out) < n:
            x = self.next()
            if m != 1 << k:
                x = x * (1 << k) // m          # равномерно «сжимаем» диапазон до k бит
            out += [(x >> (k - 1 - i)) & 1 for i in range(k)]
        return out[:n]

    def describe(self) -> str:
        return self.formula


# ==========================================================================
# 1. Метод середины квадрата (фон Нейман, 1946)
# ==========================================================================

class MiddleSquare(Generator):
    """xₙ₊₁ = средние d цифр числа xₙ², записанного 2d цифрами."""
    key = 'middle'
    name = 'Середина квадрата (фон Нейман)'

    def __init__(self, seed: int = 5772, digits: int = 4) -> None:
        if digits % 2:
            raise ValueError('число цифр должно быть чётным')
        self.digits = digits
        self.modulus = 10 ** digits
        self.state = seed % self.modulus
        self.formula = f'xₙ₊₁ = средние {digits} цифры числа xₙ² (записанного {2 * digits} цифрами)'

    def step(self, x: int) -> tuple[str, int]:
        sq = str(x * x).zfill(2 * self.digits)
        d = self.digits
        return sq, int(sq[d // 2:d // 2 + d])

    def next(self) -> int:
        _, self.state = self.step(self.state)
        return self.state


# ==========================================================================
# 2. Линейный конгруэнтный генератор (Лемер, 1949)
# ==========================================================================

LCG_PRESETS = {
    'ansi': ('ANSI C rand()', 1103515245, 12345, 2 ** 31),
    'nr': ('Numerical Recipes', 1664525, 1013904223, 2 ** 32),
    'minstd': ('MINSTD (Парк–Миллер)', 16807, 0, 2 ** 31 - 1),
    'randu': ('RANDU (IBM, 1960-е)', 65539, 0, 2 ** 31),
    'toy': ('Учебный: m = 64', 13, 7, 64),
}


class LCG(Generator):
    """xₙ₊₁ = (a·xₙ + c) mod m."""
    key = 'lcg'

    def __init__(self, a: int = 1103515245, c: int = 12345, m: int = 2 ** 31, seed: int = 1, name: str = '') -> None:
        if m < 2 or not 0 < a < m or not 0 <= c < m:
            raise ValueError('нужно 0 < a < m, 0 ≤ c < m')
        self.a, self.c, self.modulus = a, c, m
        self.state = seed % m
        if c == 0 and self.state == 0:
            self.state = 1                       # мультипликативный датчик застревает в нуле
        self.name = name or f'ЛКГ a = {a}, c = {c}, m = {m}'
        self.formula = f'xₙ₊₁ = ({a}·xₙ + {c}) mod {m}'

    @classmethod
    def preset(cls, key: str, seed: int = 1) -> LCG:
        name, a, c, m = LCG_PRESETS[key]
        g = cls(a, c, m, seed, name)
        g.key = key
        return g

    def next(self) -> int:
        self.state = (self.a * self.state + self.c) % self.modulus
        return self.state


# ==========================================================================
# 3. Регистр сдвига с линейной обратной связью (РСЛОС, LFSR)
# ==========================================================================

LFSR_POLYS = {
    5: (5, 2),                # x⁵ + x² + 1 — тот же примитивный многочлен, что в ЛР №3
    16: (16, 14, 13, 11),     # x¹⁶ + x¹⁴ + x¹³ + x¹¹ + 1
    32: (32, 22, 2, 1),       # x³² + x²² + x² + x + 1
}


class LFSR(Generator):
    """Регистр из n бит; новый бит = XOR отводов; на выходе — выдвигаемый бит.

    Если многочлен обратной связи примитивный, регистр проходит все 2ⁿ − 1 ненулевых состояний.
    """
    key = 'lfsr'

    def __init__(self, taps=(32, 22, 2, 1), seed: int = 0xACE1ACE1) -> None:
        self.n = taps[0]
        self.taps = tuple(taps)
        self.state = seed & ((1 << self.n) - 1) or 1
        self.modulus = 2 ** 32
        poly = ' + '.join(f'x^{t}' if t > 1 else 'x' for t in taps) + ' + 1'
        self.name = f'РСЛОС, {self.n} бит'
        self.formula = f'новый бит = XOR отводов {", ".join(map(str, taps))}; многочлен {poly}'

    def next_bit(self) -> int:
        s = self.state
        bit = 0
        for t in self.taps:
            bit ^= s >> (self.n - t)
        bit &= 1
        out = s & 1
        self.state = (s >> 1) | (bit << (self.n - 1))
        return out

    def next(self) -> int:
        x = 0
        for _ in range(32):
            x = (x << 1) | self.next_bit()
        return x

    def bits(self, n: int) -> list[int]:
        return [self.next_bit() for _ in range(n)]


# ==========================================================================
# 4. Xorshift (Марсалья, 2003)
# ==========================================================================

class Xorshift32(Generator):
    """x ^= x << 13; x ^= x >> 17; x ^= x << 5 — три сдвига и XOR, период 2³² − 1."""
    key = 'xorshift'
    name = 'Xorshift32 (Марсалья)'
    formula = 'x ← x ⊕ (x ≪ 13); x ← x ⊕ (x ≫ 17); x ← x ⊕ (x ≪ 5)'

    def __init__(self, seed: int = 2463534242) -> None:
        self.state = seed & 0xFFFFFFFF or 1

    def next(self) -> int:
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x
        return x


# ==========================================================================
# 5. Вихрь Мерсенна MT19937 (Мацумото, Нисимура, 1997)
# ==========================================================================

class MT19937(Generator):
    """Состояние — 624 слова по 32 бита; период 2¹⁹⁹³⁷ − 1 (простое число Мерсенна).

    twist: новое слово = mt[k + 397] ⊕ (склейка старшего бита mt[k] и младших 31 бит mt[k+1]) · A;
    tempering (закалка): y ^= y≫11; y ^= (y≪7) & 0x9D2C5680; y ^= (y≪15) & 0xEFC60000; y ^= y≫18.
    Это тот же алгоритм, что в модуле random языка Python, — результат совпадает бит в бит.
    """
    key = 'mt'
    name = 'Вихрь Мерсенна MT19937'
    formula = 'xₖ₊ₙ = xₖ₊ₘ ⊕ (xₖᵘ | xₖ₊₁ˡ)·A,  n = 624, m = 397;  выход — «закалка» слова'
    N, M = 624, 397
    MATRIX_A, UPPER, LOWER = 0x9908B0DF, 0x80000000, 0x7FFFFFFF

    def __init__(self, seed: int = 5489, python_compatible: bool = True) -> None:
        if python_compatible:
            self.init_by_array(self._key_of(seed))     # так делает random.seed(целое)
        else:
            self.init_genrand(seed)                     # так в оригинальной программе авторов

    @staticmethod
    def _key_of(seed: int) -> list[int]:
        seed = abs(seed)
        key = []
        while True:
            key.append(seed & 0xFFFFFFFF)
            seed >>= 32
            if not seed:
                return key

    def init_genrand(self, s: int) -> None:
        mt = [0] * self.N
        mt[0] = s & 0xFFFFFFFF
        for i in range(1, self.N):
            mt[i] = (1812433253 * (mt[i - 1] ^ (mt[i - 1] >> 30)) + i) & 0xFFFFFFFF
        self.mt, self.index = mt, self.N

    def init_by_array(self, key: list[int]) -> None:
        self.init_genrand(19650218)
        mt, n = self.mt, self.N
        i, j = 1, 0
        for _ in range(max(n, len(key))):
            mt[i] = ((mt[i] ^ ((mt[i - 1] ^ (mt[i - 1] >> 30)) * 1664525)) + key[j] + j) & 0xFFFFFFFF
            i += 1
            j += 1
            if i >= n:
                mt[0] = mt[n - 1]
                i = 1
            if j >= len(key):
                j = 0
        for _ in range(n - 1):
            mt[i] = ((mt[i] ^ ((mt[i - 1] ^ (mt[i - 1] >> 30)) * 1566083941)) - i) & 0xFFFFFFFF
            i += 1
            if i >= n:
                mt[0] = mt[n - 1]
                i = 1
        mt[0] = 0x80000000

    def twist(self) -> None:
        mt, n, m = self.mt, self.N, self.M
        for k in range(n):
            y = (mt[k] & self.UPPER) | (mt[(k + 1) % n] & self.LOWER)
            mt[k] = mt[(k + m) % n] ^ (y >> 1) ^ (self.MATRIX_A if y & 1 else 0)
        self.index = 0

    @staticmethod
    def temper(y: int) -> int:
        y ^= y >> 11
        y ^= (y << 7) & 0x9D2C5680
        y ^= (y << 15) & 0xEFC60000
        y ^= y >> 18
        return y

    def next(self) -> int:
        if self.index >= self.N:
            self.twist()
        y = self.mt[self.index]
        self.index += 1
        return self.temper(y)


# ==========================================================================
# 6. Блюм–Блюм–Шуб (1986) — криптостойкий датчик
# ==========================================================================

class BBS(Generator):
    """xₙ₊₁ = xₙ² mod M, M = p·q, p ≡ q ≡ 3 (mod 4); выходной бит — младший бит xₙ.

    Предсказать следующий бит так же трудно, как разложить M на множители.
    """
    key = 'bbs'
    name = 'Блюм–Блюм–Шуб (BBS)'

    def __init__(self, p: int = 2147483647, q: int = 4294967291, seed: int = 123456789) -> None:
        if p % 4 != 3 or q % 4 != 3:
            raise ValueError('p и q должны давать остаток 3 при делении на 4')
        self.p, self.q, self.M = p, q, p * q
        s = seed % self.M
        while s % p == 0 or s % q == 0 or s < 2:
            s += 1
        self.state = s * s % self.M
        self.modulus = 2 ** 32
        self.formula = f'xₙ₊₁ = xₙ² mod M, M = {p}·{q}; бит = xₙ mod 2'

    def next_bit(self) -> int:
        self.state = self.state * self.state % self.M
        return self.state & 1

    def next(self) -> int:
        x = 0
        for _ in range(32):
            x = (x << 1) | self.next_bit()
        return x

    def bits(self, n: int) -> list[int]:
        return [self.next_bit() for _ in range(n)]


# ==========================================================================
# Эталоны для сравнения
# ==========================================================================

class PythonRandom(Generator):
    key = 'python'
    name = 'Эталон: random (Python)'
    formula = 'random.getrandbits(32) — встроенный вихрь Мерсенна'

    def __init__(self, seed: int = 5489) -> None:
        self.rnd = random.Random(seed)

    def next(self) -> int:
        return self.rnd.getrandbits(32)


class SystemRandom(Generator):
    key = 'os'
    name = 'Эталон: os.urandom (системный КСГПСЧ)'
    formula = 'os.urandom — криптографический генератор операционной системы (зерно задать нельзя)'

    def next(self) -> int:
        return int.from_bytes(os.urandom(4), 'big')


def make(key: str, seed: int = 1, **params) -> Generator:
    """Создать датчик по ключу: middle, ansi, nr, minstd, randu, toy, lfsr16, lfsr32, xorshift, mt, bbs, python, os."""
    if key == 'middle':
        return MiddleSquare(seed if seed > 99 else 5772, params.get('digits', 4))
    if key in LCG_PRESETS:
        return LCG.preset(key, seed)
    if key == 'lcg':
        return LCG(params['a'], params['c'], params['m'], seed)
    if key.startswith('lfsr'):
        n = int(key[4:] or 32)
        g = LFSR(LFSR_POLYS[n], seed or 1)
        g.key = key
        return g
    if key == 'xorshift':
        return Xorshift32(seed or 1)
    if key == 'mt':
        return MT19937(seed)
    if key == 'bbs':
        return BBS(seed=seed)
    if key == 'python':
        return PythonRandom(seed)
    if key == 'os':
        return SystemRandom()
    raise KeyError(key)


CATALOG = {
    'middle': 'Середина квадрата (фон Нейман)',
    'toy': 'ЛКГ учебный (m = 64)',
    'randu': 'ЛКГ RANDU (IBM)',
    'ansi': 'ЛКГ ANSI C rand()',
    'minstd': 'ЛКГ MINSTD (Парк–Миллер)',
    'nr': 'ЛКГ Numerical Recipes',
    'lfsr16': 'РСЛОС, 16 бит',
    'lfsr32': 'РСЛОС, 32 бита',
    'xorshift': 'Xorshift32',
    'mt': 'Вихрь Мерсенна MT19937',
    'bbs': 'Блюм–Блюм–Шуб (BBS)',
    'python': 'Эталон: random (Python)',
    'os': 'Эталон: os.urandom',
}
