"""Единый список методов сжатия.

У каждого метода одинаковый интерфейс:
    compress(data) -> payload                    — сжать байты;
    decompress(payload, original_size) -> data   — восстановить их.
Благодаря этому архиватор, интерфейс и тесты работают с любым методом одинаково.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import huffman, lzw, rle, shannon_fano


@dataclass(frozen=True)
class Method:
    key: str       # короткое имя для командной строки
    code: int      # номер метода в заголовке архива
    title: str     # название для людей
    summary: str   # идея метода одной строкой
    compress: Callable[[bytes], bytes]
    decompress: Callable[[bytes, int], bytes]


METHODS = {m.key: m for m in (
    Method('rle', 1, 'RLE',
           'серии одинаковых байтов заменяются тройкой «байт, флаг, количество»',
           rle.compress, rle.decompress),
    Method('huffman', 2, 'Хаффман',
           'частым байтам — короткие коды, редким — длинные; дерево строится снизу вверх',
           huffman.compress, huffman.decompress),
    Method('shannon', 3, 'Шеннон–Фано',
           'алфавит делится на группы с равными суммами частот; дерево строится сверху вниз',
           shannon_fano.compress, shannon_fano.decompress),
    Method('lzw', 4, 'LZW',
           'повторяющиеся цепочки байтов заменяются номерами в словаре, который строится на лету',
           lzw.compress, lzw.decompress),
)}

AUTO = 'auto'  # «попробовать все методы и оставить лучший»


def get_method(key_or_code: str | int) -> Method:
    """Найти метод по имени ('huffman') или по номеру из заголовка архива (2)."""
    if isinstance(key_or_code, int):
        for m in METHODS.values():
            if m.code == key_or_code:
                return m
        raise KeyError(f'неизвестный номер метода: {key_or_code}')
    return METHODS[key_or_code]
