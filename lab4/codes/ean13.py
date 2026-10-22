"""Штрих-код EAN-13 — 13 цифр товарного кода (12 значащих + контрольная).

Строение (95 модулей шириной в 1 «элементарный штрих»):
    101        — левый ограничитель;
    6 цифр     — левая половина, каждая цифра 7 модулей набором L или G;
    01010      — центральный ограничитель;
    6 цифр     — правая половина, набор R;
    101        — правый ограничитель.
Первая цифра не рисуется штрихами: она задаётся тем, какие цифры левой половины записаны
набором L, а какие G (таблица чётности). R — инверсия L, G — R, записанный задом наперёд.
У L и G (слева) нечётное и чётное число тёмных модулей соответственно, поэтому сканер
понимает и направление чтения, и первую цифру.

Контрольная цифра: сумма цифр на нечётных местах ×1 + на чётных ×3; контрольная дополняет
сумму до кратного 10. Ловит любую ошибку в одной цифре и почти все перестановки соседних.
"""
from __future__ import annotations

L_CODES = ['0001101', '0011001', '0010011', '0111101', '0100011',
           '0110001', '0101111', '0111011', '0110111', '0001011']
R_CODES = [''.join('1' if b == '0' else '0' for b in code) for code in L_CODES]
G_CODES = [code[::-1] for code in R_CODES]
PARITY = ['LLLLLL', 'LLGLGG', 'LLGGLG', 'LLGGGL', 'LGLLGG', 'LGGLLG', 'LGGGLL', 'LGLGLG', 'LGLGGL', 'LGGLGL']
START = END = '101'
CENTER = '01010'
QUIET_LEFT, QUIET_RIGHT = 11, 7       # светлые поля в модулях


class BarcodeError(ValueError):
    pass


def check_digit(digits12: str) -> int:
    """Контрольная цифра по весам 1, 3, 1, 3, …"""
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(digits12))
    return (10 - total % 10) % 10


def normalize(code: str) -> str:
    """12 цифр → добавить контрольную; 13 цифр → проверить контрольную."""
    code = code.strip().replace(' ', '')
    if not code.isdigit() or len(code) not in (12, 13):
        raise BarcodeError('EAN-13: нужно 12 или 13 цифр')
    if len(code) == 12:
        return code + str(check_digit(code))
    if int(code[12]) != check_digit(code[:12]):
        raise BarcodeError(f'EAN-13: неверная контрольная цифра {code[12]}, должна быть {check_digit(code[:12])}')
    return code


def encode(code: str) -> tuple[str, list[tuple[str, str]]]:
    """Последовательность модулей ('1' — штрих) и разбор по частям [(пояснение, модули)]."""
    code = normalize(code)
    parity = PARITY[int(code[0])]
    parts = [('левый ограничитель', START)]
    for d, p in zip(code[1:7], parity):
        parts.append((f'{d} ({p})', (L_CODES if p == 'L' else G_CODES)[int(d)]))
    parts.append(('центральный ограничитель', CENTER))
    for d in code[7:]:
        parts.append((f'{d} (R)', R_CODES[int(d)]))
    parts.append(('правый ограничитель', END))
    return ''.join(m for _, m in parts), parts


def _match(widths: list[float], table: list[str]) -> tuple[int, float]:
    """Ближайший по ширинам штрихов символ таблицы: (цифра, ошибка)."""
    total = sum(widths)
    norm = [w * 7 / total for w in widths]
    best = (-1, 1e9)
    for digit, code in enumerate(table):
        runs, cur = [], 1
        for a, b in zip(code, code[1:]):
            if a == b:
                cur += 1
            else:
                runs.append(cur)
                cur = 1
        runs.append(cur)
        if len(runs) != 4:
            continue
        err = sum(abs(a - b) for a, b in zip(norm, runs))
        if err < best[1]:
            best = (digit, err)
    return best


def decode_runs(runs: list[float]) -> str:
    """Расшифровать 59 ширин (штрих, пробел, штрих, …), начиная с левого ограничителя."""
    if len(runs) < 59:
        raise BarcodeError('мало штрихов')
    runs = runs[:59]
    left, right = runs[3:27], runs[32:56]
    digits, parity = '', ''
    for k in range(6):
        w = left[4 * k:4 * k + 4]           # левая половина начинается с пробела
        dl, el = _match(w, L_CODES)
        dg, eg = _match(w, G_CODES)
        digits += str(dl if el <= eg else dg)
        parity += 'L' if el <= eg else 'G'
    if parity not in PARITY:
        raise BarcodeError('нет такой схемы чётности L/G — штрих-код прочитан с ошибкой')
    first = PARITY.index(parity)
    for k in range(6):
        d, err = _match(right[4 * k:4 * k + 4], R_CODES)
        digits += str(d)
    code = str(first) + digits
    if int(code[12]) != check_digit(code[:12]):
        raise BarcodeError('контрольная цифра не сошлась')
    return code
