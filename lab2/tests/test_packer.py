"""Автоматические тесты архиватора.

Запуск из папки lab2:   python -m unittest discover -s tests -v
"""
import random
import sys
import unittest
from math import log2
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packer import container, explain, huffman, lzw, prefix_code, rle, shannon_fano, stats  # noqa: E402
from packer.methods import METHODS  # noqa: E402


def samples() -> dict:
    """Трудные случаи для любого архиватора."""
    rnd = random.Random(2026)
    return {
        'пустые данные': b'',
        'один байт': b'A',
        'два одинаковых байта': b'AA',
        'один символ 5000 раз': b'a' * 5000,
        'серии разной длины (в т.ч. > 255)': b''.join(
            bytes([rnd.randrange(4)]) * rnd.randrange(1, 600) for _ in range(200)),
        'все 256 значений байта': bytes(range(256)) * 8,
        'случайные байты': rnd.randbytes(20000),
        'русский текст UTF-8': ('Сжатие данных без потерь — это обратимое кодирование. ' * 40).encode('utf-8'),
        'нулевые байты и 0xFF': b'\x00\xff' * 100 + b'\x00' * 300 + b'\xff' * 300,
        'случай sKsKs для LZW': b'abababababababab' + b'a' * 100,
    }


class RoundTripTests(unittest.TestCase):
    def test_every_method_restores_data_exactly(self):
        for name, data in samples().items():
            for m in METHODS.values():
                with self.subTest(sample=name, method=m.key):
                    self.assertEqual(m.decompress(m.compress(data), len(data)), data)

    def test_archive_roundtrip_keeps_name_and_method(self):
        data = b'hello, archive! ' * 100
        for key in list(METHODS) + ['auto']:
            with self.subTest(method=key):
                info, restored = container.unpack(container.pack(data, key, 'файл.txt'))
                self.assertEqual(restored, data)
                self.assertEqual(info.name, 'файл.txt')

    def test_auto_picks_smallest(self):
        data = b'abc' * 2000
        sizes = {m.key: len(m.compress(data)) for m in METHODS.values()}
        info = container.read_info(container.pack(data, 'auto'))
        self.assertEqual(len(info.payload), min(sizes.values()))

    def test_damaged_archive_is_detected(self):
        archive = bytearray(container.pack(b'hello world ' * 100, 'huffman', 'x.txt'))
        archive[-5] ^= 0xFF
        with self.assertRaises(container.ArchiveError):
            container.unpack(bytes(archive))

    def test_not_an_archive(self):
        with self.assertRaises(container.ArchiveError):
            container.unpack(b'just some text')


class RleTests(unittest.TestCase):
    def test_40_spaces_become_3_bytes_like_in_methodichka(self):
        payload = rle.compress(b' ' * 40)
        flag = payload[0]
        self.assertEqual(payload[1:], bytes([ord(' '), flag, 40]))

    def test_flag_is_the_rarest_byte(self):
        data = bytes(range(256)) * 3 + bytes(range(1, 256))  # байт 0 встречается реже всех
        self.assertEqual(rle.choose_flag(data), 0)

    def test_flag_inside_data_is_escaped(self):
        data = bytes(range(256)) * 2 + b'\x00' * 10 + b'\x00'
        self.assertEqual(rle.decompress(rle.compress(data)), data)

    def test_growth_is_tiny_even_for_random_data(self):
        data = random.Random(1).randbytes(100_000)
        growth = len(rle.compress(data)) - len(data)
        self.assertLessEqual(growth, len(data) // 256 + 1)  # не больше n/256 + байт-флаг


class HuffmanTests(unittest.TestCase):
    METHODICHKA = {'A': 10, 'B': 20, 'C': 30, 'D': 5, 'E': 25, 'F': 10}

    def test_lengths_like_in_methodichka(self):
        lengths = huffman.code_lengths(self.METHODICHKA)
        self.assertEqual(lengths, {'C': 2, 'B': 2, 'E': 2, 'F': 3, 'A': 4, 'D': 4})
        self.assertAlmostEqual(stats.average_length(self.METHODICHKA, lengths), 2.4)

    def test_codes_are_prefix_free_and_kraft_sum_is_one(self):
        codes = prefix_code.canonical_codes(huffman.code_lengths(self.METHODICHKA))
        words = list(codes.values())
        for a in words:
            for b in words:
                if a != b:
                    self.assertFalse(b.startswith(a), f'{a} — начало {b}')
        self.assertEqual(sum(2 ** -len(w) for w in words), 1)

    def test_shannon_bounds_hold(self):
        rnd = random.Random(7)
        for _ in range(50):
            freqs = {i: rnd.randrange(1, 1000) for i in range(rnd.randrange(2, 60))}
            h = stats.entropy(freqs)
            lavg = stats.average_length(freqs, huffman.code_lengths(freqs))
            self.assertLessEqual(h, lavg + 1e-12)
            self.assertLess(lavg, h + 1)


class ShannonFanoTests(unittest.TestCase):
    def test_methodichka_example(self):
        lengths = shannon_fano.code_lengths(HuffmanTests.METHODICHKA)
        self.assertAlmostEqual(stats.average_length(HuffmanTests.METHODICHKA, lengths), 2.4)

    def test_can_be_worse_than_huffman(self):
        freqs = {'a': 35, 'b': 17, 'c': 17, 'd': 16, 'e': 15}
        sf = stats.average_length(freqs, shannon_fano.code_lengths(freqs))
        hf = stats.average_length(freqs, huffman.code_lengths(freqs))
        self.assertAlmostEqual(sf, 2.31)
        self.assertAlmostEqual(hf, 2.30)

    def test_never_better_than_huffman(self):
        rnd = random.Random(3)
        for _ in range(100):
            freqs = {i: rnd.randrange(1, 100) for i in range(rnd.randrange(2, 30))}
            sf = stats.average_length(freqs, shannon_fano.code_lengths(freqs))
            hf = stats.average_length(freqs, huffman.code_lengths(freqs))
            self.assertGreaterEqual(sf + 1e-12, hf)


class LzwTests(unittest.TestCase):
    def test_methodichka_example(self):
        demo = explain.lzw_demo('абабвбабабааааааа')
        self.assertEqual(demo.codes, [1, 2, 4, 3, 5, 8, 1, 10, 11, 1])
        added = [s.sk for s in demo.steps if s.added]
        self.assertEqual(added, ['1б', '2а', '4в', '3б', '5б', '8а', '1а', '10а', '11а'])
        self.assertEqual(demo.decoded, demo.text)

    def test_special_case_in_decoder(self):
        demo = explain.lzw_demo('аааааа')
        self.assertTrue(any(step.special for step in demo.decode_steps))
        self.assertEqual(demo.decoded, 'аааааа')

    def test_code_width(self):
        self.assertEqual(lzw.code_width(256), 9)
        self.assertEqual(lzw.code_width(511), 9)
        self.assertEqual(lzw.code_width(512), 10)
        self.assertEqual(lzw.code_width(65535), 16)
        self.assertEqual(lzw.code_width(65536), 16)

    def test_dictionary_overflow_and_reset(self):
        data = random.Random(5).randbytes(300_000)  # заведомо больше 65 536 цепочек
        payload = lzw.compress(data)
        self.assertEqual(lzw.decompress(payload), data)


class StatsTests(unittest.TestCase):
    def test_entropy_of_equiprobable_symbols_is_log2_n(self):
        self.assertAlmostEqual(stats.entropy({i: 5 for i in range(8)}), 3.0)
        self.assertAlmostEqual(stats.max_entropy({i: 1 for i in range(256)}), 8.0)

    def test_entropy_of_single_symbol_is_zero(self):
        self.assertEqual(stats.entropy({'a': 100}), 0.0)

    def test_methodichka_entropy(self):
        h = stats.entropy(HuffmanTests.METHODICHKA)
        expected = -sum(p * log2(p) for p in (0.1, 0.2, 0.3, 0.05, 0.25, 0.1))
        self.assertAlmostEqual(h, expected)

    def test_context_reduces_entropy(self):
        text = 'абабабабабвбвбвбвбвбвб' * 20
        self.assertLess(stats.conditional_entropy(text), stats.entropy(stats.frequencies(text)))


class DemoTests(unittest.TestCase):
    def test_demos_work_on_presets(self):
        for text in ('абракадабра', 'a', 'AAAAAAAAAABBBCCCCCCCCDDDDDDDDDDDDE', 'x y\nz'):
            for method in ('huffman', 'shannon'):
                demo = explain.prefix_demo(text, method)
                self.assertEqual(len(demo.encoded),
                                 sum(len(r.code) * r.freq for r in demo.rows))
            self.assertEqual(explain.lzw_demo(text).decoded, text)
            self.assertGreater(explain.rle_demo(text).packed_size, 0)

    def test_rle_demo_tokens_cover_message(self):
        demo = explain.rle_demo('AAAAAAAAAABBBCCCCCCCC')
        self.assertEqual(sum(t.count for t in demo.tokens), demo.original_size)
        self.assertEqual(sum(t.size for t in demo.tokens) + 1, demo.packed_size)


if __name__ == '__main__':
    unittest.main()
