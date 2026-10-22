"""Пошаговые объяснения датчиков и тестов — для интерфейса и командной строки (как в ЛР №3–4)."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import generators as G
from . import properties as P
from .stat_tests import ALPHA, Result

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


def b32(x: int, n: int = 32) -> str:
    s = format(x, f'0{n}b')
    return ' '.join(s[i:i + 8] for i in range(0, n, 8))


# ==========================================================================
# Датчики
# ==========================================================================

def generator_doc(gen: G.Generator, steps: int = 10) -> Doc:
    d = Doc()
    d.h1(gen.name)
    d.formula(gen.formula)
    if isinstance(gen, G.MiddleSquare):
        _middle(d, gen, steps)
    elif isinstance(gen, G.LCG):
        _lcg(d, gen, steps)
    elif isinstance(gen, G.LFSR):
        _lfsr(d, gen, steps)
    elif isinstance(gen, G.Xorshift32):
        _xorshift(d, gen, steps)
    elif isinstance(gen, G.MT19937):
        _mt(d, gen, steps)
    elif isinstance(gen, G.BBS):
        _bbs(d, gen, steps)
    else:
        d.p('Эталонный генератор для сравнения: устройство см. в описании вихря Мерсенна (random) и в документации '
            'операционной системы (os.urandom собирает энтропию из аппаратных событий и обрабатывает её '
            'криптографическим алгоритмом).')
        rows = [('n', 'xₙ (32 бита)', 'uₙ = xₙ / 2³²')]
        for i in range(1, steps + 1):
            x = gen.next()
            rows.append((i, x, f'{x / gen.modulus:.6f}'))
        d.table(rows, right={0, 1})
    return d


def _middle(d: Doc, g: G.MiddleSquare, steps: int) -> None:
    d.p('Исторически первый программный датчик (Дж. фон Нейман, 1946). Число возводится в квадрат, из середины '
        'квадрата берутся d цифр. Недостаток — последовательность быстро вырождается: попадает в 0 или в '
        'короткий цикл.')
    rows = [('n', 'xₙ', 'xₙ² (2d цифр)', 'середина → xₙ₊₁')]
    x = g.state
    for i in range(steps + 6):
        sq, nxt = g.step(x)
        k = g.digits // 2
        rows.append((i, x, f'{sq[:k]}[{sq[k:k + g.digits]}]{sq[k + g.digits:]}', nxt))
        x = nxt
    d.table(rows, right={0, 1, 3})
    per = P.period_brent(lambda v: g.step(v)[1], g.state)
    d.formula(f'Начиная с {g.state}: через {per.tail} шагов последовательность входит в цикл длины {per.length}',
              BAD if (per.length or 0) < 100 else OK)
    d.p(f'Состояние — одно число из {g.digits} цифр, поэтому различных состояний всего {g.modulus}, и период не '
        f'может быть больше {g.modulus}. На практике он намного короче.', 'muted')


def _lcg(d: Doc, g: G.LCG, steps: int) -> None:
    a, c, m = g.a, g.c, g.modulus
    d.p('Линейный конгруэнтный генератор (Д. Лемер, 1949) — самый распространённый простой датчик: умножить, '
        'прибавить, взять остаток. Состояние — одно число из [0, m), поэтому период не больше m.')
    rows = [('n', 'xₙ', 'a·xₙ + c', 'mod m → xₙ₊₁', 'uₙ₊₁ = xₙ₊₁ / m')]
    x = g.state
    for i in range(steps):
        y = a * x + c
        nxt = y % m
        rows.append((i, x, y, nxt, f'{nxt / m:.4f}'))
        x = nxt
    d.table(rows, right={0, 1, 2, 3})
    d.h2('Максимальный период: теорема Халла–Добелла')
    if c == 0:
        d.p('При c = 0 (мультипликативный датчик) период не может равняться m: ноль переходит в ноль. '
            'Для простого m наибольший период m − 1 достигается, если a — первообразный корень по модулю m '
            '(так у MINSTD: 16807 = 7⁵ — первообразный корень по модулю 2³¹ − 1).')
    for text, ok in P.hull_dobell(a, c, m):
        d.formula(('✓ ' if ok else '✗ ') + text, OK if ok else BAD)
    if m <= 1 << 20:
        per = P.period_brent(lambda v: (a * v + c) % m, g.state)
        d.formula(f'Найденный период (алгоритм Брента): {per.length}', OK if per.length == m else BAD)
    if m & (m - 1) == 0:
        lows = P.lcg_low_bit_period(G.LCG(a, c, m, g.state), 0, 32)
        d.p('При m = 2ᵏ младшие биты плохие: бит номер j повторяется с периодом не больше 2^(j+1). '
            'Младший бит первых чисел: ' + ''.join(map(str, lows)), BAD)
    if (a, c, m) == (65539, 0, 2 ** 31):
        d.p('RANDU: a = 2¹⁶ + 3, поэтому a² = 6a − 9 (mod 2³¹) и xₖ₊₂ = 6xₖ₊₁ − 9xₖ (mod 2³¹). Любая тройка '
            'подряд идущих чисел лежит на одной из 15 плоскостей в кубе — это видно во вкладке «Сравнение».', BAD)


def _lfsr(d: Doc, g: G.LFSR, steps: int) -> None:
    n = g.n
    d.p(f'Регистр сдвига с линейной обратной связью (РСЛОС) из {n} бит. На каждом шаге выдвигается младший бит '
        '(он и есть выход), а слева вдвигается XOR битов-отводов. В терминах ЛР №3: последовательность '
        'удовлетворяет линейному рекуррентному соотношению над GF(2), а его характеристический многочлен — '
        'многочлен обратной связи.')
    rows = [('шаг', 'регистр', 'выход', 'новый бит')]
    s = g.state
    for i in range(min(steps + 6, 16)):
        bit = 0
        for t in g.taps:
            bit ^= s >> (n - t)
        bit &= 1
        rows.append((i, format(s, f'0{n}b'), s & 1, bit))
        s = (s >> 1) | (bit << (n - 1))
    d.table(rows, right={0})
    d.formula(f'Многочлен примитивный ⇒ период 2^{n} − 1 = {2 ** n - 1}', OK)
    lc = P.linear_complexity(G.LFSR(g.taps, g.state).bits(4 * n + 50))
    d.p(f'Слабость: линейная сложность последовательности равна {lc} (= числу ячеек). По 2·{n} = {2 * n} '
        'подряд идущим битам алгоритм Берлекэмпа–Мэсси восстанавливает отводы и предсказывает все дальнейшие '
        'биты. Поэтому РСЛОС в чистом виде не годится для криптографии, хотя статистически хорош.', BAD)


def _xorshift(d: Doc, g: G.Xorshift32, steps: int) -> None:
    d.p('Xorshift (Дж. Марсалья, 2003): состояние — 32-битное слово, шаг — три операции «сдвиг и XOR». Каждая '
        'операция обратима и линейна над GF(2), поэтому весь шаг — умножение вектора из 32 бит на невырожденную '
        'матрицу T. Сдвиги 13, 17, 5 подобраны так, что порядок матрицы равен 2³² − 1 — максимальный период.')
    x = g.state
    for i in range(min(steps, 3)):
        a = x ^ ((x << 13) & 0xFFFFFFFF)
        b = a ^ (a >> 17)
        c = b ^ ((b << 5) & 0xFFFFFFFF)
        d.table([('шаг ' + str(i + 1), 'значение'), ('x', b32(x)), ('x ⊕ (x ≪ 13)', b32(a)),
                 ('… ⊕ (… ≫ 17)', b32(b)), ('… ⊕ (… ≪ 5)', b32(c)), ('десятичное', c)])
        x = c


def _mt(d: Doc, g: G.MT19937, steps: int) -> None:
    d.p('Вихрь Мерсенна (М. Мацумото, Т. Нисимура, 1997) — стандартный датчик Python, MATLAB, R, C++ (std::mt19937). '
        'Состояние — 624 слова по 32 бита (19 968 бит), период 2¹⁹⁹³⁷ − 1 — простое число Мерсенна. '
        'Последовательность равномерно распределена в 623 измерениях.')
    d.h2('Скручивание (twist) — обновление всех 624 слов')
    d.formula('y = (старший бит mt[k]) | (младшие 31 бит mt[k+1])')
    d.formula('mt[k] = mt[k + 397] ⊕ (y ≫ 1) ⊕ (0x9908B0DF, если y нечётное)')
    d.p('Это линейная рекурсия над GF(2), как у РСЛОС, но огромной степени 19937.', 'muted')
    d.h2('Закалка (tempering) — улучшение равномерности выходного слова')
    if g.index >= g.N:
        g.twist()
    y = g.mt[g.index]
    y1 = y ^ (y >> 11)
    y2 = y1 ^ ((y1 << 7) & 0x9D2C5680)
    y3 = y2 ^ ((y2 << 15) & 0xEFC60000)
    y4 = y3 ^ (y3 >> 18)
    d.table([('операция', 'значение'), ('y = mt[i]', b32(y)), ('y ⊕= y ≫ 11', b32(y1)),
             ('y ⊕= (y ≪ 7) & 0x9D2C5680', b32(y2)), ('y ⊕= (y ≪ 15) & 0xEFC60000', b32(y3)),
             ('y ⊕= y ≫ 18', b32(y4)), ('выход', y4)])
    rows = [('n', 'xₙ', 'uₙ')]
    for i in range(1, steps + 1):
        x = g.next()
        rows.append((i, x, f'{x / 2 ** 32:.6f}'))
    d.table(rows, right={0, 1})
    d.p('Проверка: при том же зерне модуль random языка Python выдаёт ровно эти числа (random.getrandbits(32)). '
        'Слабость: по 624 подряд выходам состояние восстанавливается (закалку можно обратить), поэтому вихрь '
        'Мерсенна не криптостойкий.', 'muted')


def _bbs(d: Doc, g: G.BBS, steps: int) -> None:
    d.p('Блюм–Блюм–Шуб (1986): xₙ₊₁ = xₙ² mod M, где M = p·q — произведение двух больших простых, '
        'p ≡ q ≡ 3 (mod 4). На выход идёт младший бит. Предсказать следующий бит по предыдущим так же трудно, '
        'как разложить M на множители, поэтому датчик криптостойкий — но очень медленный.')
    rows = [('n', 'xₙ', 'xₙ₊₁ = xₙ² mod M', 'бит')]
    x = g.state
    for i in range(steps):
        nxt = x * x % g.M
        rows.append((i, x, nxt, nxt & 1))
        x = nxt
    d.table(rows, right={0, 1, 2, 3})
    d.p(f'Здесь p = {g.p}, q = {g.q} — для учебной демонстрации. В криптографии берут p и q по 1024 бита и больше.',
        'muted')


# ==========================================================================
# Тесты
# ==========================================================================

TEST_THEORY = {
    'frequency': 'Единиц и нулей поровну. S = Σ(2εᵢ − 1) ≈ N(0, n) по центральной предельной теореме.',
    'block': 'В каждом блоке из M бит доля единиц близка к 1/2; χ² = 4M·Σ(πᵢ − 1/2)².',
    'runs': 'Серий (участков одинаковых бит) должно быть ≈ 2nπ(1−π): слишком мало — биты «залипают», '
            'слишком много — чередуются.',
    'longest': 'Самая длинная серия единиц в блоке имеет известное распределение; сравнение по χ².',
    'cusum': 'Случайное блуждание ±1 не уходит от нуля дальше ~√n.',
    'apen': 'Все 2- и 3-битные шаблоны встречаются одинаково часто; ApEn ≈ ln 2.',
    'chi2': 'Гистограмма чисел ровная: χ² = Σ(Oᵢ − Eᵢ)²/Eᵢ по k интервалам.',
    'ks': 'Эмпирическая функция распределения близка к прямой F(x) = x; D = max|Fₙ(x) − x|.',
    'serial': 'Пары соседних чисел равномерно заполняют квадрат — числа не зависят от предыдущих.',
    'triples': 'Тройки равномерно заполняют куб — ловит плоскости ЛКГ (RANDU).',
    'poker': 'В «руке» из 5 цифр число разных цифр распределено как в комбинаторике (числа Стирлинга).',
    'autocorr': 'Коэффициент корреляции соседних чисел ≈ 0.',
    'pi': 'Доля точек внутри четверти круга ≈ π/4 — проверка «в деле».',
    'lowbit': 'Младший бит самих чисел не должен быть периодичным (у ЛКГ с m = 2ᵏ он чередуется).',
}


def tests_doc(name: str, results: list[Result], n_numbers: int, n_bits: int) -> Doc:
    d = Doc()
    passed = sum(r.passed for r in results)
    d.h1(f'{name}: пройдено {passed} из {len(results)} тестов')
    nn, nb = f'{n_numbers:,}'.replace(',', ' '), f'{n_bits:,}'.replace(',', ' ')
    d.p(f'Выборка: {nn} чисел и {nb} бит. Уровень значимости α = {ALPHA}: тест не пройден, '
        'если p-значение меньше α.')
    rows = [('Тест', 'p-значение', 'Итог', 'Статистика')]
    marks = {}
    for i, r in enumerate(results, 1):
        rows.append((r.name, f'{r.p_value:.4f}' if r.p_value >= 1e-4 else f'{r.p_value:.1e}',
                     'пройден' if r.passed else 'НЕ пройден', r.statistic))
        marks[i] = OK if r.passed else BAD
    d.table(rows, right={1}, marks=marks)
    d.h2('Что проверяет каждый тест')
    for r in results:
        d.p(f'{r.name}. {TEST_THEORY.get(r.key, "")}' + (f' Детали: {r.details}.' if r.details else ''))
    d.p('Как читать p-значение: если последовательность случайна, p распределено равномерно на [0, 1], и '
        'идеальный генератор «проваливает» каждый тест с вероятностью α = 1 %. Поэтому один провал с p ≈ 0,005 '
        'не страшен, а p ≈ 10⁻¹⁰ или провал сразу нескольких тестов — явный дефект.', 'muted')
    return d
