"""Построение QR-кода по стандарту ISO/IEC 18004 — собственная реализация, без библиотек.

Этапы (так же устроено пошаговое объяснение в программе):
    1. Анализ данных: выбрать режим (цифровой, буквенно-цифровой, байтовый) и версию 1–40.
    2. Битовый поток: индикатор режима (4 бита) + число символов + данные + терминатор
       + выравнивание до байта + байты-заполнители 0xEC, 0x11.
    3. Разбиение на блоки и коррекция Рида–Соломона для каждого блока.
    4. Чередование (interleaving) байтов блоков — чтобы клякса портила понемногу каждый блок.
    5. Матрица: шаблоны поиска, разделители, синхронизирующие линии, выравнивающие узоры,
       тёмный модуль, место под служебную информацию; данные укладываются «змейкой» снизу вверх.
    6. Маска: 8 вариантов; выбирается маска с наименьшим штрафом (правила N1–N4).
    7. Служебная информация: уровень + номер маски, защищённые БЧХ-кодом (15,5); номер версии
       (для версий ≥ 7) — кодом Голея (18,6).
Матрица хранится как modules[строка][столбец], 1 — тёмный модуль.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import qr_tables as T
from . import reed_solomon as rs

MASKS = {
    0: lambda r, c: (r + c) % 2 == 0,
    1: lambda r, c: r % 2 == 0,
    2: lambda r, c: c % 3 == 0,
    3: lambda r, c: (r + c) % 3 == 0,
    4: lambda r, c: (r // 2 + c // 3) % 2 == 0,
    5: lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    6: lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    7: lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
}
MASK_FORMULAS = {
    0: '(i + j) mod 2 = 0', 1: 'i mod 2 = 0', 2: 'j mod 3 = 0', 3: '(i + j) mod 3 = 0',
    4: '(⌊i/2⌋ + ⌊j/3⌋) mod 2 = 0', 5: '(i·j) mod 2 + (i·j) mod 3 = 0',
    6: '((i·j) mod 2 + (i·j) mod 3) mod 2 = 0', 7: '((i + j) mod 2 + (i·j) mod 3) mod 2 = 0',
}


class QRError(ValueError):
    pass


# ==========================================================================
# 1–2. Режим, версия, битовый поток
# ==========================================================================

def choose_mode(text: str) -> str:
    """Самый плотный режим, в который помещаются все символы."""
    if text and all(ch in '0123456789' for ch in text):
        return 'numeric'
    if text and all(ch in T.ALPHANUMERIC for ch in text):
        return 'alphanumeric'
    return 'byte'


def _bits(value: int, length: int) -> str:
    return format(value, f'0{length}b')


def encode_data(text: str, mode: str) -> list[tuple[str, str]]:
    """Данные в битах по частям: [(пояснение, биты)]."""
    parts = []
    if mode == 'numeric':
        for i in range(0, len(text), 3):
            group = text[i:i + 3]
            parts.append((group, _bits(int(group), {3: 10, 2: 7, 1: 4}[len(group)])))
    elif mode == 'alphanumeric':
        for i in range(0, len(text), 2):
            pair = text[i:i + 2]
            if len(pair) == 2:
                value = 45 * T.ALPHANUMERIC.index(pair[0]) + T.ALPHANUMERIC.index(pair[1])
                parts.append((f'{pair} → 45·{T.ALPHANUMERIC.index(pair[0])} + {T.ALPHANUMERIC.index(pair[1])}',
                              _bits(value, 11)))
            else:
                parts.append((pair, _bits(T.ALPHANUMERIC.index(pair), 6)))
    else:
        for ch in text:
            for b in ch.encode('utf-8'):
                parts.append((f'{ch!r} → {b}' if ord(ch) < 128 else f'{ch!r} (UTF-8) → {b}', _bits(b, 8)))
    return parts


def char_count(text: str, mode: str) -> int:
    """Поле «число символов»: для байтового режима — число байтов UTF-8."""
    return len(text.encode('utf-8')) if mode == 'byte' else len(text)


def bits_needed(text: str, mode: str, version: int) -> int:
    return 4 + T.char_count_bits(mode, version) + sum(len(b) for _, b in encode_data(text, mode))


def choose_version(text: str, level: str, mode: str, minimum: int = 1) -> int:
    """Наименьшая версия, в которую помещаются данные при заданном уровне коррекции."""
    for v in range(minimum, 41):
        if char_count(text, mode) < 2 ** T.char_count_bits(mode, v) and \
                bits_needed(text, mode, v) <= T.data_codewords(v, level) * 8:
            return v
    raise QRError('данные не помещаются даже в версию 40')


def build_bitstream(text: str, mode: str, version: int, level: str) -> tuple[str, list[tuple[str, str]]]:
    """Полный поток бит данных и его разбор по частям [(название, биты)]."""
    capacity = T.data_codewords(version, level) * 8
    parts = [('индикатор режима', _bits(T.MODES[mode][0], 4)),
             (f'число символов ({T.char_count_bits(mode, version)} бит)',
              _bits(char_count(text, mode), T.char_count_bits(mode, version)))]
    parts += [(f'данные: {label}', b) for label, b in encode_data(text, mode)]
    bits = ''.join(b for _, b in parts)
    if len(bits) > capacity:
        raise QRError('данные не помещаются в выбранную версию')
    term = min(4, capacity - len(bits))
    if term:
        parts.append(('терминатор', '0' * term))
        bits += '0' * term
    pad = -len(bits) % 8
    if pad:
        parts.append(('дополнение до целого байта', '0' * pad))
        bits += '0' * pad
    i = 0
    while len(bits) < capacity:
        b = _bits(T.PAD_BYTES[i % 2], 8)
        parts.append((f'байт-заполнитель {T.PAD_BYTES[i % 2]:#04x}', b))
        bits += b
        i += 1
    return bits, parts


def to_bytes(bits: str) -> list[int]:
    return [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]


# ==========================================================================
# 3–4. Блоки, коррекция, чередование
# ==========================================================================

def make_blocks(data: list[int], version: int, level: str) -> list[tuple[list[int], list[int]]]:
    """[(данные блока, байты коррекции блока)]."""
    blocks, k = [], 0
    for size, ecc in T.block_layout(version, level):
        chunk = data[k:k + size]
        k += size
        blocks.append((chunk, rs.remainder(chunk, ecc)))
    return blocks


def interleave(blocks: list[tuple[list[int], list[int]]]) -> list[int]:
    """Сначала i-е байты данных всех блоков по очереди, затем так же байты коррекции."""
    out = []
    for i in range(max(len(d) for d, _ in blocks)):
        out += [d[i] for d, _ in blocks if i < len(d)]
    for i in range(len(blocks[0][1])):
        out += [e[i] for _, e in blocks]
    return out


# ==========================================================================
# 5. Матрица
# ==========================================================================

def format_bits(level: str, mask: int) -> int:
    """15 бит служебной информации: 5 бит (уровень + маска) + 10 бит БЧХ, затем XOR с 0x5412."""
    data = T.FORMAT_BITS[level] << 3 | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * T.FORMAT_GENERATOR)
    return (data << 10 | rem) ^ T.FORMAT_MASK


def version_bits(version: int) -> int:
    """18 бит номера версии: 6 бит версии + 12 бит кода Голея."""
    rem = version
    for _ in range(12):
        rem = (rem << 1) ^ ((rem >> 11) * T.VERSION_GENERATOR)
    return version << 12 | rem


def format_positions(size: int) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Где лежат 15 бит служебной информации: две копии, бит i → (строка, столбец)."""
    first = [(i, 8) for i in range(6)] + [(7, 8), (8, 8), (8, 7)] + [(8, 14 - i) for i in range(9, 15)]
    second = [(8, size - 1 - i) for i in range(8)] + [(size - 15 + i, 8) for i in range(8, 15)]
    return first, second


def version_positions(size: int) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Две копии 18 бит версии: блоки 6×3 у правого верхнего и левого нижнего шаблонов поиска."""
    first = [(i // 3, size - 11 + i % 3) for i in range(18)]
    second = [(size - 11 + i % 3, i // 3) for i in range(18)]
    return first, second


def function_patterns(version: int) -> tuple[list[list[int]], list[list[str | None]]]:
    """Служебные модули: (цвета, тип модуля или None для области данных)."""
    size = T.size_of(version)
    m = [[0] * size for _ in range(size)]
    kind: list[list[str | None]] = [[None] * size for _ in range(size)]

    def put(r, c, dark, k):
        m[r][c] = int(dark)
        kind[r][c] = k

    for i in range(size):                                  # синхронизирующие линии
        put(6, i, i % 2 == 0, 'timing')
        put(i, 6, i % 2 == 0, 'timing')
    for cr, cc in ((3, 3), (3, size - 4), (size - 4, 3)):  # шаблоны поиска 7×7 и разделители
        for dr in range(-4, 5):
            for dc in range(-4, 5):
                r, c = cr + dr, cc + dc
                if 0 <= r < size and 0 <= c < size:
                    dist = max(abs(dr), abs(dc))
                    put(r, c, dist not in (2, 4), 'separator' if dist == 4 else 'finder')
    pos = T.alignment_positions(version)                  # выравнивающие узоры 5×5
    last = len(pos) - 1
    for i, r in enumerate(pos):
        for j, c in enumerate(pos):
            if (i, j) in ((0, 0), (0, last), (last, 0)):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    put(r + dr, c + dc, max(abs(dr), abs(dc)) != 1, 'alignment')
    first, second = format_positions(size)                # место под служебную информацию
    for r, c in first + second:
        put(r, c, 0, 'format')
    put(size - 8, 8, 1, 'dark')                           # всегда тёмный модуль
    if version >= 7:
        bits = version_bits(version)
        a, b = version_positions(size)
        for i, ((r1, c1), (r2, c2)) in enumerate(zip(a, b)):
            put(r1, c1, bits >> i & 1, 'version')
            put(r2, c2, bits >> i & 1, 'version')
    return m, kind


def data_order(kind) -> list[tuple[int, int]]:
    """Порядок укладки битов: пары столбцов справа налево, «змейкой» вверх и вниз, столбец 6 пропускается."""
    size = len(kind)
    order = []
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        upward = ((right + 1) & 2) == 0
        for vert in range(size):
            r = size - 1 - vert if upward else vert
            for c in (right, right - 1):
                if kind[r][c] is None:
                    order.append((r, c))
        right -= 2
    return order


def place_data(m, kind, codewords: list[int]) -> None:
    bits = ''.join(format(b, '08b') for b in codewords)
    for i, (r, c) in enumerate(data_order(kind)):
        m[r][c] = int(bits[i]) if i < len(bits) else 0     # «лишние» модули (остаток) — светлые


def apply_mask(m, kind, mask: int) -> list[list[int]]:
    f = MASKS[mask]
    return [[v ^ 1 if kind[r][c] is None and f(r, c) else v for c, v in enumerate(row)] for r, row in enumerate(m)]


def draw_format(m, level: str, mask: int) -> None:
    bits = format_bits(level, mask)
    first, second = format_positions(len(m))
    for i, ((r1, c1), (r2, c2)) in enumerate(zip(first, second)):
        m[r1][c1] = bits >> i & 1
        m[r2][c2] = bits >> i & 1
    m[len(m) - 8][8] = 1


# ==========================================================================
# 6. Штраф маски
# ==========================================================================

def penalty(m) -> tuple[int, int, int, int]:
    """Штрафы (N1, N2, N3, N4): чем меньше, тем легче сканеру прочитать код."""
    size = len(m)
    lines = [row for row in m] + [[m[r][c] for r in range(size)] for c in range(size)]
    n1 = 0
    for line in lines:                                   # N1: серии ≥ 5 одинаковых модулей
        run = 1
        for a, b in zip(line, line[1:]):
            if a == b:
                run += 1
            else:
                n1 += 3 + run - 5 if run >= 5 else 0
                run = 1
        n1 += 3 + run - 5 if run >= 5 else 0
    n2 = 3 * sum(1 for r in range(size - 1) for c in range(size - 1)   # N2: одноцветные квадраты 2×2
                 if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1])
    n3 = 0                                                # N3: узор 1:1:3:1:1, похожий на шаблон поиска
    pat_a, pat_b = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0], [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
    for line in lines:
        ext = [0] * 4 + list(line) + [0] * 4
        for i in range(len(ext) - 10):
            window = ext[i:i + 11]
            if window == pat_a or window == pat_b:
                n3 += 40
    dark = sum(map(sum, m))                               # N4: доля тёмных далека от 50 %
    k = int(abs(dark * 100 / (size * size) - 50) // 5)
    return n1, n2, n3, 10 * k


# ==========================================================================
# Итог
# ==========================================================================

@dataclass
class QRCode:
    text: str
    level: str
    version: int
    mode: str
    mask: int
    modules: list[list[int]]
    kind: list[list[str | None]]
    bit_parts: list[tuple[str, str]]
    data: list[int]
    blocks: list[tuple[list[int], list[int]]]
    codewords: list[int]
    penalties: dict[int, tuple[int, int, int, int]] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.modules)

    @property
    def format_bits(self) -> int:
        return format_bits(self.level, self.mask)


def make_qr(text: str, level: str = 'M', version: int | None = None, mask: int | None = None,
            mode: str | None = None) -> QRCode:
    """Построить QR-код. version и mask = None — выбрать автоматически."""
    if level not in T.LEVELS:
        raise QRError('уровень коррекции — L, M, Q или H')
    if not text:
        raise QRError('пустое сообщение')
    mode = mode or choose_mode(text)
    if mode != 'byte' and choose_mode(text) == 'byte':
        raise QRError(f'символы сообщения нельзя записать в режиме «{T.MODE_NAMES[mode]}»')
    if version is None:
        version = choose_version(text, level, mode)
    elif not 1 <= version <= 40:
        raise QRError('версия — от 1 до 40')
    bits, parts = build_bitstream(text, mode, version, level)
    data = to_bytes(bits)
    blocks = make_blocks(data, version, level)
    codewords = interleave(blocks)
    base, kind = function_patterns(version)
    place_data(base, kind, codewords)
    candidates = {}
    for k in range(8):
        masked = apply_mask(base, kind, k)
        draw_format(masked, level, k)
        candidates[k] = (masked, penalty(masked))
    chosen = mask if mask is not None else min(range(8), key=lambda k: sum(candidates[k][1]))
    return QRCode(text, level, version, mode, chosen, candidates[chosen][0], kind, parts, data, blocks,
                  codewords, {k: v[1] for k, v in candidates.items()})
