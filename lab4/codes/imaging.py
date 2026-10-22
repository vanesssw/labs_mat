"""Картинки кодов и «сканер», который читает код с изображения.

Рисование: каждый модуль — квадрат scale×scale пикселей, вокруг светлое поле (quiet zone).

Сканер QR работает как настоящий, только без поиска перспективы:
    1. перевод в оттенки серого (яркость Y = 0,299R + 0,587G + 0,114B), при необходимости
       медианный фильтр 3×3 против шума, и бинаризация: порог посередине между уровнями
       тёмного и светлого (запасной вариант — порог Оцу);
    2. поиск шаблонов поиска: в строках ищем серии «тёмный–светлый–тёмный–светлый–тёмный»
       с отношением ширин 1:1:3:1:1 и проверяем то же по вертикали;
    3. три найденных шаблона задают угол, масштаб и поворот сетки; по расстоянию между ними
       определяется число модулей n и версия;
    4. в центре каждого модуля берётся средняя яркость → матрица 0/1 → qr_decode.
Сканер штрих-кода проходит несколько горизонтальных строк, измеряет ширины штрихов и пробелов
и голосует: выбирается ответ, который дали больше всего строк.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import code128, ean13
from .qr_decode import Decoded, QRDecodeError, decode_matrix

KIND_COLORS = {
    'finder': (31, 78, 160), 'separator': (205, 220, 240), 'timing': (40, 150, 70), 'alignment': (215, 120, 20),
    'format': (170, 40, 150), 'version': (0, 150, 160), 'dark': (200, 30, 30),
}
KIND_NAMES = {
    'finder': 'шаблон поиска', 'separator': 'разделитель', 'timing': 'синхронизирующая линия',
    'alignment': 'выравнивающий узор', 'format': 'служебная информация (уровень и маска)',
    'version': 'номер версии', 'dark': 'тёмный модуль', None: 'данные и коррекция',
}


# ==========================================================================
# Рисование
# ==========================================================================

def render_qr(modules, scale: int = 8, border: int = 4, dark=(0, 0, 0), light=(255, 255, 255)) -> Image.Image:
    n = len(modules)
    arr = np.array(modules, dtype=np.uint8)
    arr = np.pad(arr, border)
    img = np.where(arr[..., None] == 1, np.array(dark, np.uint8), np.array(light, np.uint8))
    img = np.repeat(np.repeat(img, scale, axis=0), scale, axis=1)
    return Image.fromarray(img.astype(np.uint8), 'RGB')


def render_kinds(modules, kind, scale: int = 10, border: int = 2) -> Image.Image:
    """Матрица, раскрашенная по назначению модулей: тёмные — насыщенным цветом, светлые — бледным."""
    n = len(modules)
    img = Image.new('RGB', ((n + 2 * border) * scale,) * 2, (255, 255, 255))
    d = ImageDraw.Draw(img)
    for r in range(n):
        for c in range(n):
            k = kind[r][c]
            if k is None:
                color = (40, 40, 40) if modules[r][c] else (238, 238, 238)
            else:
                base = KIND_COLORS[k]
                color = base if modules[r][c] else tuple(int(255 - (255 - v) * 0.25) for v in base)
            x, y = (c + border) * scale, (r + border) * scale
            d.rectangle([x, y, x + scale - 1, y + scale - 1], fill=color)
    return img


def render_barcode(modules: str, label: str = '', module: int = 3, height: int = 140, quiet: int = 11,
                   dark=(0, 0, 0), light=(255, 255, 255), guards: set[int] | None = None) -> Image.Image:
    """Штрих-код: ширина модуля module пикселей. guards — удлинённые штрихи-ограничители (EAN-13);
    тогда 13 цифр подписываются по стандарту: первая слева, по 6 под каждой половиной."""
    width = (len(modules) + 2 * quiet) * module
    text_h = 26 if label else 0
    top = 8
    img = Image.new('RGB', (width, top + height + text_h + 6), light)
    d = ImageDraw.Draw(img)
    for i, b in enumerate(modules):
        if b == '1':
            x = (quiet + i) * module
            bottom = top + height + (text_h // 2 if guards and i in guards else 0)
            d.rectangle([x, top, x + module - 1, bottom], fill=dark)
    if label:
        try:
            font = ImageFont.truetype('consola.ttf', 6 * module + 2)
        except OSError:
            font = ImageFont.load_default()
        y = top + height + 2
        if guards and len(label) == 13:
            centers = [(quiet - 4) * module] + [(quiet + 3 + 7 * i + 3.5) * module for i in range(6)] +                       [(quiet + 50 + 7 * i + 3.5) * module for i in range(6)]
            for ch, cx in zip(label, centers):
                d.text((cx - d.textlength(ch, font=font) / 2, y), ch, fill=dark, font=font)
        else:
            d.text(((width - d.textlength(label, font=font)) / 2, y), label, fill=dark, font=font)
    return img


def ean13_guards() -> set[int]:
    return set(range(0, 3)) | set(range(45, 50)) | set(range(92, 95))


# ==========================================================================
# Бинаризация
# ==========================================================================

def to_gray(img: Image.Image) -> np.ndarray:
    """Яркость каждого пикселя 0…255 (именно её видит сканер, цвет теряется)."""
    return np.asarray(img.convert('L'), dtype=np.float64)


def otsu(gray: np.ndarray) -> float:
    """Порог Оцу: перебираем порог t и выбираем тот, при котором дисперсия между классами
    «тёмные» и «светлые» максимальна (σ²_между = w₀·w₁·(μ₀ − μ₁)²)."""
    hist = np.bincount(gray.astype(np.uint8).ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    levels = np.arange(256)
    w0 = np.cumsum(hist)
    w1 = total - w0
    m0 = np.cumsum(hist * levels)
    mean_all = m0[-1]
    with np.errstate(divide='ignore', invalid='ignore'):
        between = (mean_all * w0 / total - m0) ** 2 / (w0 * w1 / total)
    between[~np.isfinite(between)] = 0
    best = np.flatnonzero(between >= between.max() * (1 - 1e-9))
    return (float(best[0]) + float(best[-1])) / 2 + 0.5     # середина «плато» лучших порогов


def midrange(gray: np.ndarray) -> float:
    """Порог посередине между уровнем тёмного (2-й процентиль) и светлого (98-й процентиль)."""
    lo, hi = np.percentile(gray, (2, 98))
    return float(lo + hi) / 2


def median3(img: Image.Image) -> Image.Image:
    """Медианный фильтр 3×3: каждый пиксель заменяется медианой соседей — убирает одиночные точки шума."""
    return img.convert('L').filter(ImageFilter.MedianFilter(3))


def binarize(img: Image.Image, invert: bool = False, method: str = 'midrange') -> tuple[np.ndarray, np.ndarray, float]:
    gray = to_gray(img)
    t = midrange(gray) if method == 'midrange' else otsu(gray)
    dark = gray < t
    return (~dark if invert else dark), gray, t


# ==========================================================================
# Поиск QR-кода
# ==========================================================================

def _runs(line: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Серии одинаковых значений: (начала, длины, значения)."""
    change = np.flatnonzero(np.diff(line.astype(np.int8))) + 1
    starts = np.concatenate(([0], change))
    lengths = np.diff(np.concatenate((starts, [len(line)])))
    return starts, lengths, line[starts]


def _ratio_ok(w, tol: float = 0.6) -> float | None:
    """Проверка отношения 1:1:3:1:1. Возвращает размер модуля или None."""
    total = sum(w)
    if total < 7:
        return None
    m = total / 7
    for wi, k in zip(w, (1, 1, 3, 1, 1)):
        if abs(wi - k * m) > tol * m * (1.5 if k == 3 else 1):
            return None
    return m


def _cross(binary, x: int, y: int, horizontal: bool) -> tuple[float, float] | None:
    """Перепроверка шаблона по второму направлению через точку (x, y): (центр, модуль)."""
    line = binary[:, x] if not horizontal else binary[y, :]
    p = y if not horizontal else x
    if not line[p]:
        return None
    starts, lengths, vals = _runs(line)
    i = int(np.searchsorted(starts, p, side='right')) - 1
    if i < 2 or i + 2 >= len(lengths):
        return None
    w = lengths[i - 2:i + 3]
    if list(vals[i - 2:i + 3]) != [1, 0, 1, 0, 1]:
        return None
    m = _ratio_ok(w)
    if m is None:
        return None
    return starts[i - 2] + w.sum() / 2, m


def find_finders(binary: np.ndarray) -> list[tuple[float, float, float, int]]:
    """Кандидаты шаблонов поиска: [(x, y, модуль, сколько строк его подтвердили)]."""
    h, w = binary.shape
    hits = []
    for y in range(0, h, 1):
        starts, lengths, vals = _runs(binary[y])
        for i in range(len(lengths) - 4):
            if vals[i] != 1:
                continue
            seg = lengths[i:i + 5]
            m = _ratio_ok(seg)
            if m is None:
                continue
            cx = starts[i] + seg.sum() / 2
            # перепроверка по вертикали и снова по горизонтали — через несколько точек центрального
            # квадрата 3×3: одна линия ручки может испортить одну проверку, но не все
            offsets = [0, -m, m]
            v = next((r for dx in offsets if 0 <= int(cx + dx) < w
                      for r in [_cross(binary, int(cx + dx), y, horizontal=False)] if r), None)
            if v is None:
                continue
            cy, mv = v
            hh = next((r for dy in offsets if 0 <= int(cy + dy) < h
                       for r in [_cross(binary, int(cx), int(cy + dy), horizontal=True)] if r), None)
            if hh is None:
                continue
            hits.append((hh[0], cy, (m + mv + hh[1]) / 3))
    clusters: list[list] = []
    for x, y, m in hits:
        for cl in clusters:
            if abs(cl[0] - x) < 2.5 * m and abs(cl[1] - y) < 2.5 * m:
                n = cl[3]
                cl[0] = (cl[0] * n + x) / (n + 1)
                cl[1] = (cl[1] * n + y) / (n + 1)
                cl[2] = (cl[2] * n + m) / (n + 1)
                cl[3] = n + 1
                break
        else:
            clusters.append([x, y, m, 1])
    clusters.sort(key=lambda c: -c[3])
    return [tuple(c) for c in clusters]


@dataclass
class Located:
    top_left: tuple[float, float]
    top_right: tuple[float, float]
    bottom_left: tuple[float, float]
    module: float
    size: int


def _corner_order(trio):
    """Упорядочить три точки: (левый верхний, правый верхний, левый нижний) и оценить «прямоугольность»."""
    pts = [np.array(c[:2]) for c in trio]
    best = None
    for i in range(3):
        tl = pts[i]
        a, b = [pts[j] for j in range(3) if j != i]
        u, v = a - tl, b - tl
        la, lb = np.linalg.norm(u), np.linalg.norm(v)
        if la < 1 or lb < 1:
            continue
        cos = abs(float(u @ v)) / (la * lb)                  # у прямого угла косинус = 0
        err = cos + abs(la - lb) / max(la, lb)               # стороны прямого угла равны
        if best is None or err < best[0]:
            if u[0] * v[1] - u[1] * v[0] < 0:                # по часовой стрелке: сначала правый верхний
                a, b = b, a
            best = (err, tl, a, b)
    return best


def locate(binary: np.ndarray) -> Located:
    """Найти три шаблона поиска, образующие прямоугольный равнобедренный треугольник, и размер матрицы."""
    from itertools import combinations
    cands = [c for c in find_finders(binary) if c[3] >= 2][:8]
    if len(cands) < 3:
        raise QRDecodeError(f'найдено шаблонов поиска: {len(cands)} из 3 — код не обнаружен')
    best = None
    for trio in combinations(cands, 3):
        ms = [c[2] for c in trio]
        spread = (max(ms) - min(ms)) / np.mean(ms)          # модули трёх шаблонов должны совпадать
        order = _corner_order(trio)
        if order is None or spread > 0.4 or order[0] > 0.25:
            continue
        score = (order[0] + spread, -sum(c[3] for c in trio))
        if best is None or score < best[0]:
            best = (score, trio, order)
    if best is None:
        raise QRDecodeError('три шаблона поиска не образуют квадратный код — код не обнаружен')
    _, trio, (_, tl, a, b) = best
    module = float(np.mean([c[2] for c in trio]))
    side = (np.linalg.norm(a - tl) + np.linalg.norm(b - tl)) / 2
    n = side / module + 7
    size = int(round((n - 17) / 4)) * 4 + 17
    size = min(177, max(21, size))
    return Located(tuple(tl), tuple(a), tuple(b), module, size)


def sample(gray: np.ndarray, threshold: float, loc: Located, invert: bool = False) -> list[list[int]]:
    """Средняя яркость в центре каждого модуля → 0/1.

    Центр модуля (строка r, столбец c): P = TL + (c − 3)·u + (r − 3)·v, где u и v — шаги сетки по
    столбцам и строкам (TL — центр левого верхнего шаблона, он лежит в модуле (3, 3)). Среднее
    по квадрату вокруг центра считается через интегральное изображение — сразу для всех модулей.
    """
    n = loc.size
    tl, tr, bl = (np.array(p) for p in (loc.top_left, loc.top_right, loc.bottom_left))
    u, v = (tr - tl) / (n - 7), (bl - tl) / (n - 7)
    rad = max(0, int(min(np.linalg.norm(u), np.linalg.norm(v)) * 0.2))
    h, w = gray.shape
    rr, cc = np.mgrid[0:n, 0:n]
    xi = np.rint(tl[0] + (cc - 3) * u[0] + (rr - 3) * v[0]).astype(int)
    yi = np.rint(tl[1] + (cc - 3) * u[1] + (rr - 3) * v[1]).astype(int)
    x0, x1 = np.clip(xi - rad, 0, w), np.clip(xi + rad + 1, 0, w)
    y0, y1 = np.clip(yi - rad, 0, h), np.clip(yi + rad + 1, 0, h)
    integral = np.pad(gray.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    total = integral[y1, x1] - integral[y0, x1] - integral[y1, x0] + integral[y0, x0]
    area = (x1 - x0) * (y1 - y0)
    mean = np.where(area > 0, total / np.maximum(area, 1), 255.0)
    bits = (mean < threshold).astype(int)
    if invert:
        bits ^= 1
    return bits.tolist()


@dataclass
class Scan:
    decoded: Decoded | None
    error: str = ''
    how: str = ''                     # какая попытка сработала: фильтр, порог, полярность
    located: Located | None = None
    matrix: list[list[int]] | None = None


ATTEMPTS = [(False, 'midrange', False), (True, 'midrange', False), (False, 'otsu', False),
            (False, 'midrange', True), (True, 'midrange', True)]


def scan_qr(img: Image.Image) -> Scan:
    """Найти и прочитать QR-код. Попытки: без фильтра и с медианным, порог-середина и Оцу,
    обычная и инвертированная полярность (светлый код на тёмном фоне)."""
    errors = []
    for filtered, method, invert in ATTEMPTS:
        source = median3(img) if filtered else img
        binary, gray, t = binarize(source, invert, method)
        try:
            loc = locate(binary)
        except QRDecodeError as e:
            errors.append(str(e))
            continue
        how = ', '.join(x for x in ('медианный фильтр' if filtered else '', 'порог Оцу' if method == 'otsu' else '',
                                    'инверсия' if invert else '') if x) or 'без обработки'
        # размер по расстоянию между шаблонами может ошибиться на ±4 модуля — пробуем соседние версии
        for size in (loc.size, loc.size - 4, loc.size + 4, loc.size - 8, loc.size + 8):
            if not 21 <= size <= 177:
                continue
            trial = Located(loc.top_left, loc.top_right, loc.bottom_left, loc.module, size)
            m = sample(gray, t, trial, invert)
            try:
                return Scan(decode_matrix(m), how=how + ('' if size == loc.size else f', размер уточнён до {size}'),
                            located=trial, matrix=m)
            except QRDecodeError as e:
                if size == loc.size:
                    errors.append(str(e))
    located = [e for e in errors if not e.startswith('найдено шаблонов') and 'разного размера' not in e]
    return Scan(None, (located or errors)[0])


# ==========================================================================
# Чтение штрих-кодов
# ==========================================================================

@dataclass
class BarcodeScan:
    text: str | None
    lines_ok: int
    lines_total: int
    kind: str = ''
    error: str = ''


def scan_barcode(img: Image.Image, kind: str = 'auto', lines: int = 25) -> BarcodeScan:
    """Прочитать EAN-13 или Code 128 по нескольким горизонтальным строкам и проголосовать."""
    h = img.height
    votes: Counter = Counter()
    last_error = 'штрихи не найдены'
    rows = np.linspace(h * 0.1, h * 0.75, lines).astype(int)
    for filtered in (False, True):                                # без фильтра и с медианным фильтром
        binary, _, _ = binarize(median3(img) if filtered else img)
        if binary[rows].sum() > 0.8 * binary[rows].size:          # светлые штрихи на тёмном фоне
            binary = ~binary
        _vote_lines(binary, rows, kind, votes)
    if not votes:
        return BarcodeScan(None, 0, len(rows), error=last_error)
    (k, text), count = votes.most_common(1)[0]
    return BarcodeScan(text, count, 2 * len(rows), k)


def _vote_lines(binary, rows, kind, votes) -> None:
    for y in rows:
        starts, lengths, vals = _runs(binary[y])
        first = np.flatnonzero(vals == 1)
        if len(first) == 0:
            continue
        i0 = int(first[0])
        last = int(np.flatnonzero(vals == 1)[-1])
        runs = [float(x) for x in lengths[i0:last + 1]]
        for k in (('ean13', 'code128') if kind == 'auto' else (kind,)):
            try:
                text = ean13.decode_runs(runs) if k == 'ean13' else code128.decode_runs(runs)
                votes[(k, text)] += 1
                break
            except (ean13.BarcodeError, ValueError):
                pass
