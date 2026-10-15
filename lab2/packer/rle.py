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
