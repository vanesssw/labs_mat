"""LZW (Лемпель — Зив — Велч, 1984) — словарный метод сжатия.

Вместо отдельных символов кодируются целые цепочки (фразы), которые уже
встречались раньше. Каждой цепочке в словаре присвоен номер — код. Словарь
строится «на лету» одинаково и при упаковке, и при распаковке, поэтому
хранить его в архиве не нужно: алгоритм «обучается» в процессе сжатия.

Кодирование (обозначения методички: s — текущая цепочка, K — следующий символ):
    s = первый символ
    пока есть символы:
        K = следующий символ
        если цепочка sK есть в словаре:  s = sK          (удлиняем цепочку)
        иначе:  выдать код(s);  добавить sK в словарь;  s = K
    выдать код(s)

Параметры этой реализации:
  • начальный словарь — все 256 однобайтовых цепочек (коды 0…255);
  • код 256 (CLEAR) — команда «очистить словарь»;
  • новые цепочки получают коды 257, 258, …;
  • код пишется переменным числом бит — ровно столько, сколько нужно для
    самого большого кода в словаре на данный момент (от 9 до 16 бит);
  • когда словарь заполнен (65 536 кодов), записывается CLEAR и обучение
    начинается заново — так словарь подстраивается под новые данные.
"""
from __future__ import annotations

from .bitio import BitReader, BitWriter

CLEAR = 256               # служебный код «очистить словарь»
FIRST_CODE = 257          # первый код для новых цепочек
MIN_WIDTH = 9             # 9 бит хватает для кодов 0…511
MAX_WIDTH = 16            # 16 бит — коды 0…65535
MAX_CODES = 1 << MAX_WIDTH


def code_width(max_code: int) -> int:
    """Сколько бит нужно, чтобы записать любой код от 0 до max_code (от 9 до 16)."""
    return min(MAX_WIDTH, max(MIN_WIDTH, max_code.bit_length()))


def compress(data: bytes) -> bytes:
    if not data:
        return b''
    writer = BitWriter()
    dictionary = {}          # (код цепочки s, байт K) → код цепочки sK
    next_code = FIRST_CODE   # код, который получит следующая новая цепочка
    stream = iter(data)
    s = next(stream)         # код текущей цепочки; для одного байта код = сам байт
    for k in stream:
        code = dictionary.get((s, k))
        if code is not None:                 # sK уже есть в словаре — удлиняем цепочку
            s = code
            continue
        writer.write_int(s, code_width(next_code - 1))  # выдаём код самой длинной известной цепочки
        if next_code < MAX_CODES:
            dictionary[(s, k)] = next_code              # запоминаем новую цепочку sK
            next_code += 1
        else:                                           # словарь заполнен — начинаем заново
            writer.write_int(CLEAR, code_width(next_code - 1))
            dictionary.clear()
            next_code = FIRST_CODE
        s = k                                           # новая цепочка начинается с K
    writer.write_int(s, code_width(next_code - 1))
    return writer.getvalue()


def decompress(payload: bytes, original_size: int | None = None) -> bytes:
    """Распаковка: словарь восстанавливается по тем же правилам, что при сжатии.

    Распаковщик отстаёт от упаковщика на один шаг: новую цепочку он может
    достроить только когда узнает первый символ следующей. Поэтому иногда
    приходит код, которого в словаре ещё нет (случай «sKsKs», например
    «аааа…»). Это может быть только цепочка «предыдущая + её первый символ».
    """
    reader = BitReader(payload)
    table = [bytes([b]) for b in range(256)] + [b'']  # table[код] = цепочка; 256 — CLEAR
    out = bytearray()
    prev = None                                       # цепочка, выданная на прошлом шаге
    while True:
        code = reader.read_int(code_width(len(table)))
        if code is None:                              # остались только добивочные нули
            break
        if code == CLEAR:
            del table[FIRST_CODE:]
            prev = None
            continue
        if code < len(table):
            entry = table[code]
        elif code == len(table) and prev is not None:
            entry = prev + prev[:1]                   # особый случай «sKsKs»
        else:
            raise ValueError('LZW: неизвестный код — данные повреждены')
        out += entry
        if prev is not None and len(table) < MAX_CODES:
            table.append(prev + entry[:1])            # та же цепочка, что добавил упаковщик
        prev = entry
    return bytes(out)
