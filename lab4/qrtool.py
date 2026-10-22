"""ЛР №4 — QR-коды и штрих-коды из командной строки.

Примеры (из папки lab4):
    python qrtool.py qr "Привет, мир!" -l H -o qr.png      построить QR-код (уровень L, M, Q, H)
    python qrtool.py qr "HELLO WORLD" -l Q --explain        с пошаговым объяснением построения
    python qrtool.py ean13 460123456789 -o ean.png          штрих-код EAN-13 (контрольная цифра вычисляется)
    python qrtool.py code128 "LAB4 2026" -o c128.png        штрих-код Code 128
    python qrtool.py scan qr.png                            прочитать QR-код или штрих-код с картинки
    python qrtool.py damage qr.png blot 0.2 -o bad.png      испортить картинку (виды — см. --help)
    python qrtool.py experiment "текст" blot                серия опытов для уровней L, M, Q, H
"""
from __future__ import annotations

import argparse
import sys

from PIL import Image

from codes import analysis, code128, damage, ean13, explain, imaging
from codes.qr_encode import QRError, make_qr


def cmd_qr(a) -> None:
    q = make_qr(a.text, a.level, version=a.version, mask=a.mask)
    print(f'Версия {q.version} ({q.size}×{q.size}), уровень {q.level}, маска {q.mask}, режим {q.mode}')
    if a.explain:
        print(explain.qr_doc(q).plain())
    if a.output:
        imaging.render_qr(q.modules, scale=a.scale).save(a.output)
        print(f'Сохранено: {a.output}')


def cmd_ean13(a) -> None:
    full = ean13.normalize(a.digits)
    mods, _ = ean13.encode(full)
    print(f'EAN-13: {full}')
    if a.explain:
        print(explain.ean13_doc(full).plain())
    if a.output:
        imaging.render_barcode(mods, full, guards=imaging.ean13_guards()).save(a.output)
        print(f'Сохранено: {a.output}')


def cmd_code128(a) -> None:
    mods, _ = code128.encode(a.text)
    print(f'Code 128: {len(mods)} модулей')
    if a.explain:
        print(explain.code128_doc(a.text).plain())
    if a.output:
        imaging.render_barcode(mods, a.text, quiet=code128.QUIET).save(a.output)
        print(f'Сохранено: {a.output}')


def cmd_scan(a) -> None:
    img = Image.open(a.image).convert('RGB')
    scan = imaging.scan_qr(img)
    if scan.decoded:
        print(explain.scan_doc(scan).plain())
        return
    bar = imaging.scan_barcode(img)
    if bar.text:
        print(f'Штрих-код {bar.kind}: {bar.text} (строк сканирования: {bar.lines_ok} из {bar.lines_total})')
    else:
        print(f'Код не прочитан: {scan.error}')


def cmd_damage(a) -> None:
    img = Image.open(a.image).convert('RGB')
    damage.apply(img, a.kind, a.strength).save(a.output)
    print(f'Сохранено: {a.output}')


def cmd_experiment(a) -> None:
    strengths = [i / a.steps * a.max for i in range(a.steps + 1)]
    print(f'Повреждение: {damage.DAMAGES[a.kind][0]}; сила от 0 до {a.max}')
    for s in analysis.qr_damage_series(a.text, a.kind, strengths, seeds=range(1, a.trials + 1)):
        cells = ' '.join(f'{p.rate * 100:4.0f}%' for p in s.points)
        print(f'{s.label:28} {cells}   порог {s.threshold():.2f}')


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='ЛР №4: QR-коды и штрих-коды')
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('qr', help='построить QR-код')
    p.add_argument('text')
    p.add_argument('-l', '--level', default='M', choices='LMQH')
    p.add_argument('-v', '--version', type=int, help='версия 1–40 (по умолчанию наименьшая подходящая)')
    p.add_argument('-m', '--mask', type=int, choices=range(8), help='маска 0–7 (по умолчанию лучшая)')
    p.add_argument('-s', '--scale', type=int, default=10, help='пикселей на модуль')
    p.add_argument('-o', '--output', help='файл PNG')
    p.add_argument('--explain', action='store_true', help='напечатать все этапы построения')
    p.set_defaults(func=cmd_qr)
    p = sub.add_parser('ean13', help='штрих-код EAN-13')
    p.add_argument('digits')
    p.add_argument('-o', '--output')
    p.add_argument('--explain', action='store_true')
    p.set_defaults(func=cmd_ean13)
    p = sub.add_parser('code128', help='штрих-код Code 128')
    p.add_argument('text')
    p.add_argument('-o', '--output')
    p.add_argument('--explain', action='store_true')
    p.set_defaults(func=cmd_code128)
    p = sub.add_parser('scan', help='прочитать код с картинки')
    p.add_argument('image')
    p.set_defaults(func=cmd_scan)
    p = sub.add_parser('damage', help='испортить картинку')
    p.add_argument('image')
    p.add_argument('kind', choices=list(damage.DAMAGES))
    p.add_argument('strength', type=float)
    p.add_argument('-o', '--output', default='damaged.png')
    p.set_defaults(func=cmd_damage)
    p = sub.add_parser('experiment', help='серия опытов L/M/Q/H')
    p.add_argument('text')
    p.add_argument('kind', choices=list(damage.DAMAGES))
    p.add_argument('--max', type=float, default=0.5)
    p.add_argument('--steps', type=int, default=10)
    p.add_argument('--trials', type=int, default=3)
    p.set_defaults(func=cmd_experiment)
    a = parser.parse_args(argv)
    try:
        a.func(a)
    except (QRError, ean13.BarcodeError, OSError) as e:
        print(f'Ошибка: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
