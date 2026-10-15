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
    codes: dict                 # символ → код по дереву
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
        method=method, text=text, rows=rows, codes=codes, steps=steps, tree=tree,
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
    flag_count: int               # сколько раз флаг встречается в данных как обычный байт
    runs: list[tuple[str, int, int]]  # серии одинаковых символов: (символ, длина, байтов)
    tokens: list[RleToken]
    cells: list[tuple[str, str]]      # каждый байт сжатого потока: (подпись, 'flag' | 'count' | 'data')
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

    cells = [(FLAG_MARK, 'flag')]           # первый байт потока — сам выбранный флаг
    i = 1
    while i < len(packed):
        b = packed[i]
        i += 1
        if b != flag:
            literal.append(b)
            cells.append((label(b), 'data'))
            continue
        count = packed[i]
        i += 1
        cells += [(FLAG_MARK, 'flag'), (str(count), 'count')]
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
        if runs and runs[-1][0] == ch:
            runs[-1][1] += 1
        else:
            runs.append([ch, 1])
    size_codec = 'cp1251' if encoding == 'Windows-1251' else 'utf-8'
    runs = [(show(ch), k, len(ch.encode(size_codec)) * k) for ch, k in runs]
    return RleDemo(text, encoding, flag, f'{FLAG_MARK} = байт {flag} (0x{flag:02X})', data.count(flag),
                   runs, tokens, cells, len(data), len(packed))
