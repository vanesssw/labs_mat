"""Формат файла-архива .lab2 и операции с файлами.

Заголовок архива (20 байт + имя файла), числа записаны в порядке little-endian:

    смещение  размер  поле
    0         4       сигнатура b'LAB2' — признак «это наш архив»
    4         1       версия формата (1)
    5         1       метод: 1 — RLE, 2 — Хаффман, 3 — Шеннон–Фано, 4 — LZW
    6         8       размер исходных данных в байтах
    14        4       CRC-32 исходных данных — контроль, что распаковка без искажений
    18        2       длина имени исходного файла L (в байтах)
    20        L       имя исходного файла в кодировке UTF-8
    20 + L    …       сжатые данные (их формат описан в модуле метода)
"""
from __future__ import annotations

import binascii
import struct
import time
from dataclasses import dataclass
from itertools import count
from pathlib import Path

from .methods import AUTO, METHODS, Method, get_method
from .stats import percent, ratio

MAGIC = b'LAB2'
VERSION = 1
EXTENSION = '.lab2'
_HEADER = struct.Struct('<4sBBQIH')  # сигнатура, версия, метод, размер, CRC-32, длина имени


class ArchiveError(Exception):
    """Файл не является архивом ЛР2 или повреждён."""


def crc32(data: bytes) -> int:
    """CRC-32 — остаток от деления «многочлена данных» на стандартный порождающий многочлен."""
    return binascii.crc32(data) & 0xFFFFFFFF


def choose_best(data: bytes) -> tuple[Method, bytes]:
    """Режим «Авто»: сжать всеми методами и оставить самый короткий результат."""
    best = None
    for m in METHODS.values():
        payload = m.compress(data)
        if best is None or len(payload) < len(best[1]):
            best = (m, payload)
    return best


def pack(data: bytes, method: str = 'huffman', name: str = '') -> bytes:
    """Собрать архив: заголовок + имя файла + сжатые данные."""
    if method == AUTO:
        m, payload = choose_best(data)
    else:
        m = get_method(method)
        payload = m.compress(data)
    name_bytes = name.encode('utf-8')[:0xFFFF]
    header = _HEADER.pack(MAGIC, VERSION, m.code, len(data), crc32(data), len(name_bytes))
    return header + name_bytes + payload


@dataclass
class ArchiveInfo:
    name: str             # имя исходного файла
    method: Method
    original_size: int
    crc: int
    header_size: int      # заголовок вместе с именем файла
    payload: bytes        # сжатые данные


def read_info(archive: bytes) -> ArchiveInfo:
    """Разобрать заголовок архива (без распаковки данных)."""
    if len(archive) < _HEADER.size or archive[:4] != MAGIC:
        raise ArchiveError('это не архив ЛР №2 (нет сигнатуры LAB2)')
    _, version, code, size, crc, name_len = _HEADER.unpack_from(archive)
    if version != VERSION:
        raise ArchiveError(f'неподдерживаемая версия формата: {version}')
    try:
        method = get_method(code)
    except KeyError as e:
        raise ArchiveError(str(e)) from None
    start = _HEADER.size + name_len
    name = archive[_HEADER.size:start].decode('utf-8', errors='replace')
    return ArchiveInfo(name, method, size, crc, start, archive[start:])


def unpack(archive: bytes) -> tuple[ArchiveInfo, bytes]:
    """Распаковать архив и проверить, что данные восстановлены без искажений."""
    info = read_info(archive)
    try:
        data = info.method.decompress(info.payload, info.original_size)
    except (ValueError, IndexError) as e:
        raise ArchiveError(f'архив повреждён: {e}') from None
    if len(data) != info.original_size or crc32(data) != info.crc:
        raise ArchiveError('контрольная сумма CRC-32 не совпала — архив повреждён')
    return info, data


@dataclass
class Result:
    """Итог операции над файлом — для вывода пользователю."""
    source: Path
    target: Path
    method: Method
    original_size: int
    archive_size: int
    seconds: float

    @property
    def ratio(self) -> float:
        return ratio(self.original_size, self.archive_size)

    @property
    def percent(self) -> float:
        return percent(self.original_size, self.archive_size)


def free_name(path: Path) -> Path:
    """Если такой файл уже есть — добавить « (1)», « (2)»…, как делает Windows."""
    if not path.exists():
        return path
    for i in count(1):
        candidate = path.with_name(f'{path.stem} ({i}){path.suffix}')
        if not candidate.exists():
            return candidate


def compress_file(source, target=None, method: str = 'huffman') -> Result:
    source = Path(source)
    data = source.read_bytes()
    started = time.perf_counter()
    archive = pack(data, method, source.name)
    seconds = time.perf_counter() - started
    target = Path(target) if target else source.with_name(source.name + EXTENSION)
    target.write_bytes(archive)
    return Result(source, target, read_info(archive).method, len(data), len(archive), seconds)


def decompress_file(source, target=None) -> Result:
    source = Path(source)
    archive = source.read_bytes()
    started = time.perf_counter()
    info, data = unpack(archive)
    seconds = time.perf_counter() - started
    if target:
        target = Path(target)
    else:
        name = Path(info.name).name or source.stem  # отбрасываем возможные пути в имени
        target = free_name(source.with_name(name))
    target.write_bytes(data)
    return Result(source, target, info.method, len(data), len(archive), seconds)


@dataclass
class BenchRow:
    method: Method
    archive_size: int
    compress_seconds: float
    decompress_seconds: float
    ok: bool              # распакованные данные совпали с исходными


def benchmark(data: bytes, name: str = '') -> list[BenchRow]:
    """Сжать данные каждым методом, распаковать обратно и проверить совпадение."""
    rows = []
    for m in METHODS.values():
        t0 = time.perf_counter()
        archive = pack(data, m.key, name)
        t1 = time.perf_counter()
        try:
            _, restored = unpack(archive)
            ok = restored == data
        except ArchiveError:
            ok = False
        t2 = time.perf_counter()
        rows.append(BenchRow(m, len(archive), t1 - t0, t2 - t1, ok))
    return rows
