"""Специальные функции для вычисления p-значений статистических тестов.

p-значение — вероятность получить отклонение не меньше наблюдаемого, если последовательность
на самом деле случайна. Маленькое p (у нас меньше α = 0,01) — повод отвергнуть случайность.

    erfc(x)       — дополнительная функция ошибок: P(|Z| ≥ x·√2) для стандартной нормальной Z;
    igamc(a, x)   — регуляризованная верхняя неполная гамма-функция Q(a, x) = Γ(a, x) / Γ(a);
                    p-значение критерия χ² с k степенями свободы: p = Q(k/2, χ²/2);
    kolmogorov(λ) — P(√n·D > λ) для статистики Колмогорова–Смирнова.
"""
from __future__ import annotations

from math import erfc, exp, lgamma, log, sqrt

__all__ = ['erfc', 'igam', 'igamc', 'chi2_sf', 'normal_cdf', 'kolmogorov']

_EPS = 1e-15


def igam(a: float, x: float) -> float:
    """Нижняя регуляризованная P(a, x) — ряд P = e⁻ˣ·xᵃ/Γ(a+1)·Σ xⁿ/((a+1)…(a+n)) (сходится при x < a + 1)."""
    if x <= 0:
        return 0.0
    if x >= a + 1:
        return 1.0 - igamc(a, x)
    term = total = 1.0 / a
    k = a
    for _ in range(10000):
        k += 1
        term *= x / k
        total += term
        if abs(term) < abs(total) * _EPS:
            break
    return total * exp(-x + a * log(x) - lgamma(a))


def igamc(a: float, x: float) -> float:
    """Верхняя регуляризованная Q(a, x) = 1 − P(a, x) — цепная дробь Лежандра (при x ≥ a + 1)."""
    if x <= 0:
        return 1.0
    if x < a + 1:
        return 1.0 - igam(a, x)
    # цепная дробь по методу Ленца
    b = x + 1 - a
    c = 1 / 1e-300
    d = 1 / b
    h = d
    for i in range(1, 10000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < _EPS:
            break
    return exp(-x + a * log(x) - lgamma(a)) * h


def chi2_sf(chi2: float, df: int) -> float:
    """p-значение критерия χ²: вероятность получить χ² не меньше наблюдаемого при df степенях свободы."""
    return igamc(df / 2, chi2 / 2)


def normal_cdf(z: float) -> float:
    """Φ(z) — функция распределения стандартного нормального закона."""
    return 0.5 * erfc(-z / sqrt(2))


def kolmogorov(lam: float) -> float:
    """Q(λ) = 2·Σ (−1)^(j−1)·e^(−2j²λ²) — предельное распределение √n·D (теорема Колмогорова)."""
    if lam < 0.2:
        return 1.0
    total = 0.0
    for j in range(1, 101):
        term = 2 * (-1) ** (j - 1) * exp(-2 * j * j * lam * lam)
        total += term
        if abs(term) < 1e-12:
            break
    return max(0.0, min(1.0, total))
