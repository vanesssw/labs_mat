"""Двоичный симметричный канал (ДСК) и передача текста помехоустойчивым кодом.

Модель канала: каждый переданный бит независимо от других искажается (0 ↔ 1)
с вероятностью p и доходит правильно с вероятностью 1 − p.

Вероятность, что в блоке из n бит произойдёт ровно i ошибок (формула Бернулли):
    P(i) = C(n, i) · p^i · (1 − p)^(n − i).
Код, исправляющий s ошибок, ошибается только при i > s:
    P(блок не исправлен) = 1 − Σ P(i), i = 0 … s.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from math import comb

from .gf2 import xor


def text_to_bits(text: str) -> list[int]:
    """Текст → байты UTF-8 → биты (старший бит каждого байта первым)."""
    return [(byte >> (7 - i)) & 1 for byte in text.encode('utf-8') for i in range(8)]


def bits_to_text(bits) -> str:
    """Биты → байты → текст UTF-8 (испорченные байты заменяются знаком �)."""
    data = bytes(int(''.join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits) - 7, 8))
    return data.decode('utf-8', errors='replace')


def noise(bits, p: float, rng: random.Random) -> tuple[list[int], list[int]]:
    """Пропустить биты через ДСК: (принятые биты, номера искажённых битов с 0)."""
    flips = [i for i in range(len(bits)) if rng.random() < p]
    out = list(bits)
    for i in flips:
        out[i] ^= 1
    return out, flips


def block_failure_probability(n: int, s: int, p: float) -> float:
    """Вероятность, что в блоке из n бит больше s ошибок (код с s исправляемыми их не исправит)."""
    return 1 - sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(s + 1))


@dataclass
class Transmission:
    """Итог передачи текста через канал."""
    code_name: str
    n: int
    k: int
    p: float
    message_bits: int                   # битов полезной информации
    channel_bits: int                   # битов передано по каналу (с контрольными)
    channel_errors: int                 # сколько битов исказил канал
    blocks: int = 0
    by_errors: dict[int, int] = field(default_factory=dict)  # число ошибок в блоке → сколько таких блоков
    clean: int = 0                      # блоки без ошибок
    corrected: int = 0                  # ошибки были и исправлены верно
    detected: int = 0                   # ошибка обнаружена, но не исправлена
    wrong: int = 0                      # декодер «исправил» неверно или не заметил ошибку
    residual_errors: int = 0            # ошибочных информационных битов после декодирования
    text: str = ''                      # принятый текст после декодирования
    detected_bits: set[int] = field(default_factory=set)  # номера информационных битов в «обнаруженных» блоках


def simulate_blocks(code, p: float, blocks: int = 5000, seed: int = 1) -> dict[str, int]:
    """Статистический опыт: передать blocks случайных блоков и посчитать исходы декодирования.

    Возвращает {'clean', 'corrected', 'detected', 'wrong'} — сколько блоков дошли без ошибок,
    исправлены, только обнаружены, декодированы неверно. Доля detected + wrong — опытная
    вероятность того, что блок не исправлен; её можно сравнить с block_failure_probability.
    """
    rng = random.Random(seed)
    out = {'clean': 0, 'corrected': 0, 'detected': 0, 'wrong': 0}
    for _ in range(blocks):
        info = [rng.randint(0, 1) for _ in range(code.k)]
        word = code.encode(info)
        got, flips = noise(word, p, rng)
        if not flips:
            out['clean'] += 1
            continue
        dec = code.decode(got)
        if dec.status == 'detected':
            out['detected'] += 1
        elif dec.info == info:
            out['corrected'] += 1
        else:
            out['wrong'] += 1
    return out


def transmit(text: str, code, p: float, seed: int = 1) -> Transmission:
    """Передать текст: разбить на блоки по k бит, закодировать, исказить, декодировать.

    code = None — передача без помехоустойчивого кодирования (для сравнения).
    """
    rng = random.Random(seed)
    msg = text_to_bits(text)
    if code is None:
        received, flips = noise(msg, p, rng)
        return Transmission('без кодирования', 1, 1, p, len(msg), len(msg), len(flips),
                            residual_errors=len(flips), text=bits_to_text(received))
    k, n = code.k, code.n
    padded = msg + [0] * (-len(msg) % k)
    res = Transmission(code.name, n, k, p, len(msg), 0, 0)
    out: list[int] = []
    for start in range(0, len(padded), k):
        info = padded[start:start + k]
        word = code.encode(info)
        got, flips = noise(word, p, rng)
        dec = code.decode(got)
        res.blocks += 1
        res.channel_bits += n
        res.channel_errors += len(flips)
        res.by_errors[len(flips)] = res.by_errors.get(len(flips), 0) + 1
        if not flips:
            res.clean += 1
        elif dec.status == 'detected':
            res.detected += 1
            res.detected_bits.update(range(start, start + k))
        elif dec.info == info:
            res.corrected += 1
        else:
            res.wrong += 1
        res.residual_errors += sum(xor(dec.info, info)[:max(0, min(k, len(msg) - start))])
        out += dec.info
    res.text = bits_to_text(out[:len(msg)])
    return res
