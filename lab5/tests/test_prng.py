"""Автоматические тесты ЛР №5.

Запуск из папки lab5:   python -m unittest discover -s tests -v
"""
import random
import sys
import unittest
from math import erfc, exp, sqrt
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prng import generators as G  # noqa: E402
from prng import properties as P  # noqa: E402
from prng import special  # noqa: E402
from prng import stat_tests as st  # noqa: E402

# Пример из стандарта NIST SP 800-22 (разделы 2.1.8–2.13.8): 100 бит и известные p-значения
NIST_EPS = np.array([int(c) for c in
                     '1100100100001111110110101010001000100001011010001100001000110100110001001100011001100010100010111000'],
                    dtype=np.int8)


class GeneratorTests(unittest.TestCase):
    def test_mersenne_twister_matches_python_random(self):
        """Наш MT19937 выдаёт ровно те же числа, что модуль random языка Python."""
        for seed in (0, 1, 42, 12345, 2 ** 40 + 7):
            ours, ref = G.MT19937(seed), random.Random(seed)
            self.assertEqual([ours.next() for _ in range(1500)], [ref.getrandbits(32) for _ in range(1500)])

    def test_mersenne_twister_reference_value(self):
        """Первое число оригинальной программы авторов при seed = 5489."""
        self.assertEqual(G.MT19937(5489, python_compatible=False).next(), 3499211612)

    def test_lcg_formula(self):
        g = G.LCG(13, 7, 64, 1)
        self.assertEqual(g.numbers(4), [20, 11, 22, 37])

    def test_lfsr_period_is_maximal(self):
        for n in (5, 16):
            g = G.LFSR(G.LFSR_POLYS[n], 1)
            start, k = g.state, 0
            while True:
                g.next_bit()
                k += 1
                if g.state == start:
                    break
            self.assertEqual(k, 2 ** n - 1)

    def test_xorshift_never_zero_and_bbs_requires_blum_primes(self):
        g = G.Xorshift32(1)
        self.assertTrue(all(g.next() for _ in range(10000)))
        with self.assertRaises(ValueError):
            G.BBS(p=13, q=7)                       # 13 ≡ 1 (mod 4)

    def test_middle_square_degenerates(self):
        per = P.period_brent(lambda v: G.MiddleSquare(5772).step(v)[1], 5772)
        self.assertEqual((per.length, per.tail), (1, 7))     # 5772 → … → 0 → 0


class SpecialFunctionTests(unittest.TestCase):
    def test_incomplete_gamma(self):
        for x in (0.1, 1.0, 2.5, 10.0):
            self.assertAlmostEqual(special.igamc(1, x), exp(-x), places=12)        # Q(1, x) = e⁻ˣ
            self.assertAlmostEqual(special.igamc(0.5, x), erfc(sqrt(x)), places=12)  # Q(1/2, x) = erfc(√x)

    def test_chi_square_critical_values(self):
        self.assertAlmostEqual(special.chi2_sf(3.841, 1), 0.05, places=3)
        self.assertAlmostEqual(special.chi2_sf(18.307, 10), 0.05, places=3)
        self.assertAlmostEqual(special.chi2_sf(6.635, 1), 0.01, places=3)

    def test_kolmogorov(self):
        self.assertAlmostEqual(special.kolmogorov(1.358), 0.05, places=3)


class NistExampleTests(unittest.TestCase):
    """p-значения совпадают с контрольными примерами стандарта NIST SP 800-22."""

    def test_frequency(self):
        self.assertAlmostEqual(st.frequency(NIST_EPS).p_value, 0.109599, places=6)

    def test_block_frequency(self):
        self.assertAlmostEqual(st.block_frequency(NIST_EPS, 10).p_value, 0.706438, places=6)

    def test_runs(self):
        self.assertAlmostEqual(st.runs(NIST_EPS).p_value, 0.500798, places=6)

    def test_cumulative_sums(self):
        self.assertAlmostEqual(st.cumulative_sums(NIST_EPS).p_value, 0.219194, places=6)

    def test_approximate_entropy(self):
        self.assertAlmostEqual(st.approximate_entropy(NIST_EPS, 2).p_value, 0.235301, places=6)

    def test_longest_run(self):
        eps = np.array([int(c) for c in '1100110000010101011011000100110011100000000000100100110101010001000100111101011'
                                       '0100000001101011111001100111001101101100010110010'], dtype=np.int8)
        self.assertAlmostEqual(st.longest_run(eps).p_value, 0.1806, places=3)


class QualityTests(unittest.TestCase):
    def test_good_generators_pass(self):
        for key in ('mt', 'xorshift', 'minstd', 'python'):
            res = st.run_battery(G.make(key, 777), 20_000, 200_000)
            self.assertGreaterEqual(sum(r.passed for r in res), len(res) - 1, key)

    def test_bad_generators_fail(self):
        middle = st.run_battery(G.make('middle', 5772), 5_000, 50_000)
        self.assertEqual(sum(r.passed for r in middle), 0)
        randu = {r.key: r.passed for r in st.run_battery(G.make('randu', 1), 20_000, 200_000)}
        self.assertFalse(randu['lowbit'])                     # у RANDU младший бит всегда 1
        ansi = {r.key: r.passed for r in st.run_battery(G.make('ansi', 1), 20_000, 200_000)}
        self.assertFalse(ansi['lowbit'])                      # чередуется 0101…

    def test_randu_planes(self):
        u = np.array(G.make('randu', 1).uniforms(20000))
        values = np.unique(np.round(P.randu_planes(u)))
        self.assertLessEqual(len(values), 15)

    def test_linear_complexity(self):
        self.assertEqual(P.linear_complexity(G.make('lfsr16', 7).bits(300)), 16)
        lc = P.linear_complexity(G.make('mt', 7).bits(300))
        self.assertTrue(140 <= lc <= 160)

    def test_hull_dobell(self):
        self.assertTrue(all(ok for _, ok in P.hull_dobell(1103515245, 12345, 2 ** 31)))
        self.assertFalse(all(ok for _, ok in P.hull_dobell(65539, 0, 2 ** 31)))
        self.assertEqual(P.period_brent(lambda x: (13 * x + 7) % 64, 1).length, 64)


if __name__ == '__main__':
    unittest.main()
