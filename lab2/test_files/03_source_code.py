# ===== __init__.py =====
"""Пакет packer — алгоритмы сжатия данных без потерь (ЛР №2 «Методы упаковки данных»).

Модули:
    stats         — формулы теории информации: частоты, энтропия, коэффициенты;
    bitio         — запись и чтение отдельных битов;
    rle           — кодирование повторяющихся символов (RLE, «running»);
    prefix_code   — общая часть Хаффмана и Шеннона–Фано (дерево, канонический код,
                    кодирование и декодирование битового потока);
    huffman       — построение кода Хаффмана (дерево снизу вверх);
    shannon_fano  — построение кода Шеннона–Фано (дерево сверху вниз);
    lzw           — словарный метод Лемпеля–Зива–Велча;
    methods       — список методов с единым интерфейсом compress/decompress;
    container     — формат файла-архива .lab2 и операции с файлами;
    explain       — пошаговые демонстрации для вкладки «Как это работает».
"""

# ===== bitio.py =====
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

# ===== container.py =====
"""Формат файла-архива .lab2 и операции с файлами.

Заголовок архива (20 байт + имя файла), числа записаны в порядке little-endian:

    смещение  размер  поле
    0         4       сигнатура b'LAB2' — признак «это наш архив»
    4         1       версия формата (1)
    5         1       метод: 1 — RLE, 2 — Хаффман, 3 — Шеннон–Фано, 4 — LZW
    6         8       размер исходных данных в байтах
    14        4       CRC-32 исходных данных — контроль, что распаковка без искажений
    18        2       длина имени исходного файла L (в байтах)
    20        L       имя исходного файла в кодировке UTF-8
    20 + L    …       сжатые данные (их формат описан в модуле метода)
"""
from __future__ import annotations

import binascii
import struct
import time
from dataclasses import dataclass
from itertools import count
from pathlib import Path

from .methods import AUTO, METHODS, Method, get_method
from .stats import percent, ratio

MAGIC = b'LAB2'
VERSION = 1
EXTENSION = '.lab2'
_HEADER = struct.Struct('<4sBBQIH')  # сигнатура, версия, метод, размер, CRC-32, длина имени


class ArchiveError(Exception):
    """Файл не является архивом ЛР2 или повреждён."""


def crc32(data: bytes) -> int:
    """CRC-32 — остаток от деления «многочлена данных» на стандартный порождающий многочлен."""
    return binascii.crc32(data) & 0xFFFFFFFF


def choose_best(data: bytes) -> tuple[Method, bytes]:
    """Режим «Авто»: сжать всеми методами и оставить самый короткий результат."""
    best = None
    for m in METHODS.values():
        payload = m.compress(data)
        if best is None or len(payload) < len(best[1]):
            best = (m, payload)
    return best


def pack(data: bytes, method: str = 'huffman', name: str = '') -> bytes:
    """Собрать архив: заголовок + имя файла + сжатые данные."""
    if method == AUTO:
        m, payload = choose_best(data)
    else:
        m = get_method(method)
        payload = m.compress(data)
    name_bytes = name.encode('utf-8')[:0xFFFF]
    header = _HEADER.pack(MAGIC, VERSION, m.code, len(data), crc32(data), len(name_bytes))
    return header + name_bytes + payload


@dataclass
class ArchiveInfo:
    name: str             # имя исходного файла
    method: Method
    original_size: int
    crc: int
    header_size: int      # заголовок вместе с именем файла
    payload: bytes        # сжатые данные


def read_info(archive: bytes) -> ArchiveInfo:
    """Разобрать заголовок архива (без распаковки данных)."""
    if len(archive) < _HEADER.size or archive[:4] != MAGIC:
        raise ArchiveError('это не архив ЛР №2 (нет сигнатуры LAB2)')
    _, version, code, size, crc, name_len = _HEADER.unpack_from(archive)
    if version != VERSION:
        raise ArchiveError(f'неподдерживаемая версия формата: {version}')
    try:
        method = get_method(code)
    except KeyError as e:
        raise ArchiveError(str(e)) from None
    start = _HEADER.size + name_len
    name = archive[_HEADER.size:start].decode('utf-8', errors='replace')
    return ArchiveInfo(name, method, size, crc, start, archive[start:])


def unpack(archive: bytes) -> tuple[ArchiveInfo, bytes]:
    """Распаковать архив и проверить, что данные восстановлены без искажений."""
    info = read_info(archive)
    try:
        data = info.method.decompress(info.payload, info.original_size)
    except (ValueError, IndexError) as e:
        raise ArchiveError(f'архив повреждён: {e}') from None
    if len(data) != info.original_size or crc32(data) != info.crc:
        raise ArchiveError('контрольная сумма CRC-32 не совпала — архив повреждён')
    return info, data


@dataclass
class Result:
    """Итог операции над файлом — для вывода пользователю."""
    source: Path
    target: Path
    method: Method
    original_size: int
    archive_size: int
    seconds: float

    @property
    def ratio(self) -> float:
        return ratio(self.original_size, self.archive_size)

    @property
    def percent(self) -> float:
        return percent(self.original_size, self.archive_size)


def free_name(path: Path) -> Path:
    """Если такой файл уже есть — добавить « (1)», « (2)»…, как делает Windows."""
    if not path.exists():
        return path
    for i in count(1):
        candidate = path.with_name(f'{path.stem} ({i}){path.suffix}')
        if not candidate.exists():
            return candidate


def compress_file(source, target=None, method: str = 'huffman') -> Result:
    source = Path(source)
    data = source.read_bytes()
    started = time.perf_counter()
    archive = pack(data, method, source.name)
    seconds = time.perf_counter() - started
    target = Path(target) if target else source.with_name(source.name + EXTENSION)
    target.write_bytes(archive)
    return Result(source, target, read_info(archive).method, len(data), len(archive), seconds)


def decompress_file(source, target=None) -> Result:
    source = Path(source)
    archive = source.read_bytes()
    started = time.perf_counter()
    info, data = unpack(archive)
    seconds = time.perf_counter() - started
    if target:
        target = Path(target)
    else:
        name = Path(info.name).name or source.stem  # отбрасываем возможные пути в имени
        target = free_name(source.with_name(name))
    target.write_bytes(data)
    return Result(source, target, info.method, len(data), len(archive), seconds)


@dataclass
class BenchRow:
    method: Method
    archive_size: int
    compress_seconds: float
    decompress_seconds: float
    ok: bool              # распакованные данные совпали с исходными


def benchmark(data: bytes, name: str = '') -> list[BenchRow]:
    """Сжать данные каждым методом, распаковать обратно и проверить совпадение."""
    rows = []
    for m in METHODS.values():
        t0 = time.perf_counter()
        archive = pack(data, m.key, name)
        t1 = time.perf_counter()
        try:
            _, restored = unpack(archive)
            ok = restored == data
        except ArchiveError:
            ok = False
        t2 = time.perf_counter()
        rows.append(BenchRow(m, len(archive), t1 - t0, t2 - t1, ok))
    return rows

# ===== explain.py =====
"""Пошаговые демонстрации алгоритмов на коротком сообщении.

Используются во вкладке «Как это работает» и в примерах отчёта. Алгоритмы те же,
что в архиваторе, но вместо байтов — буквы, и каждый шаг записывается,
чтобы его можно было показать человеку.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, log2

from . import huffman, rle, shannon_fano
from .prefix_code import Node, canonical_codes, tree_codes
from .stats import CodeQuality, code_quality, frequencies, kraft_sum

_VISIBLE = {' ': '␣', '\n': '↵', '\r': '␍', '\t': '⇥'}
FLAG_MARK = '⚑'


def show(symbol: str) -> str:
    """Как показать символ человеку: пробел → «␣», перевод строки → «↵»."""
    return ''.join(_VISIBLE.get(ch, ch) for ch in symbol)


@dataclass
class DrawNode:
    """Узел дерева в виде, удобном для рисования."""
    text: str                                     # надпись в кружке
    caption: str = ''                             # подпись под листом
    children: list = field(default_factory=list)  # [(подпись ребра, DrawNode)]
    leaf: bool = False


# --------------------------------------------------------------------------
# Хаффман и Шеннон–Фано
# --------------------------------------------------------------------------

@dataclass
class CodeRow:
    symbol: str
    freq: int
    prob: float       # p = f / n
    info: float       # собственная информация −log2 p, бит
    code: str         # код, прочитанный по дереву
    canonical: str    # канонический код с той же длиной (так хранится в архиве)


@dataclass
class PrefixDemo:
    method: str                 # 'huffman' или 'shannon'
    text: str
    rows: list[CodeRow]         # символы по убыванию частоты
    steps: list[str]            # словесное описание шагов построения дерева
    tree: DrawNode | None
    quality: CodeQuality        # H, Hmax, lср, Kсс, Kоэ
    kraft: float                # Σ 2^(−l)
    uniform_bits: int           # длина равномерного кода ⌈log2 N⌉
    encoded: str                # закодированное сообщение (строка из 0 и 1)

    @property
    def original_bits(self) -> int:
        return 8 * len(self.text)


def _leaves(node: Node) -> list:
    if node.is_leaf:
        return [node.symbol]
    return _leaves(node.left) + _leaves(node.right)


def _group(symbols, limit: int = 12) -> str:
    text = ''.join(show(s) for s in symbols)
    return '{' + (text if len(text) <= limit else text[:limit - 1] + '…') + '}'


def _node_name(node: Node) -> str:
    return show(node.symbol) if node.is_leaf else _group(_leaves(node))


def _draw(node: Node, codes: dict) -> DrawNode:
    if node.is_leaf:
        return DrawNode(str(node.weight), f'{show(node.symbol)}\n{codes[node.symbol]}', leaf=True)
    return DrawNode(str(node.weight), children=[('0', _draw(node.left, codes)),
                                                ('1', _draw(node.right, codes))])


def prefix_demo(text: str, method: str = 'huffman') -> PrefixDemo:
    """Построить код Хаффмана ('huffman') или Шеннона–Фано ('shannon') для сообщения."""
    freqs = frequencies(text)
    n = len(text)
    builder = huffman if method == 'huffman' else shannon_fano
    root, raw_steps = builder.build_tree(freqs)
    codes = tree_codes(root)
    lengths = {s: len(c) for s, c in codes.items()}
    canon = canonical_codes(lengths)
    order = sorted(freqs, key=lambda s: (-freqs[s], s))
    rows = [CodeRow(show(s), freqs[s], freqs[s] / n, -log2(freqs[s] / n), codes[s], canon[s])
            for s in order]

    steps = []
    if method == 'huffman':
        for i, (a, b, parent) in enumerate(raw_steps, 1):
            steps.append(f'{i}) {_node_name(a)}({a.weight}) + {_node_name(b)}({b.weight})'
                         f'  →  {_node_name(parent)}({parent.weight})')
    else:
        for i, (upper, lower) in enumerate(raw_steps, 1):
            whole = [s for s, _ in upper + lower]
            path = _common_prefix([codes[s] for s in whole])  # путь от корня до этой группы
            steps.append(f'{i}) {_group(whole)}({sum(f for _, f in upper + lower)})  →  '
                         f'{_group(s for s, _ in upper)}({sum(f for _, f in upper)}) : {path}0   |   '
                         f'{_group(s for s, _ in lower)}({sum(f for _, f in lower)}) : {path}1')

    if root is None:
        tree = None
    elif root.is_leaf:  # один символ: корень с единственной веткой «0»
        tree = DrawNode(str(root.weight), children=[('0', _draw(root, codes))])
    else:
        tree = _draw(root, codes)

    distinct = len(freqs)
    return PrefixDemo(
        method=method, text=text, rows=rows, steps=steps, tree=tree,
        quality=code_quality(freqs, lengths), kraft=kraft_sum(lengths),
        uniform_bits=max(1, ceil(log2(distinct))) if distinct else 0,
        encoded=''.join(codes[ch] for ch in text),
    )


def _common_prefix(words: list[str]) -> str:
    first, last = min(words), max(words)
    i = 0
    while i < len(first) and first[i] == last[i]:
        i += 1
    return first[:i]


# --------------------------------------------------------------------------
# LZW
# --------------------------------------------------------------------------

@dataclass
class LzwStep:
    symbol: str          # очередной входной символ K ('' — конец сообщения)
    sk: str              # обозначение «sK» как в методичке, например «2а»
    phrase: str          # сама цепочка sK, например «ба»
    output: int | None   # выданный код (если sK в словаре не нашлась)
    added: int | None    # код, под которым sK добавлена в словарь


@dataclass
class LzwDecodeStep:
    code: int
    entry: str           # цепочка, выданная на выход
    added: int | None    # код новой цепочки в словаре распаковщика
    added_phrase: str
    special: bool        # кода ещё не было в словаре (случай «sKsKs»)


@dataclass
class LzwDemo:
    text: str
    alphabet: dict              # символ → начальный код
    steps: list[LzwStep]
    codes: list[int]            # выход кодера
    phrases: dict               # код → цепочка (словарь после кодирования)
    decode_steps: list[LzwDecodeStep]
    decoded: str

    @property
    def fixed_width(self) -> int:
        """Бит на код, если все коды писать одинаковой длины (по самому большому коду)."""
        return max(self.phrases).bit_length() if self.phrases else 0

    @property
    def variable_bits(self) -> int:
        """Всего бит, если каждый код писать минимально нужной на тот момент длиной."""
        total, biggest = 0, max(self.alphabet.values(), default=0)
        for step in self.steps:
            if step.output is not None:
                total += biggest.bit_length()
            if step.added is not None:
                biggest = step.added
        return total


def lzw_demo(text: str, first_code: int = 1) -> LzwDemo:
    """LZW для сообщения: словарь начинается с алфавита сообщения (коды с first_code)."""
    alphabet = {ch: first_code + i for i, ch in enumerate(sorted(set(text)))}
    if not text:
        return LzwDemo(text, alphabet, [], [], {}, [], '')
    code_of = dict(alphabet)                       # цепочка → код
    next_code = first_code + len(alphabet)
    steps, codes = [], []
    s = text[0]
    steps.append(LzwStep(show(s), str(code_of[s]), s, None, None))
    for k in text[1:]:
        label = f'{code_of[s]}{show(k)}'
        if s + k in code_of:                       # sK уже в словаре — удлиняем цепочку
            steps.append(LzwStep(show(k), label, s + k, None, None))
            s = s + k
        else:                                      # выдаём код s, запоминаем sK
            codes.append(code_of[s])
            code_of[s + k] = next_code
            steps.append(LzwStep(show(k), label, s + k, code_of[s], next_code))
            next_code += 1
            s = k
    codes.append(code_of[s])
    steps.append(LzwStep('', '', '', code_of[s], None))

    table = {c: ch for ch, c in alphabet.items()}  # распаковщик: код → цепочка
    next_code = first_code + len(alphabet)
    decode_steps, out, prev = [], [], None
    for c in codes:
        special = c not in table
        entry = prev + prev[0] if special else table[c]
        out.append(entry)
        added, added_phrase = None, ''
        if prev is not None:
            table[next_code] = added_phrase = prev + entry[0]
            added = next_code
            next_code += 1
        decode_steps.append(LzwDecodeStep(c, entry, added, added_phrase, special))
        prev = entry

    return LzwDemo(text, alphabet, steps, codes, {c: p for p, c in code_of.items()},
                   decode_steps, ''.join(out))


def lzw_trie(demo: LzwDemo) -> DrawNode:
    """Словарь LZW в виде дерева: каждая цепочка — путь от корня, в узле — её код."""
    nodes = {'': DrawNode('·')}
    for code, phrase in sorted(demo.phrases.items(), key=lambda cp: (len(cp[1]), cp[0])):
        node = DrawNode(str(code), caption=show(phrase) if len(phrase) > 1 else '')
        nodes[phrase] = node
        nodes[phrase[:-1]].children.append((show(phrase[-1]), node))
    for node in nodes.values():
        node.leaf = not node.children
    return nodes['']


# --------------------------------------------------------------------------
# RLE
# --------------------------------------------------------------------------

@dataclass
class RleToken:
    kind: str     # 'lit' — обычные байты, 'run' — серия, 'esc' — экранированный флаг
    text: str     # как показать в сжатом потоке
    count: int    # сколько исходных байтов представляет
    size: int     # сколько байтов занимает в сжатом потоке


@dataclass
class RleDemo:
    text: str
    encoding: str
    flag: int
    flag_label: str
    runs: list[tuple[str, int]]   # серии одинаковых символов в исходном сообщении
    tokens: list[RleToken]
    original_size: int            # байт до сжатия
    packed_size: int              # байт после сжатия (вместе с байтом-флагом)


def rle_demo(text: str) -> RleDemo:
    """RLE для сообщения: настоящий байтовый RLE из архиватора, разобранный по шагам."""
    try:
        data, encoding = text.encode('cp1251'), 'Windows-1251'
    except UnicodeEncodeError:
        data, encoding = text.encode('utf-8'), 'UTF-8'
    codec = 'cp1251' if encoding == 'Windows-1251' else 'latin-1'

    def label(b: int) -> str:
        ch = bytes([b]).decode(codec, errors='replace')
        return show(ch) if ch.isprintable() or ch in _VISIBLE else f'<{b:02X}>'

    packed = rle.compress(data)
    flag = packed[0]
    tokens, literal = [], bytearray()

    def flush():
        if literal:
            tokens.append(RleToken('lit', ''.join(label(b) for b in literal), len(literal), len(literal)))
            literal.clear()

    i = 1
    while i < len(packed):
        b = packed[i]
        i += 1
        if b != flag:
            literal.append(b)
            continue
        count = packed[i]
        i += 1
        if count == rle.ESCAPE:
            flush()
            tokens.append(RleToken('esc', f'{FLAG_MARK} 0', 1, 2))
        elif literal:                       # «b ⚑ L»: b — последний обычный байт
            b = literal.pop()
            flush()
            tokens.append(RleToken('run', f'{label(b)} {FLAG_MARK} {count}', count, 3))
        else:                               # серия из самих флагов: «⚑ 0 ⚑ L»
            prev = tokens.pop()
            tokens.append(RleToken('run', f'{prev.text} {FLAG_MARK} {count}', count, prev.size + 2))
    flush()

    runs = []
    for ch in text:
        if runs and runs[-1][0] == show(ch):
            runs[-1] = (runs[-1][0], runs[-1][1] + 1)
        else:
            runs.append((show(ch), 1))
    return RleDemo(text, encoding, flag, f'{FLAG_MARK} = байт {flag} (0x{flag:02X})',
                   runs, tokens, len(data), len(packed))

# ===== huffman.py =====
"""Метод Хаффмана — построение оптимального префиксного кода.

Идея: частым символам — короткие коды, редким — длинные.
Алгоритм (Д. Хаффман, 1952):
  1) каждый символ — отдельный узел-лист с весом, равным его частоте;
  2) берём два узла с наименьшими весами и объединяем их в новый узел,
     вес которого равен сумме весов («вспомогательный символ» из ЛР №1);
  3) повторяем шаг 2, пока не останется один узел — корень дерева;
  4) код символа — путь от корня до его листа: влево — 0, вправо — 1.

Дерево строится СНИЗУ ВВЕРХ (от самых редких символов к корню). Такой код
оптимален: среди всех посимвольных префиксных кодов у него наименьшая
средняя длина lср, причём H ≤ lср < H + 1.
"""
from __future__ import annotations

import heapq
from itertools import count

from . import prefix_code
from .prefix_code import Node, tree_codes
from .stats import frequencies


def build_tree(freqs: dict) -> tuple[Node | None, list[tuple[Node, Node, Node]]]:
    """Построить дерево Хаффмана по частотам {символ: частота}.

    Возвращает корень и список шагов (узел1, узел2, новый узел-родитель).
    Очередь с приоритетом (heapq) каждый раз отдаёт узел с наименьшим весом.
    При равных весах первым берётся узел, созданный раньше (счётчик order),
    поэтому результат всегда одинаковый у архиватора и разархиватора.
    """
    order = count()
    heap = [(f, next(order), Node(f, s)) for s, f in sorted(freqs.items()) if f > 0]
    heapq.heapify(heap)
    steps = []
    while len(heap) > 1:
        w1, _, a = heapq.heappop(heap)  # самый редкий узел
        w2, _, b = heapq.heappop(heap)  # второй по редкости
        parent = Node(w1 + w2, left=a, right=b)
        steps.append((a, b, parent))
        heapq.heappush(heap, (parent.weight, next(order), parent))
    return (heap[0][2] if heap else None), steps


def code_lengths(freqs: dict) -> dict:
    """Длины кодов Хаффмана {символ: длина в битах} = глубины листьев в дереве."""
    root, _ = build_tree(freqs)
    return {s: len(code) for s, code in tree_codes(root).items()}


def compress(data: bytes) -> bytes:
    # Первый проход — подсчёт частот, второй (внутри encode) — само кодирование.
    return prefix_code.compress(data, code_lengths(frequencies(data)))


def decompress(payload: bytes, original_size: int) -> bytes:
    return prefix_code.decompress(payload, original_size)

# ===== lzw.py =====
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

# ===== methods.py =====
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

# ===== prefix_code.py =====
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

# ===== rle.py =====
"""RLE (Run-Length Encoding) — кодирование повторяющихся символов («running»).

Идея из методички: если в данных подряд идут L > 3 одинаковых байтов b,
их заменяют тройкой байтов

        b, ФЛАГ, L

    b     — сам повторяющийся байт (записывается как обычно);
    ФЛАГ  — служебный байт-«флажок»: «предыдущий байт нужно размножить»;
    L     — счётчик: сколько всего раз подряд стоит b (от 2 до 255).

Пример: 40 пробелов (40 байт) → «пробел, ФЛАГ, 40» (3 байта).

Главная проблема — выбор флага: в реальных файлах встречаются все 256
значений байта, «лишнего 257-го» значения нет. Решение (подсказка методички
«прочитайте про Хаффмана») — посчитать частоты байтов и взять флагом
САМЫЙ РЕДКИЙ байт, а лучше вообще не встречающийся. Если флаг всё же
попался в данных как обычный байт, он «экранируется» парой ФЛАГ, 0 —
нулевой счётчик означает «это не команда, а просто байт».

Формат сжатых данных: 1 байт — выбранный флаг, дальше закодированный поток.
"""
from __future__ import annotations

from collections import Counter

MIN_RUN = 4    # серию из 3 байтов сжимать бессмысленно: тройка тоже занимает 3 байта
MAX_RUN = 255  # счётчик хранится в одном байте, поэтому длинные серии режутся на части
ESCAPE = 0     # счётчик 0 после флага — «флаг здесь обычный байт данных»


def choose_flag(data: bytes) -> int:
    """Байт-флаг: самый редкий байт в данных (при равенстве — меньший по значению)."""
    counts = Counter(data)
    return min(range(256), key=lambda b: counts.get(b, 0))


def compress(data: bytes) -> bytes:
    flag = choose_flag(data)
    out = bytearray([flag])
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        j = i + 1                               # ищем конец серии одинаковых байтов
        while j < n and data[j] == b and j - i < MAX_RUN:
            j += 1
        run = j - i
        if b == flag:                           # флаг в данных: экранируем «ФЛАГ, 0»
            out += bytes([flag, ESCAPE])
            if run > 1:                         # и, если их несколько, размножаем
                out += bytes([flag, run])
        elif run >= MIN_RUN:
            out += bytes([b, flag, run])        # «b, ФЛАГ, L» — как в методичке
        else:
            out += data[i:j]                    # короткая серия — копируем как есть
        i = j
    return bytes(out)


def decompress(payload: bytes, original_size: int | None = None) -> bytes:
    if not payload:
        return b''
    flag = payload[0]
    out = bytearray()
    i, n = 1, len(payload)
    while i < n:
        b = payload[i]
        i += 1
        if b != flag:                           # обычный байт — просто переписываем
            out.append(b)
            continue
        if i >= n:
            raise ValueError('RLE: поток оборвался сразу после байта-флага')
        count = payload[i]
        i += 1
        if count == ESCAPE:                     # «ФЛАГ, 0» — это сам байт-флаг
            out.append(flag)
        elif out:                               # размножаем предыдущий байт до count штук
            out += bytes([out[-1]]) * (count - 1)
        else:
            raise ValueError('RLE: команда повтора в самом начале потока')
    return bytes(out)

# ===== shannon_fano.py =====
"""Метод Шеннона–Фано (как в ЛР №1).

  1) символы выписываются в порядке убывания частот (вероятностей);
  2) список делится на две группы так, чтобы суммарные частоты групп
     были как можно ближе друг к другу;
  3) верхней группе приписывается 0, нижней — 1;
  4) каждая группа снова делится по тому же правилу, пока в каждой
     не останется по одному символу.

Дерево строится СВЕРХУ ВНИЗ (от всего алфавита к отдельным символам).
Код тоже префиксный, но не всегда оптимальный: жадное деление пополам
иногда даёт среднюю длину чуть больше, чем у Хаффмана.
"""
from __future__ import annotations

from . import prefix_code
from .prefix_code import Node, tree_codes
from .stats import frequencies


def split_index(group: list[tuple[object, int]]) -> int:
    """Где разрезать список (уже отсортированный по убыванию частот),
    чтобы суммы частот верхней и нижней частей различались меньше всего."""
    total = sum(f for _, f in group)
    best_k, best_diff = 1, None
    upper_sum = 0
    for k in range(1, len(group)):
        upper_sum += group[k - 1][1]
        diff = abs(total - 2 * upper_sum)  # |верхняя сумма − нижняя сумма|
        if best_diff is None or diff < best_diff:
            best_k, best_diff = k, diff
    return best_k


def build_tree(freqs: dict) -> tuple[Node | None, list[tuple[list, list]]]:
    """Построить дерево Шеннона–Фано.

    Возвращает корень и список шагов-делений (верхняя группа, нижняя группа);
    группа — список пар (символ, частота).
    """
    items = sorted(((s, f) for s, f in freqs.items() if f > 0), key=lambda sf: (-sf[1], sf[0]))
    steps = []

    def build(group):
        if len(group) == 1:
            sym, f = group[0]
            return Node(f, sym)
        k = split_index(group)
        upper, lower = group[:k], group[k:]
        steps.append((upper, lower))
        return Node(sum(f for _, f in group), left=build(upper), right=build(lower))

    return (build(items) if items else None), steps


def code_lengths(freqs: dict) -> dict:
    root, _ = build_tree(freqs)
    return {s: len(code) for s, code in tree_codes(root).items()}


def compress(data: bytes) -> bytes:
    return prefix_code.compress(data, code_lengths(frequencies(data)))


def decompress(payload: bytes, original_size: int) -> bytes:
    # Распаковщику нужны только длины кодов, поэтому он тот же, что у Хаффмана.
    return prefix_code.decompress(payload, original_size)

# ===== stats.py =====
"""Формулы теории информации, которые используются в работе.

Обозначения (как в лекциях и в ЛР №1):
    n    — длина сообщения (сколько в нём символов или байтов);
    f_i  — частота: сколько раз встретился i-й символ;
    p_i  — вероятность символа, оценивается как f_i / n;
    N    — число различных символов в сообщении (объём алфавита);
    l_i  — длина кодового слова i-го символа в битах.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import log2


def frequencies(data) -> dict:
    """Частоты символов: {символ: сколько раз встретился}.

    Для bytes символы — числа 0..255 (байты), для str — буквы.
    """
    return dict(Counter(data))


def entropy(freqs: dict) -> float:
    """Энтропия Шеннона H = −Σ p_i·log2(p_i), бит на символ.

    Это среднее количество информации в одном символе. По теореме Шеннона
    это ещё и нижняя граница средней длины кода: lср ≥ H.
    """
    total = sum(freqs.values())
    h = 0.0
    for f in freqs.values():
        if f:
            p = f / total
            h -= p * log2(p)
    return h


def max_entropy(freqs: dict) -> float:
    """Hmax = log2(N) — энтропия, если бы все N символов были равновероятны (мера Хартли)."""
    n = sum(1 for f in freqs.values() if f)
    return log2(n) if n else 0.0


def redundancy(freqs: dict) -> float:
    """Избыточность R = 1 − H / Hmax (0 — избыточности нет, всё «по делу»)."""
    hmax = max_entropy(freqs)
    return 1 - entropy(freqs) / hmax if hmax else 0.0


def conditional_entropy(data) -> float:
    """Условная энтропия H1 = H(X_k | X_k−1), бит на символ.

    Неопределённость очередного символа, когда предыдущий уже известен.
    Считается как H(пар соседних символов) − H(первых символов этих пар).
    Всегда H1 ≤ H0: чем сильнее символы связаны друг с другом, тем меньше H1.
    """
    if len(data) < 2:
        return 0.0
    pairs = Counter(zip(data, data[1:]))
    firsts = Counter(data[:-1])
    return entropy(pairs) - entropy(firsts)


def average_length(freqs: dict, lengths: dict) -> float:
    """Средняя длина кодового слова lср = Σ p_i·l_i, бит на символ."""
    total = sum(freqs.values())
    if total == 0:
        return 0.0
    return sum(f * lengths[s] for s, f in freqs.items() if f) / total


def kraft_sum(lengths: dict) -> float:
    """Сумма Крафта Σ 2^(−l_i). Для любого префиксного кода она не больше 1."""
    return sum(2.0 ** -length for length in lengths.values())


@dataclass
class CodeQuality:
    """Характеристики эффективности неравномерного кода (как в ЛР №1)."""

    entropy: float      # H — энтропия, бит/символ
    max_entropy: float  # Hmax = log2 N, бит/символ
    avg_length: float   # lср — средняя длина кодового слова, бит/символ

    @property
    def k_cc(self) -> float:
        """Коэффициент статистического сжатия Kсс = Hmax / lср."""
        return self.max_entropy / self.avg_length if self.avg_length else 0.0

    @property
    def k_oe(self) -> float:
        """Коэффициент относительной эффективности Kоэ = H / lср (не больше 1)."""
        return self.entropy / self.avg_length if self.avg_length else 0.0


def code_quality(freqs: dict, lengths: dict) -> CodeQuality:
    return CodeQuality(entropy(freqs), max_entropy(freqs), average_length(freqs, lengths))


@dataclass
class DataProfile:
    """Статистический «портрет» файла."""

    size: int             # n — размер в байтах
    distinct: int         # N — сколько различных значений байта встречается
    entropy: float        # H0 — энтропия по частотам отдельных байтов, бит/байт
    max_entropy: float    # Hmax = log2 N
    cond_entropy: float   # H1 — энтропия с учётом предыдущего байта, бит/байт

    @property
    def limit_bytes(self) -> float:
        """Нижняя граница для ПОСИМВОЛЬНЫХ кодов (Хаффман, Шеннон–Фано): n·H0 / 8 байт."""
        return self.size * self.entropy / 8


def profile(data: bytes) -> DataProfile:
    freqs = frequencies(data)
    return DataProfile(len(data), len(freqs), entropy(freqs), max_entropy(freqs),
                       conditional_entropy(data))


def ratio(original_size: int, packed_size: int) -> float:
    """Коэффициент сжатия k = V_исх / V_сж (больше 1 — файл уменьшился)."""
    return original_size / packed_size if packed_size else float('inf')


def percent(original_size: int, packed_size: int) -> float:
    """Размер архива в процентах от исходного (меньше 100 % — сжатие, больше — расширение)."""
    return 100.0 * packed_size / original_size if original_size else float('inf')
