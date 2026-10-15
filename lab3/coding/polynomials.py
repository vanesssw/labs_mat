"""Двоичные многочлены — язык циклических кодов.

Кодовая комбинация записывается как многочлен: разряды — коэффициенты при степенях x,
старшая степень слева. Например, 100101 = 1·x⁵ + 0·x⁴ + 0·x³ + 1·x² + 0·x + 1 = x⁵ + x² + 1.

Коэффициенты складываются по модулю 2, поэтому:
    * сложение и вычитание многочленов — одно и то же (поразрядный XOR);
    * деление «столбиком» — это сдвиги делителя и XOR, без переносов и заёмов.

Многочлен хранится как список коэффициентов от старшей степени к младшей: [1, 0, 0, 1, 0, 1].
"""
from __future__ import annotations

from .gf2 import to_str

SUPERSCRIPT = str.maketrans('0123456789', '⁰¹²³⁴⁵⁶⁷⁸⁹')


def trim(p) -> list[int]:
    """Убрать старшие нулевые коэффициенты: 000101 → 101. Нулевой многочлен → [0]."""
    p = list(p)
    while len(p) > 1 and p[0] == 0:
        p.pop(0)
    return p or [0]


def degree(p) -> int:
    """Степень многочлена — старшая степень x с ненулевым коэффициентом (у нуля −1)."""
    p = trim(p)
    return len(p) - 1 if p[0] else -1


def monomial(m: int) -> list[int]:
    """Одночлен x^m = 1 и m нулей."""
    return [1] + [0] * m


def power_str(m: int, var: str = 'x') -> str:
    """x^m в виде текста: 1, x, x², x¹³."""
    if m == 0:
        return '1'
    return var if m == 1 else var + str(m).translate(SUPERSCRIPT)


def poly_str(p, var: str = 'x') -> str:
    """[1, 0, 0, 1, 0, 1] → 'x⁵ + x² + 1'."""
    p = list(p)
    n = len(p)
    terms = [power_str(n - 1 - i, var) for i, c in enumerate(p) if c]
    return ' + '.join(terms) if terms else '0'


def add(a, b) -> list[int]:
    """Сумма (она же разность) многочленов: XOR коэффициентов при одинаковых степенях."""
    n = max(len(a), len(b))
    a = [0] * (n - len(a)) + list(a)
    b = [0] * (n - len(b)) + list(b)
    return [x ^ y for x, y in zip(a, b)]


def mul(a, b) -> list[int]:
    """Произведение многочленов: сумма сдвинутых копий a для каждой единицы в b."""
    a, b = trim(a), trim(b)
    out = [0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        if x:
            for j, y in enumerate(b):
                out[i + j] ^= y
    return out


def divide(a, g) -> tuple[list[int], list[int]]:
    """Деление с остатком: a(x) = q(x)·g(x) + R(x), где степень R меньше степени g.

    Возвращает (частное, остаток). Остаток всегда содержит deg g разрядов
    (со старшими нулями) — столько же, сколько контрольных разрядов в коде.
    """
    g = trim(g)
    m = len(g)
    if m == 1 and g[0] == 0:
        raise ZeroDivisionError('деление на нулевой многочлен')
    cur = list(a)
    if len(cur) < m:
        cur = [0] * (m - len(cur)) + cur
    q = [0] * (len(cur) - m + 1)
    for i in range(len(cur) - m + 1):
        if cur[i]:
            q[i] = 1
            for j in range(m):
                cur[i + j] ^= g[j]
    return trim(q), cur[len(cur) - (m - 1):] if m > 1 else []


def mod(a, g) -> list[int]:
    """Остаток от деления a(x) на g(x) (deg g разрядов)."""
    return divide(a, g)[1]


def long_division(a, g) -> list[tuple[str, str]]:
    """Деление «столбиком» для показа: список строк (моноширинная часть, пояснение).

    На каждом шаге под старшей единицей текущего остатка подписывается делитель
    и выполняется XOR — это вычитание g(x)·x^p. Старшие нули заменяются пробелами,
    все оставшиеся разряды «сносятся» сразу.
    """
    g = trim(g)
    m, n = len(g), len(a)
    cur = list(a)
    lines = [('  ' + to_str(cur), 'делимое')]
    for i in range(n - m + 1):
        if not cur[i]:
            continue
        lines.append(('+ ' + ' ' * i + to_str(g), f'K(x)·{power_str(n - m - i)}'))
        lines.append(('  ' + ' ' * i + '-' * m, ''))
        for j in range(m):
            cur[i + j] ^= g[j]
        keep = n - (m - 1)              # младшие m − 1 разрядов показываем всегда (это остаток)
        first = next((t for t in range(n) if cur[t]), n)
        lines.append(('  ' + ''.join(' ' if t < min(first, keep) else str(cur[t]) for t in range(n)), ''))
    rem = cur[n - (m - 1):] if n >= m else [0] * (m - 1 - n) + cur
    lines[-1] = (lines[-1][0], f'остаток R = {to_str(rem)}')
    return lines


def is_irreducible(g) -> bool:
    """Неприводимый многочлен не раскладывается в произведение многочленов меньшей степени.

    Проверка перебором: делим на все многочлены степени от 1 до deg/2.
    """
    g = trim(g)
    d = degree(g)
    if d < 1:
        return False
    for dd in range(1, d // 2 + 1):
        for low in range(1 << dd):
            divisor = [1] + [int(b) for b in format(low, f'0{dd}b')]
            if not any(mod(g, divisor)):
                return False
    return True


def factorize(g) -> list[list[int]]:
    """Разложение на неприводимые множители (перебором делителей по возрастанию степени)."""
    g = trim(g)
    factors = []
    dd = 1
    while degree(g) >= 2 * dd:
        found = False
        for low in range(1 << dd):
            divisor = [1] + [int(b) for b in format(low, f'0{dd}b')]
            q, r = divide(g, divisor)
            if not any(r):
                factors.append(divisor)
                g = q
                found = True
                break
        if not found:
            dd += 1
    if degree(g) >= 1:
        factors.append(g)
    return factors


def period(g) -> int | None:
    """Период (порядок) многочлена: наименьшее e, при котором g(x) делит x^e + 1.

    Циклический код длины n с образующим многочленом g существует, только если g делит xⁿ + 1,
    то есть n кратно периоду. У g с нулевым свободным членом периода нет (None).
    """
    g = trim(g)
    d = degree(g)
    if d < 1 or g[-1] == 0:
        return None
    one = [0] * (d - 1) + [1]
    cur = one
    for e in range(1, 1 << d):
        cur = mod(cur + [0], g)          # умножение остатка на x и новое деление
        if cur == one:
            return e
    return None
