"""Пошаговые объяснения построения и чтения кодов — для интерфейса и командной строки.

Объяснение собирается в объект Doc (заголовки, абзацы, формулы, таблицы), как в ЛР №3.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import code128, ean13
from . import qr_tables as T
from .gf256 import LOG
from .qr_encode import MASK_FORMULAS, QRCode, format_bits, version_bits
from .reed_solomon import generator_poly

OK, BAD = 'good', 'bad'


@dataclass
class Doc:
    blocks: list[tuple[str, object, tuple[str, ...]]] = field(default_factory=list)

    def h1(self, text: str) -> None:
        self.blocks.append(('h1', text, ()))

    def h2(self, text: str) -> None:
        self.blocks.append(('h2', text, ()))

    def p(self, text: str, *tags: str) -> None:
        self.blocks.append(('p', text, tags))

    def formula(self, text: str, *tags: str) -> None:
        self.blocks.append(('formula', text, tags))

    def mono(self, lines, *tags: str) -> None:
        if isinstance(lines, str):
            lines = [lines]
        self.blocks.append(('mono', list(lines), tags))

    def table(self, rows: list[tuple], right: set[int] = frozenset(), marks: dict[int, str] | None = None) -> None:
        self.blocks.append(('table', (rows, set(right), marks or {}), ()))

    def plain(self) -> str:
        out: list[str] = []
        for kind, data, _ in self.blocks:
            if kind == 'h1':
                out += ['', '=' * 78, data, '=' * 78]
            elif kind == 'h2':
                out += ['', data, '-' * len(data)]
            elif kind in ('p', 'formula'):
                out.append(('    ' if kind == 'formula' else '') + data)
            elif kind == 'mono':
                out += ['    ' + line for line in data]
            elif kind == 'table':
                rows, right, _ = data
                widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
                for j, r in enumerate(rows):
                    cells = [str(c).rjust(w) if i in right else str(c).ljust(w)
                             for i, (c, w) in enumerate(zip(r, widths))]
                    out.append('    ' + '  '.join(cells).rstrip())
                    if j == 0:
                        out.append('    ' + '  '.join('-' * w for w in widths))
        return '\n'.join(out).strip('\n') + '\n'


def chunks(s: str, n: int) -> str:
    return ' '.join(s[i:i + n] for i in range(0, len(s), n))


def alpha_poly(g: list[int]) -> str:
    """Многочлен с коэффициентами-степенями α: x² + α²⁵x + α¹ → 'x^2 + α^25·x + α^1'."""
    deg = len(g) - 1
    terms = []
    for i, c in enumerate(g):
        p = deg - i
        x = f'x^{p}' if p > 1 else 'x' if p == 1 else ''
        coef = '' if i == 0 else f'α^{LOG[c]}'
        terms.append(coef + ('·' if coef and x else '') + x)
    return ' + '.join(terms)


# ==========================================================================
# QR-код
# ==========================================================================

def qr_doc(q: QRCode) -> Doc:
    d = Doc()
    v, lv = q.version, q.level
    d.h1(f'QR-код: версия {v} ({q.size}×{q.size}), уровень {lv}, маска {q.mask}')

    d.h2('1. Анализ данных: режим и версия')
    nbytes = len(q.text.encode('utf-8'))
    d.p(f'Сообщение: {len(q.text)} символов ({nbytes} байт в UTF-8). Выбран режим «{T.MODE_NAMES[q.mode]}» — '
        'самый плотный, в котором записываются все символы:')
    d.table([('Режим', 'Символы', 'Плотность'),
             ('цифровой', '0–9', '3 цифры → 10 бит (3,33 бита на символ)'),
             ('буквенно-цифровой', '0–9, A–Z, пробел, $%*+-./:', '2 символа → 11 бит (5,5 бита)'),
             ('байтовый', 'любые байты (UTF-8)', '1 байт → 8 бит')],
            marks={['numeric', 'alphanumeric', 'byte'].index(q.mode) + 1: OK})
    cap = T.data_codewords(v, lv)
    d.p(f'Версия — наименьшая, в которую помещаются данные при уровне {lv} (~{T.LEVEL_PERCENT[lv]} % '
        f'восстанавливаемых байтов). В версии {v}: всего {T.total_codewords(v)} байтов, из них данных {cap}, '
        f'коррекции {T.total_codewords(v) - cap}.')
    rows = [('Уровень', 'Байтов данных', 'Байтов коррекции', 'Блоков', 'Исправит байтов')]
    for level in T.LEVELS:
        layout = T.block_layout(v, level)
        rows.append((f'{level} (~{T.LEVEL_PERCENT[level]} %)', T.data_codewords(v, level),
                     T.total_codewords(v) - T.data_codewords(v, level), len(layout),
                     sum(e // 2 for _, e in layout)))
    d.table(rows, right={1, 2, 3, 4}, marks={T.LEVELS.index(lv) + 1: OK})

    d.h2('2. Поток бит')
    rows = [('Часть', 'Биты')]
    shown = q.bit_parts if len(q.bit_parts) <= 40 else q.bit_parts[:30] + [('…', '…')] + q.bit_parts[-6:]
    for label, b in shown:
        rows.append((label, chunks(b, 8) if len(b) > 12 else b))
    d.table(rows)
    d.p(f'Индикатор режима {q.bit_parts[0][1]} говорит декодеру, как читать дальше; поле «число символов» '
        f'занимает {T.char_count_bits(q.mode, v)} бит в версии {v}. Терминатор 0000 отмечает конец данных, '
        'затем поток дополняется нулями до целого байта и байтами-заполнителями 11101100 (0xEC) и '
        '00010001 (0x11) — до ёмкости версии.', 'muted')
    d.p(f'Байты данных ({len(q.data)}): ' + ' '.join(map(str, q.data[:60])) + (' …' if len(q.data) > 60 else ''))

    d.h2('3. Блоки и коррекция Рида–Соломона')
    layout = T.block_layout(v, lv)
    ecc = layout[0][1]
    d.p(f'Данные делятся на {len(layout)} блок(а/ов). К каждому блоку добавляется {ecc} байтов коррекции — '
        f'остаток от деления D(x)·x^{ecc} на образующий многочлен g(x) = (x − α⁰)(x − α¹)…(x − α^{ecc - 1}) '
        f'над полем GF(256). Блок исправляет до ⌊{ecc}/2⌋ = {ecc // 2} ошибочных байтов.')
    d.formula('g(x) = ' + alpha_poly(generator_poly(ecc)))
    rows = [('Блок', 'Байтов данных', 'Байты коррекции')]
    for i, (data, e) in enumerate(q.blocks[:12], 1):
        rows.append((i, len(data), ' '.join(map(str, e[:14])) + (' …' if len(e) > 14 else '')))
    d.table(rows, right={0, 1})
    total_fix = sum(e // 2 for _, e in layout)
    d.formula(f'Всего можно исправить {total_fix} байтов из {T.total_codewords(v)} '
              f'= {total_fix / T.total_codewords(v) * 100:.1f} % (но не больше {ecc // 2} в каждом блоке)', OK)

    d.h2('4. Чередование байтов')
    d.p('Байты блоков записываются по очереди: 1-й байт блока 1, 1-й байт блока 2, …, затем 2-е байты и т. д.; '
        'после данных так же чередуются байты коррекции. Соседние в матрице байты принадлежат разным блокам, '
        'поэтому одна клякса распределяется по всем блокам понемногу и каждый блок может её исправить.')
    d.p('Итоговая последовательность: ' + ' '.join(map(str, q.codewords[:40])) + (' …' if len(q.codewords) > 40 else ''),
        'muted')

    d.h2('5. Матрица')
    n = q.size
    align = T.alignment_positions(v)
    d.p(f'Сторона матрицы n = 17 + 4·{v} = {n} модулей. Служебные элементы:')
    rows = [('Элемент', 'Где', 'Зачем')]
    rows.append(('3 шаблона поиска 7×7', 'три угла', 'по ним сканер находит код, его размер и поворот (1:1:3:1:1)'))
    rows.append(('разделители', 'вокруг шаблонов поиска', 'светлая рамка в 1 модуль'))
    rows.append(('синхронизирующие линии', 'строка 6 и столбец 6', 'чередование задаёт шаг сетки модулей'))
    if align:
        rows.append((f'выравнивающие узоры 5×5', f'центры в {", ".join(map(str, align))}',
                     'уточняют сетку при изгибе и перспективе'))
    rows.append(('служебная информация', 'около шаблонов поиска, 2 копии', 'уровень коррекции и номер маски'))
    if v >= 7:
        rows.append(('номер версии', '2 блока 6×3', 'версия, защищённая кодом Голея (18,6)'))
    rows.append(('тёмный модуль', f'строка {n - 8}, столбец 8', 'всегда тёмный'))
    d.table(rows)
    d.p(f'Оставшиеся {T.raw_data_modules(v)} модулей занимают данные: биты укладываются парами столбцов справа '
        'налево, «змейкой» — вверх, затем вниз, обходя служебные модули. '
        + (f'Последние {T.raw_data_modules(v) % 8} модуля(ей) — остаток, они светлые.'
           if T.raw_data_modules(v) % 8 else ''))

    d.h2('6. Выбор маски')
    d.p('Маска инвертирует модули данных там, где формула маски истинна (i — строка, j — столбец). Это разбивает '
        'большие одноцветные области и узоры, похожие на шаблон поиска. Для каждой из 8 масок считается штраф:')
    d.p('N1 — серии из 5 и более одинаковых модулей (3 + (длина − 5)); N2 — одноцветные квадраты 2×2 (по 3); '
        'N3 — узоры 1011101 с 4 светлыми модулями сбоку (по 40); N4 — отклонение доли тёмных от 50 % '
        '(по 10 за каждые 5 %).', 'muted')
    rows = [('Маска', 'Условие инверсии', 'N1', 'N2', 'N3', 'N4', 'Сумма')]
    for k in range(8):
        n1, n2, n3, n4 = q.penalties[k]
        rows.append((k, MASK_FORMULAS[k], n1, n2, n3, n4, n1 + n2 + n3 + n4))
    d.table(rows, right={0, 2, 3, 4, 5, 6}, marks={q.mask + 1: OK})

    d.h2('7. Служебная информация')
    data5 = T.FORMAT_BITS[lv] << 3 | q.mask
    rem = data5
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * T.FORMAT_GENERATOR)
    fb = format_bits(lv, q.mask)
    d.formula(f'уровень {lv} = {T.FORMAT_BITS[lv]:02b}, маска {q.mask} = {q.mask:03b} → 5 бит {data5:05b}')
    d.formula(f'остаток БЧХ: {data5:05b}·x¹⁰ mod (x¹⁰ + x⁸ + x⁵ + x⁴ + x² + x + 1) = {rem:010b}')
    d.formula(f'({data5:05b} {rem:010b}) XOR 101010000010010 = {fb:015b}', OK)
    d.p('БЧХ-код (15,5) имеет минимальное расстояние 7: декодер исправляет до 3 неверных бит. Две копии '
        'служебной информации лежат в разных углах — если одну закрыли, читается другая.', 'muted')
    if v >= 7:
        d.formula(f'версия {v} = {v:06b} → с кодом Голея {version_bits(v):018b}')
    return d


# ==========================================================================
# Штрих-коды
# ==========================================================================

def ean13_doc(code: str) -> Doc:
    d = Doc()
    full = ean13.normalize(code)
    d.h1(f'EAN-13: {full}')
    d.h2('1. Контрольная цифра')
    rows = [('Позиция', 'Цифра', 'Вес', 'Произведение')]
    total = 0
    for i, ch in enumerate(full[:12], 1):
        w = 3 if i % 2 == 0 else 1
        total += int(ch) * w
        rows.append((i, ch, w, int(ch) * w))
    d.table(rows, right={0, 1, 2, 3})
    d.formula(f'Сумма = {total}; контрольная = (10 − {total} mod 10) mod 10 = {full[12]}', OK)
    d.p('Веса 1 и 3 взаимно просты с 10, поэтому ошибка в любой одной цифре меняет сумму на число, '
        'не кратное 10, и всегда обнаруживается. Перестановка соседних цифр a и b меняет сумму на 2(a − b) '
        '— не обнаруживается только при |a − b| = 5.', 'muted')
    d.h2('2. Кодирование цифр')
    parity = ean13.PARITY[int(full[0])]
    d.p(f'Первая цифра {full[0]} не рисуется отдельно: она задаёт схему наборов левой половины {parity}. '
        'Цифры набора L содержат нечётное число тёмных модулей, G — чётное, R — инверсия L.')
    _, parts = ean13.encode(full)
    d.table([('Часть', 'Модули')] + [(label, m) for label, m in parts])
    d.p('Всего 3 + 6·7 + 5 + 6·7 + 3 = 95 модулей; слева 11 и справа 7 модулей светлого поля.', 'muted')
    return d


def code128_doc(text: str) -> Doc:
    d = Doc()
    d.h1(f'Code 128: «{text}»')
    syms = code128.symbols(text)
    values = [v for v, _ in syms]
    check = code128.checksum(values)
    d.h2('1. Символы')
    rows = [('№', 'Символ', 'Значение', 'Ширины', 'Вес i', 'i·значение')]
    for i, (v, label) in enumerate(syms):
        rows.append((i, label, v, code128.PATTERNS[v], i if i else 1, v * (i if i else 1)))
    d.table(rows, right={0, 2, 4, 5})
    weighted = values[0] + sum(i * v for i, v in enumerate(values[1:], 1))
    d.formula(f'Контрольный символ = ({values[0]} + Σ i·значение) mod 103 = {weighted} mod 103 = {check}', OK)
    d.p('Каждый символ — 3 штриха и 3 пробела суммарной шириной 11 модулей. Набор C кодирует пару цифр одним '
        'символом, поэтому длинные числа получаются вдвое короче.', 'muted')
    _, parts = code128.encode(text)
    d.table([('Часть', 'Модули')] + [(label, m) for label, m in parts])
    return d


# ==========================================================================
# Результат сканирования
# ==========================================================================

def scan_doc(scan, expected: str | None = None) -> Doc:
    d = Doc()
    if scan.decoded is None:
        d.h1('Код не прочитан')
        d.p(scan.error, BAD)
        return d
    r = scan.decoded
    ok = expected is None or r.text == expected
    d.h1('Код прочитан' + ('' if ok else ' с ошибкой!'))
    d.formula(f'Текст: {r.text}', OK if ok else BAD)
    mode = ' + '.join(T.MODE_NAMES.get(m, m) for m in r.mode.split('+'))
    d.p(f'Версия {r.version}, уровень {r.level}, маска {r.mask}, режим «{mode}». Обработка изображения: {scan.how}.')
    if scan.located:
        loc = scan.located
        d.p(f'Шаблоны поиска: левый верхний ({loc.top_left[0]:.0f}, {loc.top_left[1]:.0f}), правый верхний '
            f'({loc.top_right[0]:.0f}, {loc.top_right[1]:.0f}), левый нижний ({loc.bottom_left[0]:.0f}, '
            f'{loc.bottom_left[1]:.0f}); модуль ≈ {loc.module:.1f} пикс.', 'muted')
    d.p(f'Служебная информация: исправлено бит — {r.format_errors} (можно до 3).')
    rows = [('Блок', 'Байтов', 'Исправлено', 'Предел')]
    marks = {}
    for i, b in enumerate(r.blocks, 1):
        rows.append((b.index + 1, b.data_len + b.ecc_len, b.errors, b.capacity))
        if b.errors > 0:
            marks[i] = BAD if b.errors > b.capacity * 0.75 else OK
    d.table(rows, right={0, 1, 2, 3}, marks=marks)
    d.formula(f'Рид–Соломон исправил байтов: {r.corrected}', OK)
    return d
