"""Чтение QR-кода из матрицы модулей — обратный путь к qr_encode, с исправлением ошибок.

    1. Сторона матрицы → версия: n = 17 + 4·v.
    2. Служебная информация: читаем обе копии по 15 бит и выбираем ближайшее (по Хэммингу)
       из 32 допустимых значений. Код БЧХ (15,5) имеет d₀ = 7 и исправляет до 3 ошибочных бит.
    3. Для версий ≥ 7 так же читаем номер версии (код Голея (18,6), тоже до 3 ошибок).
    4. Снимаем маску (XOR с той же формулой), читаем биты «змейкой», собираем байты.
    5. Разбираем чередование обратно на блоки и исправляем каждый блок кодом Рида–Соломона.
    6. Разбираем поток бит: режим, число символов, данные.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import qr_tables as T
from . import reed_solomon as rs
from .qr_encode import (MASKS, data_order, format_bits, format_positions, function_patterns, version_bits,
                        version_positions)


class QRDecodeError(ValueError):
    pass


VALID_FORMATS = {format_bits(lv, mk): (lv, mk) for lv in T.LEVELS for mk in range(8)}
VALID_VERSIONS = {version_bits(v): v for v in range(7, 41)}


def _distance(a: int, b: int) -> int:
    return bin(a ^ b).count('1')


@dataclass
class BlockReport:
    index: int
    data_len: int
    ecc_len: int
    errors: int                      # сколько байтов исправил Рид–Соломон (−1 — не смог)
    positions: list[int] = field(default_factory=list)

    @property
    def capacity(self) -> int:
        return self.ecc_len // 2


@dataclass
class Decoded:
    text: str
    version: int
    level: str
    mask: int
    mode: str
    format_errors: int               # сколько бит служебной информации пришлось исправить (лучшая копия)
    blocks: list[BlockReport]
    raw: bytes = b''

    @property
    def corrected(self) -> int:
        return sum(max(0, b.errors) for b in self.blocks)


def read_format(m) -> tuple[str, int, int]:
    """(уровень, маска, число исправленных бит). Исключение, если обе копии испорчены сильнее 3 бит."""
    best = None
    for positions in format_positions(len(m)):
        value = sum(m[r][c] << i for i, (r, c) in enumerate(positions))
        code = min(VALID_FORMATS, key=lambda v: _distance(v, value))
        dist = _distance(code, value)
        if best is None or dist < best[2]:
            best = (*VALID_FORMATS[code], dist)
    if best[2] > 3:
        raise QRDecodeError('служебная информация (уровень и маска) повреждена в обеих копиях')
    return best


def read_version(m) -> int:
    size = len(m)
    if (size - 17) % 4 or not 21 <= size <= 177:
        raise QRDecodeError(f'неверный размер матрицы {size}×{size}')
    version = (size - 17) // 4
    if version < 7:
        return version
    for positions in version_positions(size):
        value = sum(m[r][c] << i for i, (r, c) in enumerate(positions))
        code = min(VALID_VERSIONS, key=lambda v: _distance(v, value))
        if _distance(code, value) <= 3 and VALID_VERSIONS[code] == version:
            return version
    return version                   # размер матрицы надёжнее испорченного поля версии


def deinterleave(codewords: list[int], version: int, level: str) -> list[list[int]]:
    """Обратное чередованию: собрать каждый блок (данные + коррекция)."""
    layout = T.block_layout(version, level)
    blocks: list[list[int]] = [[] for _ in layout]
    k = 0
    for i in range(max(d for d, _ in layout)):
        for b, (d, _) in enumerate(layout):
            if i < d:
                blocks[b].append(codewords[k])
                k += 1
    for _ in range(layout[0][1]):
        for b in range(len(layout)):
            blocks[b].append(codewords[k])
            k += 1
    return blocks


def parse_bits(data: list[int], version: int) -> tuple[str, str, bytes]:
    """Разобрать поток бит: (текст, режим, сырые байты)."""
    bits = ''.join(format(b, '08b') for b in data)
    pos = 0
    out = bytearray()
    modes = []

    def take(n):
        nonlocal pos
        if pos + n > len(bits):
            raise QRDecodeError('поток бит оборвался')
        v = int(bits[pos:pos + n], 2)
        pos += n
        return v

    while pos + 4 <= len(bits):
        indicator = take(4)
        if indicator == 0:
            break
        if indicator == 0b0111:                      # ECI — указание кодировки, просто пропускаем
            first = take(8)
            if first & 0x80:
                take(8 if first & 0x40 == 0 else 16)
            continue
        mode = next((k for k, (ind, _) in T.MODES.items() if ind == indicator), None)
        if mode is None:
            raise QRDecodeError(f'неизвестный режим {indicator:04b}')
        modes.append(mode)
        count = take(T.char_count_bits(mode, version))
        if mode == 'numeric':
            digits = ''
            while count >= 3:
                digits += f'{take(10):03d}'
                count -= 3
            if count == 2:
                digits += f'{take(7):02d}'
            elif count == 1:
                digits += str(take(4))
            out += digits.encode()
        elif mode == 'alphanumeric':
            chars = ''
            while count >= 2:
                v = take(11)
                chars += T.ALPHANUMERIC[v // 45] + T.ALPHANUMERIC[v % 45]
                count -= 2
            if count:
                chars += T.ALPHANUMERIC[take(6)]
            out += chars.encode()
        else:
            for _ in range(count):
                out.append(take(8))
    raw = bytes(out)
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('cp1251', errors='replace')
    return text, '+'.join(modes) or '—', raw


def decode_matrix(m) -> Decoded:
    """Прочитать QR-код из матрицы модулей (1 — тёмный)."""
    version = read_version(m)
    level, mask, ferr = read_format(m)
    _, kind = function_patterns(version)
    f = MASKS[mask]
    bits = ''.join(str(m[r][c] ^ (1 if f(r, c) else 0)) for r, c in data_order(kind))
    total = T.total_codewords(version)
    codewords = [int(bits[i * 8:i * 8 + 8], 2) for i in range(total)]
    reports, data = [], []
    for i, (block, (dlen, elen)) in enumerate(zip(deinterleave(codewords, version, level),
                                                  T.block_layout(version, level))):
        try:
            fix = rs.decode(block, elen)
        except rs.RSError as e:
            reports.append(BlockReport(i, dlen, elen, -1))
            err = QRDecodeError(f'блок {i + 1} из {len(T.block_layout(version, level))}: {e}')
            err.blocks = reports
            raise err from None
        reports.append(BlockReport(i, dlen, elen, fix.errors, fix.positions))
        data += fix.word[:dlen]
    text, mode, raw = parse_bits(data, version)
    return Decoded(text, version, level, mask, mode, ferr, reports, raw)
