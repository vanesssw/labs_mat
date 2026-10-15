"""Решение заданий ЛР №3 в командной строке (тот же текст, что во вкладках программы).

Примеры (из папки lab3):
    python solve.py                      все три задания для своего варианта (№ 1, «Группа 1»)
    python solve.py -n 7 -g 2            вариант 7, «Группа 2»
    python solve.py -t 3                 только задание 3
    python solve.py -t 2 -M 18 -s 3      задание 2 для кода, исправляющего трёхкратные ошибки
    python solve.py -o решение.txt       сохранить решение в файл
"""
from __future__ import annotations

import argparse
import sys

from coding import explain
from coding import variants as V
from coding.cyclic_code import CyclicCode
from coding.gf2 import bits
from coding.group_code import GroupCode


def build(args) -> list[explain.Doc]:
    t = V.table_variant(args.number)
    docs = []
    if args.task in (0, 1):
        code = GroupCode.from_variant(V.check_part(args.number), args.group)
        info, w1, w2 = V.GROUP_TASKS[t]
        docs.append(explain.task1(code, bits(info), [bits(w1), bits(w2)],
                                  f'Задание 1. Групповой код (9,5) — табл. 2.1 вариант {args.number}, '
                                  f'«Группа {args.group}», табл. 2.2 вариант {t}'))
    if args.task in (0, 2):
        docs.append(explain.task2(M=args.M, s=args.s))
    if args.task in (0, 3):
        g, info, word = V.CYCLIC_TASKS[t]
        code = CyclicCode(bits(g), len(word))
        docs.append(explain.task3(code, bits(info), bits(word),
                                  f'Задание 3. Циклический код ({code.n},{code.k}) — табл. 2.3 вариант {t}'))
    return docs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='ЛР №3: помехоустойчивое кодирование — пошаговые решения')
    parser.add_argument('-n', '--number', type=int, default=V.MY_NUMBER, choices=range(1, 19), metavar='1..18',
                        help='номер в журнале = вариант табл. 2.1 (табл. 2.2 и 2.3 — по последней цифре)')
    parser.add_argument('-g', '--group', type=int, default=V.MY_GROUP, choices=(1, 2),
                        help='1 — единичная информационная часть, 2 — обратная диагональ')
    parser.add_argument('-t', '--task', type=int, default=0, choices=(0, 1, 2, 3), help='номер задания (0 — все)')
    parser.add_argument('-M', type=int, default=18, help='задание 2: число кодовых комбинаций')
    parser.add_argument('-s', type=int, default=2, help='задание 2: кратность исправляемых ошибок')
    parser.add_argument('-o', '--output', help='записать решение в текстовый файл (UTF-8)')
    args = parser.parse_args(argv)

    text = '\n'.join(d.plain() for d in build(args))
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f'Решение записано в {args.output}')
    else:
        print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
