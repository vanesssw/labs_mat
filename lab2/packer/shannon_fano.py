"""Метод Шеннона–Фано (как в ЛР №1).

  1) символы выписываются в порядке убывания частот (вероятностей);
  2) список делится на две группы так, чтобы суммарные частоты групп
     были как можно ближе друг к другу;
  3) верхней группе приписывается 0, нижней — 1;
  4) каждая группа снова делится по тому же правилу, пока в каждой
     не останется по одному символу.

Дерево строится СВЕРХУ ВНИЗ (от всего алфавита к отдельным символам).
Код тоже префиксный, но не всегда оптимальный: жадное деление пополам
иногда даёт среднюю длину чуть больше, чем у Хаффмана.
"""
from __future__ import annotations

from . import prefix_code
from .prefix_code import Node, tree_codes
from .stats import frequencies


def split_index(group: list[tuple[object, int]]) -> int:
    """Где разрезать список (уже отсортированный по убыванию частот),
    чтобы суммы частот верхней и нижней частей различались меньше всего."""
    total = sum(f for _, f in group)
    best_k, best_diff = 1, None
    upper_sum = 0
    for k in range(1, len(group)):
        upper_sum += group[k - 1][1]
        diff = abs(total - 2 * upper_sum)  # |верхняя сумма − нижняя сумма|
        if best_diff is None or diff < best_diff:
            best_k, best_diff = k, diff
    return best_k


def build_tree(freqs: dict) -> tuple[Node | None, list[tuple[list, list]]]:
    """Построить дерево Шеннона–Фано.

    Возвращает корень и список шагов-делений (верхняя группа, нижняя группа);
    группа — список пар (символ, частота).
    """
    items = sorted(((s, f) for s, f in freqs.items() if f > 0), key=lambda sf: (-sf[1], sf[0]))
    steps = []

    def build(group):
        if len(group) == 1:
            sym, f = group[0]
            return Node(f, sym)
        k = split_index(group)
        upper, lower = group[:k], group[k:]
        steps.append((upper, lower))
        return Node(sum(f for _, f in group), left=build(upper), right=build(lower))

    return (build(items) if items else None), steps


def code_lengths(freqs: dict) -> dict:
    root, _ = build_tree(freqs)
    return {s: len(code) for s, code in tree_codes(root).items()}


def compress(data: bytes) -> bytes:
    return prefix_code.compress(data, code_lengths(frequencies(data)))


def decompress(payload: bytes, original_size: int) -> bytes:
    # Распаковщику нужны только длины кодов, поэтому он тот же, что у Хаффмана.
    return prefix_code.decompress(payload, original_size)
