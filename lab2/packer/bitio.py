"""Работа с отдельными битами.

Файл на диске состоит из целых байтов (по 8 бит), а коды Хаффмана,
Шеннона–Фано и LZW имеют произвольную длину: 2 бита, 5 бит, 12 бит...
Поэтому коды сначала склеиваются в одну строку из символов '0' и '1',
а потом каждые 8 символов этой строки превращаются в один байт
(и обратно при распаковке). Последний неполный байт дополняется нулями.
"""
from __future__ import annotations

# BYTE_BITS[b] — восьмибитная запись числа b, например BYTE_BITS[5] == '00000101'.
BYTE_BITS = [format(b, '08b') for b in range(256)]

_FLUSH_AT = 1 << 16  # сколько битов копить, прежде чем переводить их в байты


def bits_to_bytes(bits: str) -> bytes:
    """'0100000101' → байты. Неполный последний байт дополняется нулями справа."""
    if not bits:
        return b''
    bits += '0' * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, 'big')


def bytes_to_bits(data: bytes) -> str:
    """Байты → строка из '0' и '1' (по 8 символов на каждый байт)."""
    return ''.join(map(BYTE_BITS.__getitem__, data))


class BitWriter:
    """Принимает кодовые слова строками из '0'/'1' и упаковывает их в байты."""

    def __init__(self) -> None:
        self._out = bytearray()  # уже готовые байты
        self._parts = []         # кусочки битовой строки, ещё не переведённые в байты
        self._pending = 0        # сколько битов лежит в _parts
        self.bit_count = 0       # сколько всего битов записано

    def write(self, bits: str) -> None:
        self._parts.append(bits)
        self._pending += len(bits)
        self.bit_count += len(bits)
        if self._pending >= _FLUSH_AT:
            self._flush()

    def write_int(self, value: int, width: int) -> None:
        """Записать число value ровно width битами (с ведущими нулями)."""
        self.write(format(value, '0%db' % width))

    def _flush(self) -> None:
        bits = ''.join(self._parts)
        whole = len(bits) - len(bits) % 8   # сколько битов складывается в целые байты
        self._out += bits_to_bytes(bits[:whole])
        rest = bits[whole:]
        self._parts = [rest]
        self._pending = len(rest)

    def getvalue(self) -> bytes:
        """Все записанные биты в виде байтов (хвост добит нулями)."""
        self._flush()
        return bytes(self._out) + bits_to_bytes(''.join(self._parts))


class BitReader:
    """Читает из байтов целые числа заданной ширины в битах (нужно для LZW)."""

    _CHUNK = 1 << 13  # сколько байтов переводить в биты за один раз

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._next_byte = 0  # первый ещё не прочитанный байт
        self._bits = ''      # запас битов в виде строки
        self._pos = 0        # позиция в запасе

    def read_int(self, width: int) -> int | None:
        """Прочитать width бит как число; None, если столько битов уже не осталось."""
        if self._pos + width > len(self._bits):
            self._refill()
            if self._pos + width > len(self._bits):
                return None
        value = int(self._bits[self._pos:self._pos + width], 2)
        self._pos += width
        return value

    def _refill(self) -> None:
        chunk = self._data[self._next_byte:self._next_byte + self._CHUNK]
        self._next_byte += len(chunk)
        self._bits = self._bits[self._pos:] + bytes_to_bits(chunk)
        self._pos = 0
