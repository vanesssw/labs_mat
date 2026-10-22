"""Таблицы стандарта QR-кода (ISO/IEC 18004) для версий 1–40 и уровней коррекции L, M, Q, H."""
from __future__ import annotations

LEVELS = ('L', 'M', 'Q', 'H')
LEVEL_PERCENT = {'L': 7, 'M': 15, 'Q': 25, 'H': 30}     # примерно сколько процентов байтов можно восстановить
FORMAT_BITS = {'L': 0b01, 'M': 0b00, 'Q': 0b11, 'H': 0b10}  # 2 бита уровня в служебной информации

# Байтов коррекции в одном блоке (индекс — версия; 0 не используется)
ECC_PER_BLOCK = {
    'L': (0, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28,
          30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    'M': (0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28,
          28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28),
    'Q': (0, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28,
          30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    'H': (0, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30,
          30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
}

# Число блоков, на которые делятся данные (индекс — версия)
NUM_BLOCKS = {
    'L': (0, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17,
          18, 19, 19, 20, 21, 22, 24, 25),
    'M': (0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29,
          31, 33, 35, 37, 38, 40, 43, 45, 47, 49),
    'Q': (0, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38,
          40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68),
    'H': (0, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45,
          48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81),
}

# Режимы кодирования: 4-битный индикатор и длина поля «число символов» для версий 1–9, 10–26, 27–40
MODES = {
    'numeric': (0b0001, (10, 12, 14)),
    'alphanumeric': (0b0010, (9, 11, 13)),
    'byte': (0b0100, (8, 16, 16)),
}
MODE_NAMES = {'numeric': 'цифровой', 'alphanumeric': 'буквенно-цифровой', 'byte': 'байтовый'}
ALPHANUMERIC = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:'   # 45 символов, код = позиция

PAD_BYTES = (0xEC, 0x11)          # заполнители 11101100 и 00010001

FORMAT_GENERATOR = 0x537          # x¹⁰ + x⁸ + x⁵ + x⁴ + x² + x + 1 — БЧХ-код (15,5) служебной информации
FORMAT_MASK = 0x5412              # XOR-маска служебной информации (чтобы она не была нулевой)
VERSION_GENERATOR = 0x1F25        # x¹² + x¹¹ + x¹⁰ + x⁹ + x⁸ + x⁵ + x² + 1 — код Голея (18,6) номера версии


def size_of(version: int) -> int:
    """Сторона матрицы в модулях: 21 для версии 1, +4 на каждую следующую."""
    return 17 + 4 * version


def char_count_bits(mode: str, version: int) -> int:
    lens = MODES[mode][1]
    return lens[0] if version <= 9 else lens[1] if version <= 26 else lens[2]


def alignment_positions(version: int) -> list[int]:
    """Координаты центров выравнивающих узоров (одинаковы по строкам и столбцам)."""
    if version == 1:
        return []
    count = version // 7 + 2
    step = (version * 8 + count * 3 + 5) // (count * 4 - 4) * 2
    size = size_of(version)
    result = [size - 7 - i * step for i in range(count - 1)] + [6]
    return sorted(result)


def raw_data_modules(version: int) -> int:
    """Сколько модулей остаётся под данные и коррекцию после всех служебных узоров."""
    result = (16 * version + 128) * version + 64
    if version >= 2:
        count = version // 7 + 2
        result -= (25 * count - 10) * count - 55
        if version >= 7:
            result -= 36
    return result


def total_codewords(version: int) -> int:
    return raw_data_modules(version) // 8


def data_codewords(version: int, level: str) -> int:
    """Байтов данных = всего байтов − байтов коррекции во всех блоках."""
    return total_codewords(version) - ECC_PER_BLOCK[level][version] * NUM_BLOCKS[level][version]


def block_layout(version: int, level: str) -> list[tuple[int, int]]:
    """Блоки: [(байтов данных, байтов коррекции)]. Короткие блоки идут первыми, длинные на 1 байт больше."""
    blocks = NUM_BLOCKS[level][version]
    ecc = ECC_PER_BLOCK[level][version]
    total = total_codewords(version)
    short = blocks - total % blocks
    short_len = total // blocks
    return [(short_len - ecc + (0 if i < short else 1), ecc) for i in range(blocks)]
