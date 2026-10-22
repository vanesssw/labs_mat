"""Автоматические тесты ЛР №4.

Запуск из папки lab4:   python -m unittest discover -s tests -v
"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codes import code128, damage, ean13, gf256, imaging  # noqa: E402
from codes import qr_tables as T  # noqa: E402
from codes import reed_solomon as rs  # noqa: E402
from codes.qr_decode import QRDecodeError, decode_matrix  # noqa: E402
from codes.qr_encode import data_order, format_bits, make_qr, version_bits  # noqa: E402


class GaloisFieldTests(unittest.TestCase):
    def test_table_multiplication_matches_long_multiplication(self):
        for a in range(256):
            for b in range(0, 256, 7):
                self.assertEqual(gf256.mul(a, b), gf256.mul_slow(a, b))

    def test_alpha_is_primitive_and_inverse(self):
        self.assertEqual(len(set(gf256.EXP[:255])), 255)          # α⁰…α²⁵⁴ — все ненулевые элементы
        for a in range(1, 256):
            self.assertEqual(gf256.mul(a, gf256.inv(a)), 1)


class ReedSolomonTests(unittest.TestCase):
    def test_textbook_example_hello_world(self):
        """Известный пример «HELLO WORLD» версии 1-M: байты коррекции из описаний стандарта."""
        data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
        self.assertEqual(rs.remainder(data, 10), [196, 35, 39, 119, 235, 215, 231, 226, 93, 23])

    def test_corrects_up_to_half_of_ecc(self):
        rnd = random.Random(1)
        for _ in range(500):
            n = rnd.choice([7, 10, 13, 18, 26, 30])
            data = [rnd.randrange(256) for _ in range(rnd.randint(1, 60))]
            word = rs.encode(data, n)
            bad = word[:]
            pos = rnd.sample(range(len(word)), rnd.randint(0, n // 2))
            for p in pos:
                bad[p] ^= rnd.randrange(1, 256)
            fix = rs.decode(bad, n)
            self.assertEqual(fix.word, word)
            self.assertEqual(sorted(fix.positions), sorted(pos))

    def test_too_many_errors_are_detected(self):
        rnd = random.Random(2)
        data = [rnd.randrange(256) for _ in range(20)]
        word = rs.encode(data, 10)
        for _ in range(200):
            bad = word[:]
            for p in rnd.sample(range(len(word)), 7):
                bad[p] ^= rnd.randrange(1, 256)
            with self.assertRaises(rs.RSError):
                rs.decode(bad, 10)


class QRTests(unittest.TestCase):
    def test_tables_are_consistent(self):
        for v in range(1, 41):
            for lv in T.LEVELS:
                layout = T.block_layout(v, lv)
                self.assertEqual(sum(d + e for d, e in layout), T.total_codewords(v))
                self.assertEqual(sum(d for d, _ in layout), T.data_codewords(v, lv))
            _, kind = __import__('codes.qr_encode', fromlist=['function_patterns']).function_patterns(v)
            self.assertEqual(sum(row.count(None) for row in kind), T.raw_data_modules(v))

    def test_hello_world_codewords(self):
        q = make_qr('HELLO WORLD', 'Q')
        self.assertEqual((q.version, q.mode), (1, 'alphanumeric'))
        self.assertEqual(q.data, [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236])
        self.assertEqual(q.blocks[0][1], [168, 72, 22, 82, 217, 54, 156, 0, 46, 15, 180, 122, 16])

    def test_format_and_version_bits(self):
        self.assertEqual(format_bits('M', 0), 0b101010000010010)   # уровень M, маска 0 — известное значение
        self.assertEqual(version_bits(7), 0b000111110010010100)   # версия 7 — известное значение

    def test_roundtrip_all_modes_levels(self):
        texts = ['0123456789', 'HELLO WORLD $%*+-./:', 'Привет, мир! QR-код', 'x' * 500]
        for text in texts:
            for lv in T.LEVELS:
                q = make_qr(text, lv)
                d = decode_matrix(q.modules)
                self.assertEqual((d.text, d.level, d.mask, d.version), (text, lv, q.mask, q.version))

    def test_all_masks_decode(self):
        for mask in range(8):
            q = make_qr('Маска ' + str(mask), 'M', mask=mask)
            self.assertEqual(decode_matrix(q.modules).mask, mask)

    def test_byte_errors_within_capacity_are_corrected(self):
        """Портим по ⌊n/2⌋ байтов в каждом блоке — код восстанавливается; на 1 больше — уже нет."""
        rnd = random.Random(3)
        q = make_qr('Проверка исправления ошибок в каждом блоке', 'H', version=8)
        order = data_order(q.kind)
        layout = T.block_layout(q.version, q.level)
        # номер байта чередованной последовательности → (блок, позиция) — строим заранее
        owner = []
        for i in range(max(d for d, _ in layout)):
            owner += [b for b, (d, _) in enumerate(layout) if i < d]
        for _ in range(layout[0][1]):
            owner += list(range(len(layout)))

        def damaged(extra: int):
            m = [row[:] for row in q.modules]
            for b, (_, e) in enumerate(layout):
                idx = [i for i, o in enumerate(owner) if o == b]
                for cw in rnd.sample(idx, e // 2 + extra):
                    r, c = order[cw * 8]
                    m[r][c] ^= 1
            return m
        self.assertEqual(decode_matrix(damaged(0)).text, q.text)
        with self.assertRaises(QRDecodeError):
            decode_matrix(damaged(1))

    def test_format_info_survives_three_bit_errors(self):
        q = make_qr('format', 'Q')
        m = [row[:] for row in q.modules]
        for r, c in [(0, 8), (1, 8), (2, 8)]:          # 3 бита первой копии
            m[r][c] ^= 1
        self.assertEqual(decode_matrix(m).text, 'format')


class BarcodeTests(unittest.TestCase):
    def test_ean13_check_digit(self):
        self.assertEqual(ean13.normalize('400638133393'), '4006381333931')
        with self.assertRaises(ean13.BarcodeError):
            ean13.normalize('4006381333932')

    def test_ean13_structure(self):
        mods, _ = ean13.encode('460123456789')
        self.assertEqual(len(mods), 95)
        self.assertTrue(mods.startswith('101') and mods.endswith('101') and mods[45:50] == '01010')

    def test_code128_patterns_and_checksum(self):
        self.assertEqual(len(code128.PATTERNS), 107)
        self.assertTrue(all(sum(map(int, p)) == (13 if len(p) == 7 else 11) for p in code128.PATTERNS))
        values = [v for v, _ in code128.symbols('PJJ123C')]
        self.assertEqual(values[0], code128.START_B)

    def test_code128_uses_set_c_for_digits(self):
        syms = code128.symbols('12345678')
        self.assertEqual([v for v, _ in syms], [code128.START_C, 12, 34, 56, 78])


class ScannerTests(unittest.TestCase):
    TEXT = 'Сканер ЛР4: проверка'

    def test_clean_image(self):
        q = make_qr(self.TEXT, 'M')
        self.assertEqual(imaging.scan_qr(imaging.render_qr(q.modules, scale=6)).decoded.text, self.TEXT)

    def test_colors_inversion_rotation(self):
        q = make_qr(self.TEXT, 'Q')
        img = imaging.render_qr(q.modules, scale=6)
        for name, st in [('recolor', 1.0), ('invert', 1.0), ('contrast', 0.8), ('rotate', 0.3), ('noise', 0.1)]:
            with self.subTest(damage=name):
                self.assertEqual(imaging.scan_qr(damage.apply(img, name, st)).decoded.text, self.TEXT)

    def test_level_h_survives_bigger_blot_than_level_l(self):
        res = {}
        for lv in 'LH':
            q = make_qr(self.TEXT, lv, version=5)
            img = imaging.render_qr(q.modules, scale=6)
            res[lv] = imaging.scan_qr(damage.blot(img, 0.15)).decoded is not None
        self.assertEqual(res, {'L': False, 'H': True})

    def test_barcodes_read_back(self):
        mods, _ = ean13.encode('460123456789')
        img = imaging.render_barcode(mods, '4601234567893', guards=imaging.ean13_guards())
        self.assertEqual(imaging.scan_barcode(img).text, '4601234567893')
        mods, _ = code128.encode('LAB4 2026-10-19')
        img = imaging.render_barcode(mods, 'LAB4 2026-10-19', quiet=code128.QUIET)
        self.assertEqual(imaging.scan_barcode(img).text, 'LAB4 2026-10-19')
        self.assertEqual(imaging.scan_barcode(damage.blur(img, 0.02)).text, 'LAB4 2026-10-19')


if __name__ == '__main__':
    unittest.main()
