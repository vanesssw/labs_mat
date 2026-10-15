"""Автоматические тесты ЛР №3.

Запуск из папки lab3:   python -m unittest discover -s tests -v
"""
import random
import sys
import unittest
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coding import channel, explain, gf2  # noqa: E402
from coding import polynomials as poly  # noqa: E402
from coding import variants as V  # noqa: E402
from coding.cyclic_code import CyclicCode  # noqa: E402
from coding.design import design_code, hamming_sum, search_check_part  # noqa: E402
from coding.gf2 import bits, to_str  # noqa: E402
from coding.group_code import GroupCode  # noqa: E402


class Gf2Tests(unittest.TestCase):
    def test_mod2_rules(self):
        self.assertEqual(gf2.xor([0, 0, 1, 1], [0, 1, 0, 1]), [0, 1, 1, 0])
        self.assertEqual(gf2.weight(bits('101101')), 4)
        self.assertEqual(gf2.distance(bits('1011'), bits('0110')), 3)

    def test_inverse(self):
        for m in (gf2.identity(5), gf2.anti_identity(5), [[1, 1, 0], [0, 1, 1], [0, 0, 1]]):
            self.assertEqual(gf2.mat_mul(m, gf2.inverse(m)), gf2.identity(len(m)))
        with self.assertRaises(ValueError):
            gf2.inverse([[1, 1], [1, 1]])


class GroupCodeTests(unittest.TestCase):
    def test_all_variants_satisfy_g_ht_zero(self):
        """Каждая строка G удовлетворяет всем контрольным соотношениям: G·Hᵀ = 0."""
        for number in V.CHECK_PARTS:
            for group in (1, 2):
                code = GroupCode.from_variant(V.check_part(number), group)
                for row in code.G:
                    self.assertEqual(code.syndrome(row), [0] * code.r, (number, group))
                self.assertEqual(code.min_distance, 3, (number, group))   # все варианты исправляют 1 ошибку

    def test_my_variant_by_hand(self):
        """Вариант 1: результаты совпадают с ручным расчётом."""
        code = GroupCode.from_variant(V.check_part(1), 1)
        self.assertEqual([code.relation_text(j) for j in range(1, 5)],
                         ['b1 = a3 ⊕ a4 ⊕ a5', 'b2 = a2 ⊕ a5', 'b3 = a1 ⊕ a4', 'b4 = a1 ⊕ a2 ⊕ a3'])
        self.assertEqual(to_str(code.encode(bits('10101'))), '101010110')
        self.assertEqual(code.min_distance, 3)
        d1 = code.decode(bits('010101100'))
        self.assertEqual((to_str(d1.syndrome), d1.status, d1.positions), ('0011', 'corrected', (1,)))
        self.assertEqual(code.errors_with_syndrome(d1.syndrome, 2), [(3, 4), (8, 9)])
        d2 = code.decode(bits('100101110'))
        self.assertEqual((to_str(d2.syndrome), d2.status), ('0111', 'detected'))
        self.assertEqual(code.errors_with_syndrome(d2.syndrome, 2), [(1, 7), (2, 8)])

    def test_every_single_error_is_corrected(self):
        for group in (1, 2):
            code = GroupCode.from_variant(V.check_part(1), group)
            for info, word in code.codewords():
                for p in range(1, code.n + 1):
                    bad = gf2.xor(word, gf2.error_vector(code.n, [p]))
                    dec = code.decode(bad)
                    self.assertEqual(dec.corrected, word)
                    self.assertEqual(dec.info, info)

    def test_single_error_syndrome_is_column_of_h(self):
        code = GroupCode.from_variant(V.check_part(5), 1)
        c = code.encode(bits('11010'))
        for p in range(1, code.n + 1):
            self.assertEqual(code.syndrome(gf2.xor(c, gf2.error_vector(code.n, [p]))), code.column(p))

    def test_min_distance_equals_min_pairwise_distance(self):
        """Свойство группового кода: d0 = Wmin."""
        code = GroupCode.from_variant(V.check_part(9), 1)
        words = [c for _, c in code.codewords()]
        pairwise = min(gf2.distance(a, b) for a, b in combinations(words, 2))
        self.assertEqual(pairwise, code.min_distance)


class PolynomialTests(unittest.TestCase):
    def test_division_identity(self):
        rnd = random.Random(3)
        for _ in range(200):
            a = [rnd.randint(0, 1) for _ in range(rnd.randint(1, 20))]
            g = [1] + [rnd.randint(0, 1) for _ in range(rnd.randint(0, 6))]
            q, r = poly.divide(a, g)
            self.assertEqual(poly.trim(poly.add(poly.mul(q, g), r)), poly.trim(a))
            self.assertLess(poly.degree(r), poly.degree(g))

    def test_irreducible_and_period(self):
        self.assertTrue(poly.is_irreducible(bits('111')))           # x² + x + 1
        self.assertTrue(poly.is_irreducible(bits('100101')))        # x⁵ + x² + 1
        self.assertFalse(poly.is_irreducible(bits('100011')))       # x⁵ + x + 1 = (x² + x + 1)(x³ + x² + 1)
        self.assertEqual(poly.factorize(bits('100011')), [bits('111'), bits('1101')])
        self.assertEqual(poly.period(bits('1011')), 7)              # x³ + x + 1 → циклический код Хэмминга (7,4)
        self.assertEqual(poly.period(bits('100101')), 31)
        self.assertEqual(poly.poly_str(bits('100101')), 'x⁵ + x² + 1')

    def test_long_division_ends_with_remainder(self):
        lines = poly.long_division(bits('01001101100101'), bits('100101'))
        self.assertEqual(lines[-1][0].strip(), '10011')


class CyclicCodeTests(unittest.TestCase):
    def setUp(self):
        g, info, word = V.CYCLIC_TASKS[1]
        self.code = CyclicCode(bits(g), 14)
        self.info, self.word = bits(info), bits(word)

    def test_my_variant_by_hand(self):
        c = self.code
        self.assertEqual((c.k, c.r, c.period, c.is_cyclic, c.min_distance), (9, 5, 31, False, 3))
        self.assertEqual(to_str(c.encode(self.info)), '10110100100010')
        R = c.syndrome(self.word)
        self.assertEqual(to_str(R), '10011')
        self.assertNotIn(R, [x for _, x in c.single_error_table()])
        self.assertEqual(c.errors_with_syndrome(R, 2), [(3, 7), (4, 13)])
        self.assertIsNone(c.trap(self.word).result)

    def test_generator_matrices_give_same_code(self):
        c = self.code
        words = {to_str(w) for _, w in c.codewords()}
        for row in c.generator_matrix() + c.generator_matrix_by_multiplication():
            self.assertIn(to_str(row), words)
            self.assertFalse(any(c.syndrome(row)))
        for info, w in c.codewords()[:64]:
            self.assertEqual(gf2.vec_mat(info, c.generator_matrix()), w)

    def test_trapping_corrects_every_single_error(self):
        """Алгоритм методички (сдвиги) исправляет любую одиночную ошибку: укороченный и настоящий циклический код."""
        for code in (self.code, CyclicCode(bits('1011'), 7), CyclicCode(bits('10011'), 15)):
            rnd = random.Random(7)
            for _ in range(20):
                info = [rnd.randint(0, 1) for _ in range(code.k)]
                c = code.encode(info)
                for p in range(1, code.n + 1):
                    bad = gf2.xor(c, gf2.error_vector(code.n, [p]))
                    self.assertEqual(code.trap(bad).result, c)
                    self.assertEqual(code.decode(bad).corrected, c)

    def test_all_table_variants_solve(self):
        for t, (g, info, word) in V.CYCLIC_TASKS.items():
            code = CyclicCode(bits(g), len(word))
            doc = explain.task3(code, bits(info), bits(word))
            self.assertIn('Остаток R', doc.plain(), t)


class DesignTests(unittest.TestCase):
    def test_18_combinations_double_errors(self):
        res = design_code(18, 2)
        code = res.code
        self.assertEqual((res.k, res.d, code.n, code.r, code.min_distance), (5, 5, 13, 8, 5))
        self.assertEqual([b.search for b in res.rows if b.search], ['none', 'found'])
        table = code.identifier_table(2)
        synd = [to_str(s) for _, s in table]
        self.assertEqual(len(table), 13 + 78)
        self.assertEqual(len(set(synd)), len(synd))                # все опознаватели различны
        self.assertNotIn('0' * 8, synd)
        self.assertGreaterEqual(2 ** 7, hamming_sum(12, 2))         # n = 12 проходит границу Хэмминга…
        self.assertIsNone(search_check_part(5, 7, 5))              # …но такого кода нет

    def test_every_double_error_is_corrected(self):
        code = design_code(18, 2).code
        for info, c in code.codewords():
            for pos in combinations(range(1, code.n + 1), 2):
                self.assertEqual(code.decode(gf2.xor(c, gf2.error_vector(code.n, pos))).corrected, c)

    def test_other_multiplicities(self):
        self.assertEqual(design_code(18, 1).code.n, 9)
        self.assertEqual(design_code(18, 3).code.min_distance, 7)


class ChannelTests(unittest.TestCase):
    def test_text_bits_roundtrip(self):
        text = 'Код (9,5) — проверка'
        self.assertEqual(channel.bits_to_text(channel.text_to_bits(text)), text)

    def test_noiseless_channel(self):
        code = GroupCode.from_variant(V.check_part(1), 1)
        res = channel.transmit('Привет, мир!', code, 0.0)
        self.assertEqual((res.text, res.channel_errors, res.residual_errors), ('Привет, мир!', 0, 0))

    def test_coding_reduces_errors(self):
        text = 'Помехоустойчивое кодирование. ' * 20
        plain = channel.transmit(text, None, 0.01, seed=5)
        coded = channel.transmit(text, design_code(18, 2).code, 0.01, seed=5)
        self.assertLess(coded.residual_errors, plain.residual_errors)

    def test_failure_probability(self):
        self.assertEqual(channel.block_failure_probability(9, 1, 0.0), 0)
        self.assertAlmostEqual(channel.block_failure_probability(9, 1, 0.02), 0.013113, places=5)


class ExplainTests(unittest.TestCase):
    def test_every_variant_has_a_solution(self):
        for number in V.CHECK_PARTS:
            for group in (1, 2):
                code = GroupCode.from_variant(V.check_part(number), group)
                info, w1, w2 = V.GROUP_TASKS[V.table_variant(number)]
                text = explain.task1(code, bits(info), [bits(w1), bits(w2)]).plain()
                self.assertEqual(text.count('Синдром S ='), 2, (number, group))

    def test_my_variant_text(self):
        text = '\n'.join(d.plain() for d in explain.variant_docs(1, 1))
        for fragment in ('Избыточный код: 10101 0110', 'Синдром S = 0011', 'Синдром S = 0111',
                         'Выбираем код (13,5)', 'F(x) = G(x)·x^5 + R(x) = 101101001 00010', 'Остаток R = 10011'):
            self.assertIn(fragment, text)


if __name__ == '__main__':
    unittest.main()
