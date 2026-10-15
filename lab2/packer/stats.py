"""Формулы теории информации, которые используются в работе.

Обозначения (как в лекциях и в ЛР №1):
    n    — длина сообщения (сколько в нём символов или байтов);
    f_i  — частота: сколько раз встретился i-й символ;
    p_i  — вероятность символа, оценивается как f_i / n;
    N    — число различных символов в сообщении (объём алфавита);
    l_i  — длина кодового слова i-го символа в битах.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import log2


def frequencies(data) -> dict:
    """Частоты символов: {символ: сколько раз встретился}.

    Для bytes символы — числа 0..255 (байты), для str — буквы.
    """
    return dict(Counter(data))


def entropy(freqs: dict) -> float:
    """Энтропия Шеннона H = −Σ p_i·log2(p_i), бит на символ.

    Это среднее количество информации в одном символе. По теореме Шеннона
    это ещё и нижняя граница средней длины кода: lср ≥ H.
    """
    total = sum(freqs.values())
    h = 0.0
    for f in freqs.values():
        if f:
            p = f / total
            h -= p * log2(p)
    return h


def max_entropy(freqs: dict) -> float:
    """Hmax = log2(N) — энтропия, если бы все N символов были равновероятны (мера Хартли)."""
    n = sum(1 for f in freqs.values() if f)
    return log2(n) if n else 0.0


def redundancy(freqs: dict) -> float:
    """Избыточность R = 1 − H / Hmax (0 — избыточности нет, всё «по делу»)."""
    hmax = max_entropy(freqs)
    return 1 - entropy(freqs) / hmax if hmax else 0.0


def conditional_entropy(data) -> float:
    """Условная энтропия H1 = H(X_k | X_k−1), бит на символ.

    Неопределённость очередного символа, когда предыдущий уже известен.
    Считается как H(пар соседних символов) − H(первых символов этих пар).
    Всегда H1 ≤ H0: чем сильнее символы связаны друг с другом, тем меньше H1.
    """
    if len(data) < 2:
        return 0.0
    pairs = Counter(zip(data, data[1:]))
    firsts = Counter(data[:-1])
    return entropy(pairs) - entropy(firsts)


def average_length(freqs: dict, lengths: dict) -> float:
    """Средняя длина кодового слова lср = Σ p_i·l_i, бит на символ."""
    total = sum(freqs.values())
    if total == 0:
        return 0.0
    return sum(f * lengths[s] for s, f in freqs.items() if f) / total


def kraft_sum(lengths: dict) -> float:
    """Сумма Крафта Σ 2^(−l_i). Для любого префиксного кода она не больше 1."""
    return sum(2.0 ** -length for length in lengths.values())


@dataclass
class CodeQuality:
    """Характеристики эффективности неравномерного кода (как в ЛР №1)."""

    entropy: float      # H — энтропия, бит/символ
    max_entropy: float  # Hmax = log2 N, бит/символ
    avg_length: float   # lср — средняя длина кодового слова, бит/символ

    @property
    def k_cc(self) -> float:
        """Коэффициент статистического сжатия Kсс = Hmax / lср."""
        return self.max_entropy / self.avg_length if self.avg_length else 0.0

    @property
    def k_oe(self) -> float:
        """Коэффициент относительной эффективности Kоэ = H / lср (не больше 1)."""
        return self.entropy / self.avg_length if self.avg_length else 0.0


def code_quality(freqs: dict, lengths: dict) -> CodeQuality:
    return CodeQuality(entropy(freqs), max_entropy(freqs), average_length(freqs, lengths))


@dataclass
class DataProfile:
    """Статистический «портрет» файла."""

    size: int             # n — размер в байтах
    distinct: int         # N — сколько различных значений байта встречается
    entropy: float        # H0 — энтропия по частотам отдельных байтов, бит/байт
    max_entropy: float    # Hmax = log2 N
    cond_entropy: float   # H1 — энтропия с учётом предыдущего байта, бит/байт

    @property
    def limit_bytes(self) -> float:
        """Нижняя граница для ПОСИМВОЛЬНЫХ кодов (Хаффман, Шеннон–Фано): n·H0 / 8 байт."""
        return self.size * self.entropy / 8


def profile(data: bytes) -> DataProfile:
    freqs = frequencies(data)
    return DataProfile(len(data), len(freqs), entropy(freqs), max_entropy(freqs),
                       conditional_entropy(data))


def ratio(original_size: int, packed_size: int) -> float:
    """Коэффициент сжатия k = V_исх / V_сж (больше 1 — файл уменьшился)."""
    return original_size / packed_size if packed_size else float('inf')


def percent(original_size: int, packed_size: int) -> float:
    """Размер архива в процентах от исходного (меньше 100 % — сжатие, больше — расширение)."""
    return 100.0 * packed_size / original_size if original_size else float('inf')
