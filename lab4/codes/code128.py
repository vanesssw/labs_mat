"""Штрих-код Code 128 — любые символы ASCII 32–126 и пары цифр.

Каждый символ — 3 штриха и 3 пробела общей шириной 11 модулей (ширины 1–4). Таблица из 107
символов: 0–102 — данные и служебные коды, 103–105 — старт A/B/C, 106 — стоп (13 модулей).
    набор B: символ ASCII с кодом k записывается значением k − 32;
    набор C: пара цифр 00–99 записывается одним символом — вдвое плотнее для чисел;
    переключение: в наборе B символ 99 = «перейти в C», в наборе C символ 100 = «перейти в B».
Контрольный символ: (старт + Σ i·значениеᵢ) mod 103, где i — номер символа данных с 1.
"""
from __future__ import annotations

from .ean13 import BarcodeError

PATTERNS = [
    '212222', '222122', '222221', '121223', '121322', '131222', '122213', '122312', '132212', '221213',
    '221312', '231212', '112232', '122132', '122231', '113222', '123122', '123221', '223211', '221132',
    '221231', '213212', '223112', '312131', '311222', '321122', '321221', '312212', '322112', '322211',
    '212123', '212321', '232121', '111323', '131123', '131321', '112313', '132113', '132311', '211313',
    '231113', '231311', '112133', '112331', '132131', '113123', '113321', '133121', '313121', '211331',
    '231131', '213113', '213311', '213131', '311123', '311321', '331121', '312113', '312311', '332111',
    '314111', '221411', '431111', '111224', '111422', '121124', '121421', '141122', '141221', '112214',
    '112412', '122114', '122411', '142112', '142211', '241211', '221114', '413111', '241112', '134111',
    '111242', '121142', '121241', '114212', '124112', '124211', '411212', '421112', '421211', '212141',
    '214121', '412121', '111143', '111341', '131141', '114113', '114311', '411113', '411311', '113141',
    '114131', '311141', '411131', '211412', '211214', '211232', '2331112',
]
START_B, START_C, STOP = 104, 105, 106
CODE_B, CODE_C = 100, 99
QUIET = 10


def widths_to_modules(widths: str) -> str:
    """'212222' → '11011001100': штрих, пробел, штрих… заданной ширины."""
    return ''.join(('1' if i % 2 == 0 else '0') * int(w) for i, w in enumerate(widths))


def symbols(text: str) -> list[tuple[int, str]]:
    """Значения символов с пояснениями: [(значение, пояснение)], без контрольного и стопа."""
    if not text or any(not 32 <= ord(ch) <= 126 for ch in text):
        raise BarcodeError('Code 128: допустимы только символы ASCII с кодами 32–126 (латиница, цифры, знаки)')
    out = []

    def digit_run(i):
        j = i
        while j < len(text) and text[j].isdigit():
            j += 1
        return j - i

    i = 0
    run = digit_run(0)
    if run >= 4 and run % 2 == 0 or run == len(text) and run >= 2 and run % 2 == 0:
        out.append((START_C, 'старт C'))
        mode = 'C'
    else:
        out.append((START_B, 'старт B'))
        mode = 'B'
    while i < len(text):
        run = digit_run(i)
        if mode == 'B' and run >= 4:
            if run % 2:                      # нечётную цифру оставляем в наборе B
                out.append((ord(text[i]) - 32, f'{text[i]!r} (B)'))
                i += 1
                run -= 1
            out.append((CODE_C, 'переход в C'))
            mode = 'C'
        if mode == 'C':
            if run >= 2:
                out.append((int(text[i:i + 2]), f'{text[i:i + 2]} (C)'))
                i += 2
                continue
            out.append((CODE_B, 'переход в B'))
            mode = 'B'
        out.append((ord(text[i]) - 32, f'{text[i]!r} (B)'))
        i += 1
    return out


def checksum(values: list[int]) -> int:
    return (values[0] + sum(i * v for i, v in enumerate(values[1:], 1))) % 103


def encode(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Модули и разбор [(пояснение, модули)]."""
    syms = symbols(text)
    values = [v for v, _ in syms]
    check = checksum(values)
    parts = [(f'{label} = {v}', widths_to_modules(PATTERNS[v])) for v, label in syms]
    parts.append((f'контрольный = {check}', widths_to_modules(PATTERNS[check])))
    parts.append(('стоп', widths_to_modules(PATTERNS[STOP])))
    return ''.join(m for _, m in parts), parts


def _closest(widths: list[float], count: int) -> tuple[int, float]:
    total = sum(widths)
    modules = 13 if count == 7 else 11
    norm = [w * modules / total for w in widths]
    best = (-1, 1e9)
    for v, pat in enumerate(PATTERNS):
        if len(pat) != count:
            continue
        err = sum(abs(a - int(b)) for a, b in zip(norm, pat))
        if err < best[1]:
            best = (v, err)
    return best


def decode_runs(runs: list[float]) -> str:
    """Расшифровать ширины штрихов и пробелов, начиная со стартового символа."""
    values = []
    k = 0
    while k + 6 <= len(runs):
        if len(values) >= 2 and k + 7 <= len(runs):
            v7, e7 = _closest(runs[k:k + 7], 7)
            if v7 == STOP and e7 < 1.5:
                break
        v, err = _closest(runs[k:k + 6], 6)
        if err > 2.0:
            raise BarcodeError('символ не распознан')
        values.append(v)
        k += 6
    else:
        raise BarcodeError('не найден стоп-символ')
    if len(values) < 2 or values[0] not in (START_B, START_C, 103):
        raise BarcodeError('не найден стартовый символ')
    if checksum(values[:-1]) != values[-1]:
        raise BarcodeError('контрольный символ не сошёлся')
    mode = 'C' if values[0] == START_C else 'B'
    out = ''
    for v in values[1:-1]:
        if mode == 'B' and v == CODE_C:
            mode = 'C'
        elif mode == 'C' and v == CODE_B:
            mode = 'B'
        elif mode == 'C':
            out += f'{v:02d}'
        else:
            out += chr(v + 32)
    return out
