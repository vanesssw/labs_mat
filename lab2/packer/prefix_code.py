"""Префиксные коды — общая часть методов Хаффмана и Шеннона–Фано.

Оба метода строят двоичное кодовое дерево: символы сидят в листьях, код
символа — путь от корня до листа (влево — 0, вправо — 1). Раз символы только
в листьях, ни один код не является началом другого — код ПРЕФИКСНЫЙ,
и поток битов декодируется однозначно без разделителей.

Методы отличаются только тем, как строится дерево, то есть какие ДЛИНЫ кодов
получат символы. Размер сжатых данных зависит только от длин: Σ f_i·l_i бит.
Поэтому в архив записываются лишь длины, а сами кодовые слова назначаются
по единому правилу — «канонически». Распаковщик по тем же длинам получает
те же самые коды, и хранить всё дерево не нужно.

Формат сжатых данных:
    1 байт       — N − 1, где N — число различных байтов в файле (1..256);
    N × 2 байта  — пары (байт, длина его кода в битах);
    далее        — битовый поток: коды всех байтов подряд, добитый нулями до целого байта.
"""
from __future__ import annotations

from dataclasses import dataclass

from .bitio import BYTE_BITS, BitWriter


@dataclass(eq=False)
class Node:
    """Узел кодового дерева. У листа есть symbol, у внутреннего узла — два потомка."""

    weight: int                # частота символа или суммарная частота всего поддерева
    symbol: object = None      # символ (только у листа)
    left: Node | None = None   # ветка «0»
    right: Node | None = None  # ветка «1»

    @property
    def is_leaf(self) -> bool:
        return self.left is None and self.right is None


def tree_codes(root: Node | None) -> dict:
    """Прочитать коды по дереву: путь от корня до листа, шаг влево = '0', вправо = '1'."""
    if root is None:
        return {}
    if root.is_leaf:                # в сообщении всего один различный символ:
        return {root.symbol: '0'}   # дерево из одного листа, даём ему код «0»
    codes = {}
    stack = [(root, '')]
    while stack:
        node, path = stack.pop()
        if node.is_leaf:
            codes[node.symbol] = path
        else:
            stack.append((node.right, path + '1'))
            stack.append((node.left, path + '0'))
    return codes


def canonical_codes(lengths: dict) -> dict:
    """Канонический префиксный код с заданными длинами кодовых слов.

    Правило: символы упорядочиваются по (длина, символ). Первый получает код
    из одних нулей, каждый следующий — «предыдущий код + 1», а когда длина
    растёт, к коду справа дописываются нули (сдвиг влево). Если длины
    удовлетворяют неравенству Крафта Σ 2^(−l) ≤ 1, код получается префиксным.
    """
    codes = {}
    code = 0
    prev_len = 0
    for sym, length in sorted(lengths.items(), key=lambda item: (item[1], item[0])):
        code <<= length - prev_len
        codes[sym] = format(code, '0%db' % length)
        code += 1
        prev_len = length
    return codes


def write_table(lengths: dict) -> bytes:
    """Заголовок сжатых данных: N − 1, затем N пар (байт, длина кода)."""
    items = sorted(lengths.items())
    table = bytearray([len(items) - 1])
    for sym, length in items:
        table += bytes([sym, length])
    return bytes(table)


def read_table(payload: bytes) -> tuple[dict, int]:
    """Прочитать заголовок: {байт: длина кода} и позиция начала битового потока."""
    if not payload:
        raise ValueError('нет таблицы длин кодов')
    count = payload[0] + 1
    end = 1 + 2 * count
    if len(payload) < end:
        raise ValueError('таблица длин кодов обрезана')
    lengths = {payload[k]: payload[k + 1] for k in range(1, end, 2)}
    if len(lengths) != count or min(lengths.values()) == 0:
        raise ValueError('таблица длин кодов повреждена')
    longest = max(lengths.values())
    if sum(1 << (longest - l) for l in lengths.values()) > 1 << longest:
        raise ValueError('длины кодов нарушают неравенство Крафта')
    return lengths, end


def encode(data: bytes, codes: dict) -> bytes:
    """Заменить каждый байт его кодовым словом и упаковать биты в байты."""
    table = [codes.get(b, '') for b in range(256)]  # table[байт] = его код
    writer = BitWriter()
    for b in data:
        writer.write(table[b])
    return writer.getvalue()


def _decoding_tree(codes: dict) -> tuple[list, list, list]:
    """Восстановить дерево по кодовым словам. Узел 0 — корень.

    left[k] / right[k] — номер узла, в который ведёт бит 0 / 1 (−1 — пути нет);
    symbol[k] — символ в листе (−1 у внутренних узлов).
    """
    left, right, symbol = [-1], [-1], [-1]
    for sym, code in codes.items():
        node = 0
        for bit in code:
            branch = right if bit == '1' else left
            if branch[node] == -1:          # такой ветки ещё нет — создаём узел
                branch[node] = len(symbol)
                left.append(-1)
                right.append(-1)
                symbol.append(-1)
            node = branch[node]
        symbol[node] = sym
    return left, right, symbol


def decode(bitstream: bytes, codes: dict, count: int) -> bytes:
    """Декодирование: идём по дереву от корня, бит 0 — влево, 1 — вправо.

    Дошли до листа — записали его символ и вернулись в корень.
    Останавливаемся, когда восстановлено count символов (остаток — добивочные нули).
    """
    left, right, symbol = _decoding_tree(codes)
    out = bytearray()
    node = 0
    for byte in bitstream:
        for bit in BYTE_BITS[byte]:
            node = right[node] if bit == '1' else left[node]
            if node < 0:
                raise ValueError('в битовом потоке встретился несуществующий код')
            if symbol[node] >= 0:
                out.append(symbol[node])
                if len(out) == count:
                    return bytes(out)
                node = 0
    raise ValueError('битовый поток закончился раньше, чем ожидалось')


def compress(data: bytes, lengths: dict) -> bytes:
    """Сжать данные префиксным кодом с заданными длинами кодовых слов."""
    if not data:
        return b''
    return write_table(lengths) + encode(data, canonical_codes(lengths))


def decompress(payload: bytes, original_size: int) -> bytes:
    if original_size == 0:
        return b''
    lengths, start = read_table(payload)
    return decode(payload[start:], canonical_codes(lengths), original_size)
