"""Архиватор ЛР №2 — запуск из командной строки.

Примеры (из папки lab2):
    python archiver.py compress   test_files\\01_text_ru_cp1251.txt -m huffman
    python archiver.py decompress test_files\\01_text_ru_cp1251.txt.lab2
    python archiver.py info       test_files\\01_text_ru_cp1251.txt
    python archiver.py bench      test_files

Короткие формы команд: c (compress), x (decompress), i (info), b (bench).
Методы (-m): rle, huffman, shannon, lzw, auto (попробовать все и выбрать лучший).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from packer import container, huffman, shannon_fano, stats
from packer.fmt import human, num, pct
from packer.methods import AUTO, METHODS


def cmd_compress(args) -> None:
    for src in args.files:
        target = args.output if len(args.files) == 1 else None
        r = container.compress_file(src, target, args.method)
        verdict = 'сжатие' if r.archive_size < r.original_size else 'РАСШИРЕНИЕ'
        print(f'{r.source.name}: {human(r.original_size)} Б → {r.target.name}: '
              f'{human(r.archive_size)} Б ({pct(r.percent)} от исходного, k = {num(r.ratio)}, {verdict}); '
              f'метод: {r.method.title}; время {num(r.seconds)} с')


def cmd_decompress(args) -> None:
    for src in args.files:
        target = args.output if len(args.files) == 1 else None
        r = container.decompress_file(src, target)
        print(f'{r.source.name} → {r.target.name}: {human(r.original_size)} Б; метод: {r.method.title}; '
              f'CRC-32 совпала — данные восстановлены без потерь; время {num(r.seconds)} с')


def cmd_info(args) -> None:
    for src in args.files:
        data = Path(src).read_bytes()
        p = stats.profile(data)
        freqs = stats.frequencies(data)
        print(f'Файл: {src}')
        print(f'  размер n = {human(p.size)} Б, различных байтов N = {p.distinct}')
        print(f'  энтропия H0 = {num(p.entropy, 4)} бит/байт, Hmax = log2 N = {num(p.max_entropy, 4)}, '
              f'избыточность R = {num(stats.redundancy(freqs), 4)}')
        print(f'  энтропия с учётом предыдущего байта H1 = {num(p.cond_entropy, 4)} бит/байт')
        if not data:
            print('  файл пустой — сжимать нечего\n')
            continue
        print(f'  предел для посимвольного кодирования n·H0/8 = {human(p.limit_bytes)} Б '
              f'({pct(stats.percent(p.size, p.limit_bytes))})')
        for title, builder in (('Хаффман', huffman), ('Шеннон–Фано', shannon_fano)):
            q = stats.code_quality(freqs, builder.code_lengths(freqs))
            print(f'  {title:12}: lср = {num(q.avg_length, 4)} бит/байт, Kсс = Hmax/lср = {num(q.k_cc, 4)}, '
                  f'Kоэ = H/lср = {num(q.k_oe, 4)}')
        print()


def collect_files(paths: list[str]) -> list[Path]:
    files = []
    for path in map(Path, paths):
        if path.is_dir():
            files += sorted(f for f in path.iterdir() if f.is_file())
        else:
            files.append(path)
    return files


def cmd_bench(args) -> None:
    files = collect_files(args.paths)
    methods = list(METHODS.values())
    head = f'{"Файл":28} {"Размер, Б":>11} {"H0":>6} ' + ' '.join(f'{m.title:>12}' for m in methods)
    print(head)
    print('-' * len(head))
    for f in files:
        data = f.read_bytes()
        rows = container.benchmark(data, f.name)
        cells = []
        for row in rows:
            mark = '' if row.ok else ' ОШИБКА'
            cells.append(f'{pct(stats.percent(len(data), row.archive_size)) + mark:>12}' if data
                         else f'{human(row.archive_size) + " Б":>12}')
        print(f'{f.name[:28]:28} {human(len(data)):>11} {num(stats.profile(data).entropy):>6} ' + ' '.join(cells))
    print('\nВ ячейках — размер архива в % от исходного файла (меньше 100 % — сжатие, больше — расширение).')


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(
        prog='archiver.py',
        description='Архиватор ЛР №2: RLE, Хаффман, Шеннон–Фано, LZW. Сжатие без потерь.')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('compress', aliases=['c'], help='сжать файл(ы) → <имя>.lab2')
    p.add_argument('files', nargs='+', help='файлы для сжатия')
    p.add_argument('-m', '--method', choices=[*METHODS, AUTO], default='huffman',
                   help='метод сжатия (по умолчанию huffman)')
    p.add_argument('-o', '--output', help='имя архива (только для одного файла)')
    p.set_defaults(func=cmd_compress)

    p = sub.add_parser('decompress', aliases=['x'], help='распаковать архив(ы) .lab2')
    p.add_argument('files', nargs='+', help='архивы .lab2')
    p.add_argument('-o', '--output', help='имя распакованного файла (только для одного архива)')
    p.set_defaults(func=cmd_decompress)

    p = sub.add_parser('info', aliases=['i'], help='энтропия и статистика файла')
    p.add_argument('files', nargs='+')
    p.set_defaults(func=cmd_info)

    p = sub.add_parser('bench', aliases=['b'], help='сравнить все методы на файлах/папках')
    p.add_argument('paths', nargs='+', help='файлы или папки')
    p.set_defaults(func=cmd_bench)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (OSError, container.ArchiveError) as e:
        print(f'Ошибка: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
