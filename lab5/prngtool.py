"""ЛР №5 — генераторы псевдослучайных чисел из командной строки.

Примеры (из папки lab5):
    python prngtool.py list                         список датчиков
    python prngtool.py gen mt -n 10 --seed 42       первые 10 чисел вихря Мерсенна
    python prngtool.py explain randu                как работает датчик, первые шаги
    python prngtool.py test randu                   14 тестов качества для RANDU
    python prngtool.py test mt --big                то же на выборке как в NIST (10⁵ чисел, 10⁶ бит)
    python prngtool.py compare                      все датчики через одни и те же тесты
    python prngtool.py lcg 13 7 64 --seed 1         свой ЛКГ: a c m
"""
from __future__ import annotations

import argparse
import sys

from prng import explain, properties
from prng import generators as G
from prng import stat_tests as st


def sizes(a) -> tuple[int, int]:
    return (100_000, 1_000_000) if a.big else (20_000, 200_000)


def cmd_list(a) -> None:
    for key, name in G.CATALOG.items():
        print(f'{key:10} {name}')


def cmd_gen(a) -> None:
    g = G.make(a.key, a.seed)
    for i in range(a.n):
        x = g.next()
        print(f'{i + 1:4}  {x:12}  {x / g.modulus:.8f}')


def cmd_explain(a) -> None:
    print(explain.generator_doc(G.make(a.key, a.seed)).plain())


def cmd_test(a) -> None:
    g = G.make(a.key, a.seed)
    n_num, n_bits = sizes(a)
    print(explain.tests_doc(g.name, st.run_battery(g, n_num, n_bits), n_num, n_bits).plain())


def cmd_lcg(a) -> None:
    g = G.LCG(a.a, a.c, a.m, a.seed)
    print(explain.generator_doc(G.LCG(a.a, a.c, a.m, a.seed)).plain())
    n_num, n_bits = sizes(a)
    print(explain.tests_doc(g.name, st.run_battery(g, n_num, n_bits), n_num, n_bits).plain())


def cmd_compare(a) -> None:
    n_num, n_bits = sizes(a)
    print(f'Выборка: {n_num} чисел и {n_bits} бит, α = {st.ALPHA}')
    for key, name in G.CATALOG.items():
        res = st.run_battery(G.make(key, a.seed), n_num, n_bits)
        lc = properties.linear_complexity(G.make(key, a.seed).bits(400))
        marks = ''.join('+' if r.passed else '-' for r in res)
        print(f'{name:34} {marks}  {sum(r.passed for r in res):2}/{len(res)}  лин. сложность {lc}')


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='ЛР №5: генераторы псевдослучайных чисел')
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list', help='список датчиков').set_defaults(func=cmd_list)
    for name, func, hlp in (('gen', cmd_gen, 'вывести числа'), ('explain', cmd_explain, 'как работает датчик'),
                            ('test', cmd_test, 'тесты качества')):
        p = sub.add_parser(name, help=hlp)
        p.add_argument('key', choices=list(G.CATALOG))
        p.add_argument('--seed', type=int, default=12345)
        p.add_argument('-n', type=int, default=20)
        p.add_argument('--big', action='store_true', help='выборка как в NIST')
        p.set_defaults(func=func)
    p = sub.add_parser('lcg', help='свой ЛКГ')
    for x in 'acm':
        p.add_argument(x, type=int)
    p.add_argument('--seed', type=int, default=1)
    p.add_argument('--big', action='store_true')
    p.set_defaults(func=cmd_lcg)
    p = sub.add_parser('compare', help='сравнить все датчики')
    p.add_argument('--seed', type=int, default=12345)
    p.add_argument('--big', action='store_true')
    p.set_defaults(func=cmd_compare)
    a = parser.parse_args(argv)
    try:
        a.func(a)
    except ValueError as e:
        print(f'Ошибка: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
