"""Создаёт набор тестовых файлов в папке test_files.

Запуск из папки lab2:   python tools/make_test_files.py

Файл 01_text_ru_cp1251.txt (текст методических указаний) уже лежит в папке —
из него получаются UTF-8-версия текста и ZIP-архив. Остальные файлы
генерируются программно, всегда одинаково (генератор случайных чисел с
фиксированным зерном).
"""
from __future__ import annotations

import math
import random
import struct
import wave
import zipfile
from pathlib import Path

LAB_DIR = Path(__file__).resolve().parents[1]
OUT = LAB_DIR / 'test_files'
rnd = random.Random(2026)


def text_files() -> None:
    text = (OUT / '01_text_ru_cp1251.txt').read_bytes().decode('cp1251')
    (OUT / '02_text_ru_utf8.txt').write_bytes(text.encode('utf-8'))
    with zipfile.ZipFile(OUT / '10_archive.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('text_ru_cp1251.txt', text.encode('cp1251'))


def source_code() -> None:
    parts = [f'# ===== {p.name} =====\n' + p.read_text('utf-8')
             for p in sorted((LAB_DIR / 'packer').glob('*.py'))]
    (OUT / '03_source_code.py').write_text('\n'.join(parts), 'utf-8')


def csv_table() -> None:
    lines = ['дата;время;датчик;величина;значение;единица']
    sensors = {'температура': ('°C', 18, 26), 'влажность': ('%', 30, 60), 'давление': ('кПа', 99, 102)}
    for day in range(1, 8):
        for hour in range(24):
            for minute in (0, 15, 30, 45):
                for sensor_id in (1, 2, 3):
                    name = rnd.choice(list(sensors))
                    unit, low, high = sensors[name]
                    lines.append(f'2026-10-{day:02d};{hour:02d}:{minute:02d};Датчик-{sensor_id:02d};'
                                 f'{name};{rnd.uniform(low, high):.1f};{unit}')
    (OUT / '04_table.csv').write_text('\n'.join(lines) + '\n', 'utf-8')


def server_log() -> None:
    levels = ['INFO'] * 8 + ['WARN', 'ERROR']
    paths = ['/api/v1/items', '/api/v1/users', '/login', '/static/app.js', '/static/style.css']
    lines = []
    for i in range(2500):
        t = 9 * 3600 + i * 7
        level = rnd.choice(levels)
        status = 200 if level == 'INFO' else (404 if level == 'WARN' else 500)
        lines.append(f'2026-10-12 {t // 3600:02d}:{t // 60 % 60:02d}:{t % 60:02d} {level:5} '
                     f'[worker-{rnd.randrange(1, 5)}] GET {rnd.choice(paths)}?id={rnd.randrange(1000)} '
                     f'{status} {rnd.randrange(3, 250)}ms')
    (OUT / '05_server.log').write_text('\n'.join(lines) + '\n', 'ascii')


def bmp_image(width: int = 320, height: int = 240) -> None:
    """24-битный BMP: белый фон, рамка, тёмная шапка, «строки текста», цветные фигуры."""
    def pixel(x: int, y: int) -> tuple[int, int, int]:
        if x < 2 or y < 2 or x >= width - 2 or y >= height - 2:
            return 0, 0, 0                                   # чёрная рамка
        if y < 30:
            return 64, 64, 64                                # тёмно-серая шапка
        if 20 <= x < 140 and 50 <= y < 130:
            return 40, 90, 200                               # синий прямоугольник
        if (x - 230) ** 2 + (y - 95) ** 2 < 45 ** 2:
            return 220, 40, 40                               # красный круг
        if 145 <= y < 165 and 20 <= x < 300 and (x // 12) % 3 != 2 and (y - 145) % 10 < 6:
            return 0, 0, 0                                   # «строки текста»
        if 180 <= y < 225 and 20 <= x < 300:
            return (60, 170, 60) if (x - 20) // 20 % 2 == 0 else (255, 255, 255)  # полосы
        return 255, 255, 255                                 # белый фон

    row_size = (width * 3 + 3) // 4 * 4                      # строки выравниваются на 4 байта
    pixels = bytearray()
    for y in range(height - 1, -1, -1):                      # BMP хранит строки снизу вверх
        row = bytearray()
        for x in range(width):
            r, g, b = pixel(x, y)
            row += bytes((b, g, r))                          # порядок байтов в BMP: B, G, R
        pixels += row + bytes(row_size - len(row))
    header = b'BM' + struct.pack('<IHHI', 54 + len(pixels), 0, 0, 54)
    info = struct.pack('<IiiHHIIiiII', 40, width, height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
    (OUT / '06_image.bmp').write_bytes(header + info + bytes(pixels))


def wav_sound(seconds: float = 1.5, rate: int = 22050) -> None:
    """Звук: аккорд из двух синусоид (440 и 660 Гц) с лёгким шумом, 16 бит, моно."""
    frames = bytearray()
    for i in range(int(seconds * rate)):
        t = i / rate
        v = 0.5 * math.sin(2 * math.pi * 440 * t) + 0.3 * math.sin(2 * math.pi * 660 * t)
        frames += struct.pack('<h', int(v * 12000 + rnd.gauss(0, 150)))
    with wave.open(str(OUT / '13_sound.wav'), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def synthetic() -> None:
    (OUT / '07_one_char.txt').write_bytes(b'A' * 10_000)
    (OUT / '08_pattern_0_255.bin').write_bytes(bytes(range(256)) * 200)
    (OUT / '09_random.bin').write_bytes(rnd.randbytes(65_536))
    (OUT / '11_tiny.txt').write_bytes('Привет!'.encode('utf-8'))
    (OUT / '12_empty.txt').write_bytes(b'')


if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    text_files()
    source_code()
    csv_table()
    server_log()
    bmp_image()
    wav_sound()
    synthetic()
    for f in sorted(OUT.iterdir()):
        print(f'{f.name:28} {f.stat().st_size:>9} Б')
