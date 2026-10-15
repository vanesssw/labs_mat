"""Пошаговые решения заданий ЛР №3.

Решение собирается в объект Doc — список блоков (заголовки, абзацы, формулы, моноширинные
строки, таблицы). Интерфейс показывает Doc с оформлением, а solve.py печатает его как текст.
Так одно и то же решение видно и в окне программы, и в консоли, и попадает в отчёт.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import polynomials as poly
from .cyclic_code import CyclicCode
from .design import Design, design_code, griesmer_sum
from .gf2 import bits, error_vector, identity, to_str, weight, xor
from .group_code import GroupCode

OK, BAD = 'good', 'bad'


# ==========================================================================
# Документ с решением
# ==========================================================================

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
        """Моноширинный блок (матрицы, деление столбиком). lines — строка или список строк."""
        if isinstance(lines, str):
            lines = [lines]
        self.blocks.append(('mono', list(lines), tags))

    def table(self, rows: list[tuple], right: set[int] = frozenset(), marks: dict[int, str] | None = None) -> None:
        """Таблица: первая строка — заголовок; marks — {номер строки: тег} для подсветки строк."""
        self.blocks.append(('table', (rows, set(right), marks or {}), ()))

    def plain(self) -> str:
        """Текстовый вид для консоли."""
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


# ==========================================================================
# Вспомогательные функции оформления
# ==========================================================================

def matrix_lines(m, labels=None, split: int | None = None, row_labels=None) -> list[str]:
    """Матрица в моноширинном виде; split — после какого столбца поставить черту │."""
    width = max([1] + [len(lab) for lab in labels or []])
    rl_width = max([0] + [len(r) for r in row_labels or []])

    def fmt(cells, head=''):
        parts = []
        for i, c in enumerate(cells):
            if split is not None and i == split:
                parts.append('│')
            parts.append(str(c).rjust(width))
        return head.ljust(rl_width) + ('  ' if rl_width else '') + ' '.join(parts)

    lines = []
    if labels:
        lines.append(fmt(labels))
    for i, row in enumerate(m):
        lines.append(fmt(row, row_labels[i] if row_labels else ''))
    return lines


def xor_lines(rows: list[list[int]], titles: list[str]) -> list[str]:
    """Сложение нескольких векторов по модулю 2 «в столбик»."""
    total = [0] * len(rows[0])
    for r in rows:
        total = xor(total, r)
    w = max(len(t) for t in titles)
    lines = [('+ ' if i else '  ') + to_str(r) + '   ' + t.ljust(w) for i, (r, t) in enumerate(zip(rows, titles))]
    lines.append('  ' + '-' * len(total))
    lines.append('  ' + to_str(total))
    return lines


def positions_text(pos) -> str:
    return ' и '.join(map(str, pos)) if len(pos) == 2 else ', '.join(map(str, pos))


def wrap_pairs(items: list[tuple[str, str]], groups: int, head: tuple[str, str]) -> list[tuple]:
    """Длинную таблицу «ключ — значение» сворачиваем в несколько пар столбцов."""
    per = -(-len(items) // groups)
    rows = [tuple(x for _ in range(groups) for x in head)]
    for i in range(per):
        row: list[str] = []
        for g in range(groups):
            j = g * per + i
            row += list(items[j]) if j < len(items) else ['', '']
        rows.append(tuple(row))
    return rows


# ==========================================================================
# Задание 1. Групповой код (9,5)
# ==========================================================================

def task1(code: GroupCode, info, words, title: str = '') -> Doc:
    """Полное решение задания 1 для кода code, информационной части info и принятых комбинаций words."""
    d = Doc()
    k, r, n = code.k, code.r, code.n
    labels = [code.label(i) for i in range(1, n + 1)]
    d.h1(title or f'Задание 1. Групповой код ({n},{k})')

    # 1. Исходные данные
    d.h2('1. Образующая матрица')
    group = 'единичная матрица, «Группа 1»' if code.A == identity(k) else 'единицы на побочной диагонали, «Группа 2»'
    d.p(f'Образующая матрица G = [A | P] имеет k = nи = {k} строк и n = nи + nк = {n} столбцов. '
        f'Слева — информационная часть A ({group}), справа — проверочная матрица P из табл. 2.1:')
    d.mono(matrix_lines(code.G, labels, k, [f'{i})' for i in range(1, k + 1)]))
    d.p(f'Разряды a1…a{k} — информационные (nи = {k}), b1…b{r} — контрольные (nк = {r}). '
        f'Каждая строка G — разрешённая кодовая комбинация. Остальные получаются суммированием строк '
        f'по модулю 2; всего разрешённых комбинаций 2^{k} = {2 ** k} из 2^{n} = {2 ** n} возможных.')

    # 2. Свойства кода
    d.h2('2. Минимальное кодовое расстояние')
    d.p('Код групповой (линейный): сумма двух разрешённых комбинаций — снова разрешённая комбинация. '
        'Поэтому расстояние между любыми двумя комбинациями равно весу какой-то третьей комбинации, '
        'и минимальное кодовое расстояние равно минимальному весу ненулевой комбинации: d0 = Wmin.')
    words_all = code.codewords()
    by_w: dict[int, int] = {}
    for a, c in words_all:
        if any(a):
            by_w[weight(c)] = by_w.get(weight(c), 0) + 1
    d.table([('Вес комбинации W', 'Сколько комбинаций')] + [(w, by_w[w]) for w in sorted(by_w)], right={0, 1})
    d0 = code.min_distance
    d.formula(f'd0 = Wmin = {d0}', OK)
    d.formula(f'обнаруживает ошибки кратности до r = d0 − 1 = {code.detects}')
    d.formula(f'исправляет ошибки кратности до s = ⌊(d0 − 1) / 2⌋ = {code.corrects}')
    d.p('Все разрешённые комбинации кода:', 'muted')
    rows = [('№', 'Информационная часть', 'Комбинация', 'W')]
    for i, (a, c) in enumerate(words_all):
        rows.append((i, to_str(a), to_str(c[:k]) + ' ' + to_str(c[k:]), weight(c)))
    d.table(rows, right={0, 3})

    # 3. Контрольные соотношения
    d.h2('3. Контрольные соотношения')
    d.p('Контрольный разряд bj — сумма по модулю 2 тех информационных разрядов, напротив которых '
        'в j-м столбце матрицы P стоит единица (код линейный: проверочные символы — линейные '
        'комбинации информационных):')
    for j in range(1, r + 1):
        rows_with_one = code.relation_terms(j)
        d.formula(f'{code.relation_text(j)}      (в {j}-м столбце P единицы в строках {", ".join(map(str, rows_with_one))})')
    d.p(f'Если перенести bj в правую часть, получим проверки, которые выполняет приёмник. '
        f'Их коэффициенты образуют проверочную матрицу H = [Pᵀ | I{r}] размером {r}×{n}:')
    d.mono(matrix_lines(code.H, labels, k, [f'S{j}' for j in range(1, r + 1)]))
    for j in range(1, r + 1):
        d.formula(code.check_text(j))
    d.p('У правильной комбинации все Sj = 0. Набор S = (S1 … S{0}) называется синдромом (опознавателем). '
        'Синдром не зависит от переданной комбинации, только от ошибки: при одиночной ошибке '
        'в i-м разряде он совпадает с i-м столбцом H.'.format(r))

    # 4. Кодирование
    a = list(info)
    u = a if code.A == identity(k) else [x for x in code.encode(a)[:k]]
    c = code.encode(a)
    d.h2(f'4. Формирование избыточного кода для информационной части {to_str(a)}')
    if u != a:
        d.p(f'Информационная часть записывается в комбинацию как u = a·A = {to_str(u)}.')
    d.formula(', '.join(f'a{i + 1} = {x}' for i, x in enumerate(u)))
    for j in range(1, r + 1):
        terms = code.relation_terms(j)
        vals = ' ⊕ '.join(str(u[i - 1]) for i in terms) or '0'
        d.formula(f'{code.relation_text(j)} = {vals} = {c[k + j - 1]}')
    d.formula(f'Избыточный код: {to_str(c[:k])} {to_str(c[k:])}', OK)
    ones = [i + 1 for i, x in enumerate(a) if x]
    if ones:
        d.p(f'Проверка через образующую матрицу: складываем строки G с номерами {", ".join(map(str, ones))} '
            f'(там, где в информационной части единицы):')
        d.mono(xor_lines([code.G[i - 1] for i in ones], [f'строка {i}' for i in ones]))

    # 5. Проверка принятых комбинаций
    for num, w in enumerate(words, 1):
        group_check(d, code, w, f'5.{num}. Проверка принятой комбинации {num}: {to_str(w)}')
    return d


def group_check(d: Doc, code: GroupCode, w, title: str) -> None:
    """Проверка одной принятой комбинации группового кода по синдрому."""
    k, r, n = code.k, code.r, code.n
    w = list(w)
    d.h2(title)
    d.formula(f'информационные разряды {to_str(w[:k])}, контрольные {to_str(w[k:])}')
    s = code.syndrome(w)
    for j in range(1, r + 1):
        vals = ' ⊕ '.join([str(w[k + j - 1])] + [str(w[i - 1]) for i in code.relation_terms(j)])
        d.formula(f'{code.check_text(j)} = {vals} = {s[j - 1]}')
    d.formula(f'Синдром S = {to_str(s)}', OK if not any(s) else BAD)
    if not any(s):
        d.p('Синдром нулевой: все контрольные соотношения выполняются — комбинация принята без ошибок '
            f'(или ошибка совпала с разрешённой комбинацией — это возможно только при {code.min_distance} '
            f'и более ошибках). Информационная часть: {to_str(code.info_of(w))}.', OK)
        return
    d.p('Синдром ненулевой — комбинация принята с ошибкой. Синдромы одиночных ошибок — это столбцы H:')
    single = [(p, code.column(p)) for p in range(1, n + 1)]
    match = [p for p, col in single if col == s]
    rows = [('Ошибка в разряде', 'Синдром (столбец H)')] + [(f'{p} ({code.label(p)})', to_str(col)) for p, col in single]
    d.table(rows, marks={i + 1: BAD for i, (p, _) in enumerate(single) if p in match})
    if match:
        p = match[0]
        fixed = w[:]
        fixed[p - 1] ^= 1
        d.p(f'Синдром {to_str(s)} совпадает со столбцом {p} → возможна однократная ошибка в разряде {p} '
            f'({code.label(p)}). Инвертируем этот разряд:', BAD)
        d.mono(xor_lines([w, error_vector(n, [p])], ['принятая', 'вектор ошибки']))
        d.formula(f'Исправленная комбинация: {to_str(fixed[:k])} {to_str(fixed[k:])}, '
                  f'информационная часть {to_str(code.info_of(fixed))}', OK)
    else:
        d.p(f'Синдром {to_str(s)} не совпадает ни с одним столбцом H → однократной ошибкой он быть не может: '
            f'ошибок как минимум две. Код с d0 = {code.min_distance} такую ошибку обнаруживает, '
            f'но исправить её однозначно не может.', BAD)
    pairs = code.errors_with_syndrome(s, 2)
    if pairs:
        d.p(f'Двукратные ошибки, дающие тот же синдром {to_str(s)} (сумма двух столбцов H равна синдрому):')
        rows = [('Ошибки в разрядах', 'Столбцы H', 'Сумма')]
        for i, j in pairs:
            rows.append((f'{i} и {j} ({code.label(i)}, {code.label(j)})',
                         f'{to_str(code.column(i))} ⊕ {to_str(code.column(j))}', to_str(s)))
        d.table(rows)
        ex = pairs[:2]
        d.p('Примеры: ' + '; '.join(f'ошибки в разрядах {i} и {j}' for i, j in ex) + '. '
            'Приёмник не может отличить такие двукратные ошибки' + (' от однократной' if match else ' друг от друга') +
            ', поэтому код гарантированно исправляет только s = ' + str(code.corrects) + ' ошибку.', 'muted')
    else:
        d.p('Двукратных ошибок с таким синдромом нет.', 'muted')


# ==========================================================================
# Задание 2. Код для M комбинаций, исправляющий ошибки кратности ≤ s
# ==========================================================================

def task2(design: Design | None = None, M: int = 18, s: int = 2) -> Doc:
    res = design or design_code(M, s)
    d = Doc()
    M, s, k, d0 = res.M, res.s, res.k, res.d
    kind = {1: 'одиночные ошибки', 2: 'одиночные и двойные ошибки'}
    d.h1(f'Задание 2. Код для {M} комбинаций, исправляющий {kind.get(s, f"ошибки кратности до {s}")}')

    d.h2('1. Число информационных разрядов')
    d.p(f'Нужно закодировать M = {M} различных комбинаций. Двоичных слов длины k ровно 2^k, '
        f'поэтому берём наименьшее k, при котором 2^k ≥ M:')
    d.formula(f'k = nи = ⌈log₂ {M}⌉ = {k},   так как 2^{k - 1} = {2 ** (k - 1)} < {M} ≤ {2 ** k} = 2^{k}')

    d.h2('2. Требуемое кодовое расстояние')
    d.p('Если вокруг каждой разрешённой комбинации нарисовать «шар» радиуса s (все слова, отличающиеся '
        'от неё не более чем в s разрядах), то для исправления любых s ошибок шары не должны пересекаться: '
        'тогда принятое слово однозначно указывает на ближайшую разрешённую комбинацию. '
        'Для этого расстояние между комбинациями должно быть не меньше 2s + 1:')
    d.formula(f'd0 = 2s + 1 = 2·{s} + 1 = {d0}')
    d.p(f'Такой код дополнительно обнаруживает ошибки кратности до d0 − 1 = {d0 - 1} '
        '(если не пытаться их исправлять).', 'muted')

    d.h2('3. Число контрольных разрядов')
    d.p(f'Каждая исправляемая ошибка должна давать свой ненулевой синдром (опознаватель) из r = nк разрядов. '
        f'Ошибок кратности 0…{s} в комбинации длины n = k + r всего C(n,0) + … + C(n,{s}), '
        'а синдромов 2^r. Отсюда граница Хэмминга (необходимое условие):')
    d.formula(f'2^r ≥ ' + ' + '.join(f'C(n,{i})' for i in range(s + 1)))
    d.p('Граница Варшамова–Гильберта — достаточное условие: если оно выполнено, код с таким r точно существует:')
    d.formula(f'2^r > ' + ' + '.join(f'C(n−1,{i})' for i in range(d0 - 1)))
    d.p('Граница Грисмера для линейных кодов: n ≥ d0 + ⌈d0/2⌉ + ⌈d0/4⌉ + … (k слагаемых) '
        f'= {griesmer_sum(k, d0)}.', 'muted')
    rows = [('n', 'r = nк', 'Хэмминг', 'Варшамов–Гильберт', 'Подбор матрицы')]
    status = {'found': 'код найден ✓', 'none': 'полный перебор: кода нет', 'timeout': 'перебор прерван',
              'griesmer': 'невозможно (Грисмер)', '': '—'}
    marks = {}
    for i, b in enumerate(res.rows, 1):
        rows.append((b.n, b.r,
                     f'{2 ** b.r} {"≥" if b.hamming_ok else "<"} {b.hamming_sum} {"✓" if b.hamming_ok else "✗"}',
                     f'{2 ** b.r} {">" if b.vg_ok else "≤"} {b.vg_sum} {"✓" if b.vg_ok else "✗"}',
                     status[b.search] if b.hamming_ok else 'невозможно (Хэмминг)'))
        if b.search == 'found':
            marks[i] = OK
    d.table(rows, right={0, 1}, marks=marks)
    code = res.code
    if code is None:
        d.p('Код подобрать не удалось — увеличьте лимит перебора.', BAD)
        return d
    n, r = code.n, code.r
    for b in res.rows:
        if b.search == 'none':
            d.p(f'При n = {b.n} граница Хэмминга выполняется, но полный перебор показывает, что матрицы P '
                'с нужными свойствами нет: граница Хэмминга — только необходимое условие, а не достаточное.')
        elif b.search == 'griesmer':
            d.p(f'При n = {b.n} граница Хэмминга выполняется, но не выполняется граница Грисмера '
                f'(n ≥ {griesmer_sum(k, d0)}) — линейного кода такой длины нет.')
        elif b.search == 'timeout':
            d.p(f'При n = {b.n} перебор не уложился в отведённое время, поэтому минимальность найденного кода '
                'не доказана.', 'muted')
    d.formula(f'Выбираем код ({n},{k}): nи = {k}, nк = {r}, n = {n}, d0 = {d0}', OK)

    d.h2('4. Построение проверочной матрицы P')
    d.p(f'Комбинация, полученная сложением j строк G = [I{k} | P], имеет в информационной части ровно j единиц. '
        f'Чтобы её вес был не меньше d0 = {d0}, контрольная часть должна содержать не меньше d0 − j единиц:')
    for j in range(1, min(k, d0 - 1) + 1):
        what = 'каждой строки P' if j == 1 else f'суммы любых {j} строк P'
        d.formula(f'вес {what} ≥ d0 − {j} = {d0 - j}')
    d.p('Подбираем строки перебором с возвратом (первая строка — с единицами в старших разрядах, '
        'остальные — по возрастанию). Получилась матрица:')
    d.mono(matrix_lines(code.P, [f'b{j}' for j in range(1, r + 1)], None, [f'{i})' for i in range(1, k + 1)]))
    rows = [('j строк', 'Требуемый вес суммы', 'Минимальный вес суммы', '')]
    for j, need, got in res.subset_check:
        rows.append((j, f'≥ {need}', got, '✓' if got >= need else '✗'))
    d.table(rows, right={0, 2})

    d.h2('5. Образующая матрица и контрольные соотношения')
    labels = [code.label(i) for i in range(1, n + 1)]
    d.mono(matrix_lines(code.G, labels, k, [f'{i})' for i in range(1, k + 1)]))
    for j in range(1, r + 1):
        d.formula(code.relation_text(j))
    d.p(f'Проверка полным перебором всех 2^{k} − 1 = {2 ** k - 1} ненулевых комбинаций: '
        f'минимальный вес = {code.min_distance}, значит d0 = {code.min_distance}.',
        OK if code.min_distance >= d0 else BAD)

    d.h2(f'6. Кодовые комбинации для {M} сообщений')
    rows = [('№', 'Информационная часть', 'Кодовая комбинация', 'W')]
    for i, (a, c) in enumerate(code.codewords()[:M], 1):
        rows.append((i, to_str(a), to_str(c[:k]) + ' ' + to_str(c[k:]), weight(c)))
    d.table(rows, right={0, 3})
    if 2 ** k > M:
        d.p(f'Остальные {2 ** k - M} комбинаций из 2^{k} = {2 ** k} не используются, но тоже принадлежат коду.',
            'muted')

    d.h2('7. Таблица опознавателей (синдромов)')
    table = code.identifier_table(s)
    synd = [to_str(x) for _, x in table]
    unique = len(set(synd)) == len(synd) and '0' * r not in synd
    counts = ' + '.join(f'{sum(1 for p, _ in table if len(p) == t)}' for t in range(1, s + 1))
    d.p(f'Опознаватель — синдром S = H·eᵀ вектора ошибки e. Опознаватель ошибки в нескольких разрядах '
        f'равен сумме столбцов H этих разрядов. Ошибок кратности 1…{s}: {counts} = {len(table)}; '
        f'вместе с нулевым синдромом нужно {len(table) + 1} из 2^{r} = {2 ** r} возможных.')
    for t in range(1, s + 1):
        items = [(', '.join(map(str, p)), to_str(x)) for p, x in table if len(p) == t]
        name = {1: 'однократных', 2: 'двукратных', 3: 'трёхкратных', 4: 'четырёхкратных'}.get(t, f'{t}-кратных')
        d.p(f'Опознаватели {name} ошибок ({len(items)}):', 'muted')
        groups = 1 if len(items) <= 16 else 3
        d.table(wrap_pairs(items, groups, ('Разряды', 'Опознаватель')))
    if unique:
        d.p(f'Все {len(table)} опознавателей различны и ненулевые → по синдрому однозначно определяется, '
            f'в каких разрядах ошибка: код исправляет любые ошибки кратности до {s}.', OK)
    else:
        d.p('Есть совпадающие опознаватели — однозначное исправление невозможно.', BAD)

    # 8. Пример
    msg = min(M, 2 ** k) - 1
    a = [int(x) for x in format(msg, f'0{k}b')]
    c = code.encode(a)
    err = list(range(2, n + 1, max(1, (n - 1) // s)))[:s]
    v = xor(c, error_vector(n, err))
    dec = code.decode(v)
    d.h2(f'8. Пример: передача сообщения № {msg + 1} с {s}-кратной ошибкой')
    d.formula(f'передано  {to_str(c)}')
    d.formula(f'ошибки в разрядах {positions_text(err)}')
    d.formula(f'принято   {to_str(v)}')
    d.formula(f'синдром S = {to_str(dec.syndrome)} → по таблице: ошибка в разрядах '
              f'{positions_text(dec.positions)}')
    d.formula(f'исправлено {to_str(dec.corrected)} — ' +
              ('совпадает с переданной ✓' if dec.corrected == c else 'НЕ совпадает'),
              OK if dec.corrected == c else BAD)
    return d


# ==========================================================================
# Задание 3. Циклический код
# ==========================================================================

def division_block(d: Doc, a, g) -> list[int]:
    """Деление «столбиком» с подписями; возвращает остаток."""
    lines = poly.long_division(a, g)
    width = max(len(m) for m, _ in lines)
    d.mono([m.ljust(width) + ('   ← ' + note if note else '') for m, note in lines])
    return poly.mod(a, g)


def task3(code: CyclicCode, info, word, title: str = '') -> Doc:
    d = Doc()
    g, k, r, n = code.g, code.k, code.r, code.n
    d.h1(title or f'Задание 3. Циклический код ({n},{k})')

    d.h2('1. Исходные данные')
    d.formula(f'Образующий многочлен K(x) = {to_str(g)} = {poly.poly_str(g)}')
    d.formula(f'Информационная часть G(x) = {to_str(info)} = {poly.poly_str(info)}')
    d.formula(f'Проверяемая комбинация {to_str(word)}')
    d.p(f'Степень K(x) равна числу контрольных разрядов: nк = r = {r}. Информационных разрядов nи = k = {k}, '
        f'длина кода n = nи + nк = {n}. Комбинация записывается многочленом: разряд с номером i '
        f'(слева, с 1) — коэффициент при x^(n − i), то есть самый левый разряд — при x^{n - 1}.')

    d.h2('2. Свойства образующего многочлена')
    terms = weight(g)
    if poly.is_irreducible(g):
        d.p(f'K(x) неприводим — не раскладывается в произведение многочленов меньшей степени '
            f'(проверено делением на все многочлены степени 1…{r // 2}).', OK)
    else:
        factors = ' · '.join(f'({poly.poly_str(f)})' for f in poly.factorize(g))
        d.p(f'K(x) приводим: {poly.poly_str(g)} = {factors}. Методичка рекомендует неприводимые многочлены; '
            'приводимый тоже порождает код, но его свойства надо проверять отдельно.', BAD)
    per = code.period
    if per:
        d.p(f'Период K(x) — наименьшее e, при котором K(x) делит x^e + 1: e = {per}. '
            + (f'n = {n} кратно периоду, поэтому код циклический: циклический сдвиг разрешённой комбинации — '
               'снова разрешённая комбинация.' if code.is_cyclic else
               f'Так как n = {n} < {per}, код ({n},{k}) — укороченный циклический код ({per},{per - r}): '
               f'его комбинации — это комбинации кода длины {per}, у которых старшие {per - n} разрядов нулевые '
               'и поэтому не передаются. Все проверки делением на K(x) работают так же.'))
    d.p(f'Число ненулевых членов K(x) = {terms}. По методичке оно должно быть не меньше d0.')
    try:
        d0 = code.min_distance
        d.p(f'Перебором всех 2^{k} = {2 ** k} комбинаций: минимальный вес ненулевой комбинации d0 = {d0} → '
            f'код обнаруживает ошибки кратности до {code.detects} и исправляет до {code.corrects}.', OK)
    except ValueError:
        d0 = None

    d.h2('3. Образующая матрица: способ 1 — остатки от деления')
    d.p(f'Берём единичную транспонированную матрицу {k}×{k} (информационная часть). Дополнительная матрица '
        f'составляется из остатков от деления «единицы с нулями» на K(x): i-я строка единичной матрицы — это '
        f'многочлен x^({k} − i); после приписывания {r} нулей (умножения на x^{r}) он становится x^({n} − i). '
        f'Остатки удобно получать подряд: следующий остаток = предыдущий, сдвинутый влево на 1 разряд; '
        f'если из {r} разрядов «выпала» единица, прибавляем K(x).')
    rems = code.unit_remainders()
    rows = [('Строка', 'Делимое', 'Остаток', 'Вес')]
    for i, (m, rem) in enumerate(rems, 1):
        rows.append((i, f'{poly.power_str(m)} = 1{"0" * m}', to_str(rem), weight(rem)))
    d.table(rows, right={0, 3})
    G = code.generator_matrix()
    labels = [code.label(i) for i in range(1, n + 1)]
    d.mono(matrix_lines(G, labels, k, [f'{i})' for i in range(1, k + 1)]))
    need = (d0 or 3) - 1
    least = min(weight(rem) for _, rem in rems)
    d.p(f'Проверка требований методички: в каждом остатке {r} разрядов = nк ✓; остатков {k} = nи ✓; '
        f'вес каждого остатка ≥ d0 − 1 = {need}: минимальный вес {least} ' + ('✓' if least >= need else '✗'),
        OK if least >= need else BAD)

    d.h2('4. Образующая матрица: способ 2 — умножение на K(x)')
    d.p(f'Строки — многочлен K(x), умноженный на x^{k - 1}, …, x, 1 (сдвинутый влево на {k - 1}, …, 0 разрядов). '
        'Эта матрица порождает тот же самый код, но не систематическая: информационные разряды '
        'не стоят отдельно, поэтому для кодирования удобнее способ 1.')
    Gm = code.generator_matrix_by_multiplication()
    d.mono(matrix_lines(Gm, None, None, [f'K·{poly.power_str(k - i)}' for i in range(1, k + 1)]))

    d.h2('5. Формирование избыточного циклического кода')
    shifted, rem, c = code.encode_parts(info)
    d.p(f'Умножаем G(x) на x^{r} (приписываем {r} нулей) и делим на K(x). Остаток R(x) и будет контрольной частью:')
    d.formula(f'G(x)·x^{r} = {to_str(shifted)}')
    division_block(d, shifted, g)
    d.formula(f'R(x) = {to_str(rem)} = {poly.poly_str(rem)}')
    d.formula(f'F(x) = G(x)·x^{r} + R(x) = {to_str(c[:k])} {to_str(c[k:])}', OK)
    d.p(f'Проверка: F(x) делится на K(x) без остатка (остаток {to_str(code.syndrome(c))}). '
        'Тот же результат даёт сумма строк образующей матрицы (способ 1), соответствующих единицам G(x).', 'muted')

    d.h2(f'6. Проверка заданной комбинации {to_str(word)}')
    d.p('Делим принятую комбинацию F(x) на K(x):')
    R = division_block(d, word, g)
    d.formula(f'Остаток R = {to_str(R)}', OK if not any(R) else BAD)
    if not any(R):
        d.p('Комбинация делится без остатка — принята правильно. Контрольные разряды отбрасываются, '
            f'информационная часть: {to_str(word[:k])}.', OK)
        if code.corrects:
            trap_demo(d, code, c)
        return d
    d.p('Остаток ненулевой — комбинация ошибочная. Остаток зависит только от вектора ошибки E(x): '
        'остаток(F ⊕ E) = остаток(E). Одиночной ошибке в разряде i соответствует E(x) = x^(n − i), '
        'её остаток — x^(n − i) mod K(x):')
    table = code.single_error_table()
    match = [p for p, x in table if x == R]
    rows = [('Разряд', 'E(x)', 'Остаток')] + [(f'{p} ({code.label(p)})', poly.power_str(code.degree_of(p)), to_str(x))
                                              for p, x in table]
    d.table(rows, marks={i + 1: BAD for i, (p, _) in enumerate(table) if p in match})
    if match:
        p = match[0]
        fixed = list(word)
        fixed[p - 1] ^= 1
        d.p(f'Остаток {to_str(R)} совпадает с остатком ошибки в разряде {p} → однократная ошибка '
            f'в разряде {p} ({code.label(p)}, при {poly.power_str(code.degree_of(p))}) возможна.', BAD)
        d.formula(f'Исправленная комбинация: {to_str(fixed[:k])} {to_str(fixed[k:])}, '
                  f'информационная часть {to_str(fixed[:k])}', OK)
    else:
        outside = ''
        if per and per > n:
            deg = next((m for m in range(n, per) if poly.mod(poly.monomial(m), g) == R), None)
            if deg is not None:
                outside = (f' Такой остаток даёт {poly.power_str(deg)} — это была бы ошибка в разряде, соответствующем '
                           f'степени {deg}, но в комбинации всего {n} разрядов (степени 0…{n - 1}).')
        d.p(f'Остаток {to_str(R)} не совпадает ни с одним остатком одиночной ошибки → в пределах {n} '
            f'разрядов он НЕ может быть следствием однократной ошибки.{outside} Ошибка как минимум двукратная: '
            'комбинация бракуется (ошибка обнаружена, но не исправляется).', BAD)
    pairs = code.errors_with_syndrome(R, 2)
    if pairs:
        d.p(f'Двукратные ошибки с тем же остатком {to_str(R)} (сумма остатков двух одиночных ошибок):')
        rows = [('Ошибки в разрядах', 'E(x)', 'Сумма остатков')]
        for i, j in pairs:
            ri, rj = code.syndrome_of_errors((i,)), code.syndrome_of_errors((j,))
            rows.append((f'{i} и {j}', f'{poly.power_str(code.degree_of(i))} + {poly.power_str(code.degree_of(j))}',
                         f'{to_str(ri)} ⊕ {to_str(rj)} = {to_str(R)}'))
        d.table(rows)
        d.p('Примеры: ' + '; '.join(f'ошибки в разрядах {i} и {j}' for i, j in pairs[:2]) + '.', 'muted')
    if not code.corrects:
        return d
    trap_section(d, code, word, '7. Исправление по алгоритму методички (циклические сдвиги)')
    if not match:
        trap_demo(d, code, c)
    return d


def trap_section(d: Doc, code: CyclicCode, word, title: str) -> None:
    """Таблица шагов исправления циклическими сдвигами."""
    t = code.trap(word, 1)
    d.h2(title)
    if t.length != code.n:
        d.p(f'Код укороченный, поэтому сдвиги выполняются на полной длине {t.length}: к комбинации слева '
            f'приписано {t.length - code.n} нулей. Остаток сдвинутой комбинации можно не делить заново — '
            'достаточно сдвинуть предыдущий остаток влево и, если «выпала» единица, прибавить K(x).', 'muted')
    rows = [('Сдвиг влево', 'Комбинация', 'Остаток', 'Вес W')]
    for st in t.steps:
        rows.append((st.shift, to_str(st.word), to_str(st.remainder), st.weight))
    last = len(t.steps)
    d.table(rows, right={0, 3}, marks={last: OK if t.result else BAD})
    if t.result is None:
        if t.steps and 0 < t.steps[-1].weight <= 1:
            d.p(f'После {t.steps[-1].shift} сдвигов вес остатка стал W = 1, но «исправление» попадает в приписанные '
                f'нули — за пределы {code.n} разрядов. Значит, однократной ошибки в пределах кода нет.', BAD)
        else:
            d.p('Ни при одном сдвиге вес остатка не стал ≤ s = 1 — однократной ошибки нет.', BAD)
        return
    last_step = t.steps[-1]
    if last_step.shift == 0 and last_step.weight == 0:
        d.p('Остаток нулевой — ошибок нет.', OK)
        return
    d.p(f'При сдвиге на {last_step.shift} вес остатка W = {last_step.weight} ≤ s = 1: складываем сдвинутую '
        f'комбинацию с остатком и сдвигаем результат обратно вправо на {last_step.shift} разрядов.')
    fixed = t.result
    pos = [i + 1 for i in range(code.n) if fixed[i] != word[i]]
    d.formula(f'Исправленная комбинация: {to_str(fixed[:code.k])} {to_str(fixed[code.k:])} '
              f'(ошибка была в разряде {positions_text(pos)})', OK)


def trap_demo(d: Doc, code: CyclicCode, c) -> None:
    """Демонстрация исправления сдвигами на сформированной комбинации с одиночной ошибкой."""
    p = 2
    v = xor(c, error_vector(code.n, [p]))
    trap_section(d, code, v, f'8. Пример исправления сдвигами: ошибка в разряде {p} сформированной комбинации '
                             f'{to_str(c)} → {to_str(v)}')


# ==========================================================================
# Решение по варианту
# ==========================================================================

def variant_docs(number: int, group: int = 1) -> list[Doc]:
    """Все три задания для варианта с номером number (1–18) и группой 1/2."""
    from . import variants as V
    t = V.table_variant(number)
    code1 = GroupCode.from_variant(V.check_part(number), group)
    info, w1, w2 = V.GROUP_TASKS[t]
    doc1 = task1(code1, bits(info), [bits(w1), bits(w2)],
                 f'Задание 1. Групповой код (9,5) — табл. 2.1 вариант {number}, «Группа {group}», табл. 2.2 вариант {t}')
    doc2 = task2(M=18, s=2)
    g, info3, w3 = V.CYCLIC_TASKS[t]
    code3 = CyclicCode(bits(g), len(w3))
    doc3 = task3(code3, bits(info3), bits(w3), f'Задание 3. Циклический код ({code3.n},{code3.k}) — табл. 2.3 вариант {t}')
    return [doc1, doc2, doc3]
