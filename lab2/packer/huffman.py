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
