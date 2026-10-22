"""Статистические тесты качества последовательности.

Схема любого теста (проверка гипотезы):
    H₀: последовательность случайна (биты независимы и равновероятны, числа равномерны на [0, 1));
    по выборке считается статистика (S, χ², D…), распределение которой при H₀ известно;
    p-значение = P(статистика не меньше наблюдаемой | H₀);
    если p < α (у нас α = 0,01), H₀ отвергается — тест «не пройден».
Даже идеальный генератор не проходит тест с вероятностью α, поэтому одиночный провал
с p ≈ 0,005 — не приговор, а повод проверить ещё раз; p ≈ 10⁻¹⁰ — явный дефект.

Тесты по битам взяты из NIST SP 800-22 (стандарт для генераторов в криптографии),
тесты по числам — классические, из книги Д. Кнута «Искусство программирования», т. 2.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import comb, erfc, factorial, fabs, log, pi, sqrt

import numpy as np

from .special import chi2_sf, igamc, kolmogorov, normal_cdf

ALPHA = 0.01


@dataclass
class Result:
    key: str
    name: str
    statistic: str               # значение статистики с обозначением, например «χ² = 61,3»
    p_value: float
    details: str = ''

    @property
    def passed(self) -> bool:
        return self.p_value >= ALPHA


# ==========================================================================
# Тесты по битам (NIST SP 800-22)
# ==========================================================================

def frequency(bits: np.ndarray) -> Result:
    """Частотный (монобитный): единиц должно быть около половины.
    S = Σ(2εᵢ − 1), s = |S|/√n ≈ |N(0,1)|, p = erfc(s/√2)."""
    n = len(bits)
    s = int(2 * bits.sum() - n)
    stat = abs(s) / sqrt(n)
    return Result('frequency', 'Частотный (монобитный)', f'S = {s}, |S|/√n = {stat:.3f}', erfc(stat / sqrt(2)),
                  f'единиц {int(bits.sum())} из {n} ({bits.mean() * 100:.3f} %)')


def block_frequency(bits: np.ndarray, m: int = 128) -> Result:
    """Частотный в блоках: в каждом блоке из M бит доля единиц πᵢ ≈ 1/2.
    χ² = 4M·Σ(πᵢ − 1/2)², N = n/M блоков, p = Q(N/2, χ²/2)."""
    n_blocks = len(bits) // m
    pis = bits[:n_blocks * m].reshape(n_blocks, m).mean(axis=1)
    chi2 = 4 * m * float(((pis - 0.5) ** 2).sum())
    return Result('block', f'Частотный в блоках (M = {m})', f'χ² = {chi2:.1f} (N = {n_blocks})',
                  igamc(n_blocks / 2, chi2 / 2))


def runs(bits: np.ndarray) -> Result:
    """Серии: число V участков из одинаковых бит. При случайности V ≈ 2nπ(1 − π).
    p = erfc(|V − 2nπ(1−π)| / (2√(2n)·π(1−π)))."""
    n = len(bits)
    p1 = float(bits.mean())
    if abs(p1 - 0.5) >= 2 / sqrt(n):
        return Result('runs', 'Серии', f'π = {p1:.4f}', 0.0, 'не выполнено предварительное условие |π − 1/2| < 2/√n')
    v = int(np.count_nonzero(bits[1:] != bits[:-1])) + 1
    expected = 2 * n * p1 * (1 - p1)
    p = erfc(abs(v - expected) / (2 * sqrt(2 * n) * p1 * (1 - p1)))
    return Result('runs', 'Серии', f'V = {v} (ожидалось {expected:.0f})', p)


LONGEST = {          # M, K, границы классов, вероятности классов (NIST SP 800-22, табл. 2.4)
    8: (3, [1, 2, 3, 4], [0.2148, 0.3672, 0.2305, 0.1875]),
    128: (5, [4, 5, 6, 7, 8, 9], [0.1174, 0.2430, 0.2493, 0.1752, 0.1027, 0.1124]),
    10000: (6, [10, 11, 12, 13, 14, 15, 16], [0.0882, 0.2092, 0.2483, 0.1933, 0.1208, 0.0675, 0.0727]),
}


def longest_run(bits: np.ndarray) -> Result:
    """Самая длинная серия единиц в блоке: распределение длины самой длинной серии в блоках из M бит."""
    n = len(bits)
    m = 10000 if n >= 750000 else 128 if n >= 6272 else 8
    k, edges, probs = LONGEST[m]
    n_blocks = n // m
    counts = [0] * (k + 1)
    for block in bits[:n_blocks * m].reshape(n_blocks, m):
        padded = np.concatenate(([0], block, [0]))
        d = np.diff(padded)
        starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        longest = int((ends - starts).max()) if len(starts) else 0
        idx = 0 if longest <= edges[0] else k if longest >= edges[-1] else longest - edges[0]
        counts[idx] += 1
    chi2 = sum((c - n_blocks * p) ** 2 / (n_blocks * p) for c, p in zip(counts, probs))
    return Result('longest', f'Самая длинная серия единиц (M = {m})', f'χ² = {chi2:.2f}', igamc(k / 2, chi2 / 2),
                  'классы: ' + ', '.join(map(str, counts)))


def cumulative_sums(bits: np.ndarray) -> Result:
    """Кумулятивные суммы: случайное блуждание Sₖ = Σ(2εᵢ − 1) не должно уходить далеко от нуля.
    z = max|Sₖ|; p — по формуле для максимума блуждания (NIST 2.13)."""
    n = len(bits)
    walk = np.cumsum(2 * bits.astype(np.int64) - 1)
    z = int(np.abs(walk).max())
    total = 0.0
    for k in range(int((-n / z + 1) / 4), int((n / z - 1) / 4) + 1):
        total += normal_cdf((4 * k + 1) * z / sqrt(n)) - normal_cdf((4 * k - 1) * z / sqrt(n))
    total2 = 0.0
    for k in range(int((-n / z - 3) / 4), int((n / z - 1) / 4) + 1):
        total2 += normal_cdf((4 * k + 3) * z / sqrt(n)) - normal_cdf((4 * k + 1) * z / sqrt(n))
    p = 1 - total + total2
    return Result('cusum', 'Кумулятивные суммы', f'max|Sₖ| = {z} (√n = {sqrt(n):.0f})', max(0.0, min(1.0, p)))


def approximate_entropy(bits: np.ndarray, m: int = 2) -> Result:
    """Приближённая энтропия: частоты всех m- и (m+1)-битных шаблонов должны быть близки к равным.
    ApEn = φ(m) − φ(m+1), χ² = 2n(ln 2 − ApEn), p = Q(2^(m−1), χ²/2)."""
    n = len(bits)

    def phi(mm: int) -> float:
        ext = np.concatenate((bits, bits[:mm - 1])) if mm > 1 else bits
        codes = np.zeros(n, dtype=np.int64)
        for j in range(mm):
            codes = codes * 2 + ext[j:j + n]
        c = np.bincount(codes, minlength=2 ** mm) / n
        c = c[c > 0]
        return float((c * np.log(c)).sum())

    apen = phi(m) - phi(m + 1)
    chi2 = 2 * n * (log(2) - apen)
    return Result('apen', f'Приближённая энтропия (m = {m})', f'ApEn = {apen:.6f} (идеал ln 2 = 0.693147)',
                  igamc(2 ** (m - 1), chi2 / 2))


# ==========================================================================
# Тесты по числам (Кнут)
# ==========================================================================

def chi_square_uniform(u: np.ndarray, k: int = 64) -> Result:
    """Критерий χ² Пирсона: числа разбиты на k равных интервалов, в каждом ожидается n/k.
    χ² = Σ(Oᵢ − Eᵢ)²/Eᵢ, степеней свободы k − 1."""
    counts = np.bincount(np.minimum((u * k).astype(int), k - 1), minlength=k)
    e = len(u) / k
    chi2 = float(((counts - e) ** 2).sum() / e)
    return Result('chi2', f'χ² Пирсона: равномерность ({k} интервалов)', f'χ² = {chi2:.1f} (ст. свободы {k - 1})',
                  chi2_sf(chi2, k - 1))


def kolmogorov_smirnov(u: np.ndarray) -> Result:
    """Колмогоров–Смирнов: наибольшее расхождение D эмпирической функции распределения с прямой F(x) = x.
    p = Q((√n + 0,12 + 0,11/√n)·D)."""
    n = len(u)
    s = np.sort(u)
    i = np.arange(1, n + 1)
    d = float(max((i / n - s).max(), (s - (i - 1) / n).max()))
    lam = (sqrt(n) + 0.12 + 0.11 / sqrt(n)) * d
    return Result('ks', 'Колмогоров–Смирнов', f'D = {d:.5f}, √n·D = {sqrt(n) * d:.3f}', kolmogorov(lam))


def serial_pairs(u: np.ndarray, d: int = 16) -> Result:
    """Сериальный тест: неперекрывающиеся пары (u₂ᵢ, u₂ᵢ₊₁) равномерно заполняют квадрат d×d.
    χ² по d² клеткам, степеней свободы d² − 1."""
    x = np.minimum((u * d).astype(int), d - 1)
    pairs = x[: len(x) // 2 * 2].reshape(-1, 2)
    cells = np.bincount(pairs[:, 0] * d + pairs[:, 1], minlength=d * d)
    e = len(pairs) / (d * d)
    chi2 = float(((cells - e) ** 2).sum() / e)
    return Result('serial', f'Сериальный (пары, {d}×{d} клеток)', f'χ² = {chi2:.1f} (ст. свободы {d * d - 1})',
                  chi2_sf(chi2, d * d - 1))


def triples(u: np.ndarray, d: int = 8) -> Result:
    """То же для троек (u₃ᵢ, u₃ᵢ₊₁, u₃ᵢ₊₂) в кубе d×d×d — ловит «плоскости» ЛКГ."""
    x = np.minimum((u * d).astype(int), d - 1)
    t = x[: len(x) // 3 * 3].reshape(-1, 3)
    cells = np.bincount((t[:, 0] * d + t[:, 1]) * d + t[:, 2], minlength=d ** 3)
    e = len(t) / d ** 3
    chi2 = float(((cells - e) ** 2).sum() / e)
    return Result('triples', f'Сериальный (тройки, {d}×{d}×{d})', f'χ² = {chi2:.1f} (ст. свободы {d ** 3 - 1})',
                  chi2_sf(chi2, d ** 3 - 1))


def _stirling2(n: int, k: int) -> int:
    """Число Стирлинга 2-го рода — сколькими способами разбить n элементов на k непустых групп."""
    return sum((-1) ** i * comb(k, i) * (k - i) ** n for i in range(k + 1)) // factorial(k)


def poker(u: np.ndarray, d: int = 10, hand: int = 5) -> Result:
    """Покер-тест (тест разбиений): в «руке» из 5 чисел, переведённых в цифры 0–9, считаем число
    различных цифр r. P(r) = d(d−1)…(d−r+1)·S(5, r) / d⁵. Классы r ≤ 2 объединены."""
    x = np.minimum((u * d).astype(int), d - 1)
    hands = x[: len(x) // hand * hand].reshape(-1, hand)
    distinct = np.array([len(set(h)) for h in hands.tolist()])
    probs = {}
    for r in range(1, hand + 1):
        falling = 1
        for j in range(r):
            falling *= d - j
        probs[r] = falling * _stirling2(hand, r) / d ** hand
    classes = [(1, 2), (3,), (4,), (5,)]
    obs = [int(np.isin(distinct, c).sum()) for c in classes]
    exp_ = [len(hands) * sum(probs[r] for r in c) for c in classes]
    chi2 = sum((o - e) ** 2 / e for o, e in zip(obs, exp_))
    names = ['≤ 2 разных', '3 разных', '4 разных', '5 разных']
    return Result('poker', 'Покер-тест (руки по 5 цифр)', f'χ² = {chi2:.2f} (ст. свободы 3)', chi2_sf(chi2, 3),
                  '; '.join(f'{nm}: {o} (ожид. {e:.0f})' for nm, o, e in zip(names, obs, exp_)))


def autocorrelation(u: np.ndarray, lag: int = 1) -> Result:
    """Автокорреляция: соседние числа не должны быть связаны. r ≈ N(0, 1/n), z = r·√n."""
    a = u - u.mean()
    r = float((a[:-lag] * a[lag:]).sum() / (a * a).sum())
    z = r * sqrt(len(u))
    return Result('autocorr', f'Автокорреляция (сдвиг {lag})', f'r = {r:.5f}, z = {z:.2f}', erfc(abs(z) / sqrt(2)))


def monte_carlo_pi(u: np.ndarray) -> Result:
    """Метод Монте-Карло: доля точек (x, y) внутри четверти круга ≈ π/4.
    Число попаданий ~ Bin(N, π/4) ⇒ z = (k − Nπ/4)/√(N·π/4·(1 − π/4))."""
    pts = u[: len(u) // 2 * 2].reshape(-1, 2)
    n = len(pts)
    inside = int(((pts ** 2).sum(axis=1) < 1).sum())
    q = pi / 4
    z = (inside - n * q) / sqrt(n * q * (1 - q))
    return Result('pi', 'Монте-Карло: оценка числа π', f'π ≈ {4 * inside / n:.5f} (ошибка {4 * inside / n - pi:+.5f})',
                  erfc(fabs(z) / sqrt(2)))


def low_bit(low: np.ndarray) -> Result:
    """Младший бит чисел: последовательность x₁ mod 2, x₂ mod 2, … проверяется тестом серий.
    У ЛКГ с модулем m = 2ᵏ младший бит имеет период 2 (чередуется) или вообще постоянен."""
    r = runs(low)
    ones = float(low.mean())
    return Result('lowbit', 'Младший бит чисел (серии)', r.statistic, r.p_value,
                  f'доля единиц {ones * 100:.1f} %; первые биты: ' + ''.join(map(str, low[:24].tolist())))


BIT_TESTS = [frequency, block_frequency, runs, longest_run, cumulative_sums, approximate_entropy]
NUMBER_TESTS = [chi_square_uniform, kolmogorov_smirnov, serial_pairs, triples, poker, autocorrelation, monte_carlo_pi]


def run_battery(gen, n_numbers: int = 100_000, n_bits: int = 1_000_000) -> list[Result]:
    """Прогнать все тесты: сначала n_numbers чисел, потом n_bits бит (последовательность продолжается)."""
    m, k = gen.modulus, gen.word_bits
    nums = gen.numbers(n_numbers)
    u = np.array(nums, dtype=np.float64) / m
    low = np.array([((x << k) // m) & 1 for x in nums], dtype=np.int8)
    bits = np.array(gen.bits(n_bits), dtype=np.int8)
    return [t(bits) for t in BIT_TESTS] + [t(u) for t in NUMBER_TESTS] + [low_bit(low)]
