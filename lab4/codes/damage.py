"""Повреждения изображения кода для анализа помехоустойчивости (задание методички:
«почеркать, изменить цвета, размыть, отрезать углы…»).

Каждая функция принимает картинку и силу повреждения и возвращает новую картинку.
Сила — число от 0 до 1 (для каждого вида свой смысл, см. DAMAGES).
"""
from __future__ import annotations

import random

from PIL import Image, ImageDraw, ImageFilter, ImageOps


def _code_box(img: Image.Image) -> tuple[int, int, int, int]:
    """Прямоугольник, где нарисован сам код (без светлого поля): по тёмным пикселям."""
    gray = img.convert('L')
    box = ImageOps.invert(gray).point(lambda v: 255 if v > 100 else 0).getbbox()
    return box or (0, 0, img.width, img.height)


def scribble(img: Image.Image, strength: float, seed: int = 1, color=(0, 0, 0)) -> Image.Image:
    """Почеркать: случайные линии ручкой поверх кода. strength — число линий / 20."""
    out = img.copy()
    d = ImageDraw.Draw(out)
    x0, y0, x1, y1 = _code_box(img)
    rnd = random.Random(seed)
    width = max(2, int((x1 - x0) * 0.012))
    for _ in range(int(round(strength * 20))):
        pts = [(rnd.uniform(x0, x1), rnd.uniform(y0, y1)) for _ in range(3)]
        d.line(pts, fill=color, width=width, joint='curve')
    return out


def blot(img: Image.Image, strength: float, color=(0, 0, 0)) -> Image.Image:
    """Клякса (или логотип) в центре: квадрат, закрывающий долю strength площади кода."""
    out = img.copy()
    x0, y0, x1, y1 = _code_box(img)
    side = ((x1 - x0) * (y1 - y0) * strength) ** 0.5
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    ImageDraw.Draw(out).rectangle([cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2], fill=color)
    return out


def recolor(img: Image.Image, strength: float, dark=(30, 60, 160), light=(255, 230, 120)) -> Image.Image:
    """Изменить цвета: тёмные модули → dark, светлые → light, плавно в зависимости от strength."""
    gray = img.convert('L')
    t = strength
    d = tuple(int(0 * (1 - t) + c * t) for c in dark)
    l = tuple(int(255 * (1 - t) + c * t) for c in light)
    return ImageOps.colorize(gray, black=d, white=l)


def contrast(img: Image.Image, strength: float) -> Image.Image:
    """Снизить контраст: тёмные и светлые модули сближаются к серому. strength = 1 — серое пятно."""
    gray = img.convert('RGB')
    flat = Image.new('RGB', img.size, (128, 128, 128))
    return Image.blend(gray, flat, min(strength, 0.999))


def invert(img: Image.Image, strength: float = 1.0) -> Image.Image:
    """Инверсия: светлый код на тёмном фоне."""
    return ImageOps.invert(img.convert('RGB')) if strength >= 0.5 else img.copy()


def blur(img: Image.Image, strength: float) -> Image.Image:
    """Размытие по Гауссу. strength = 1 — радиус 1/20 стороны кода."""
    x0, y0, x1, y1 = _code_box(img)
    return img.filter(ImageFilter.GaussianBlur(radius=strength * (x1 - x0) / 20))


def cut_corner(img: Image.Image, strength: float, corner: str = 'br') -> Image.Image:
    """Отрезать угол: закрасить фоном треугольник с катетом strength от стороны кода."""
    out = img.copy()
    x0, y0, x1, y1 = _code_box(img)
    a = (x1 - x0) * strength
    pts = {'br': [(x1 + 2, y1 + 2), (x1 - a, y1 + 2), (x1 + 2, y1 - a)],
           'tl': [(x0 - 2, y0 - 2), (x0 + a, y0 - 2), (x0 - 2, y0 + a)],
           'tr': [(x1 + 2, y0 - 2), (x1 - a, y0 - 2), (x1 + 2, y0 + a)],
           'bl': [(x0 - 2, y1 + 2), (x0 + a, y1 + 2), (x0 - 2, y1 - a)]}[corner]
    bg = img.getpixel((0, 0))
    ImageDraw.Draw(out).polygon(pts, fill=bg)
    return out


def noise(img: Image.Image, strength: float, seed: int = 1) -> Image.Image:
    """«Соль и перец»: доля strength пикселей заменяется случайными чёрными и белыми."""
    out = img.convert('RGB').copy()
    px = out.load()
    rnd = random.Random(seed)
    w, h = out.size
    for _ in range(int(w * h * strength)):
        px[rnd.randrange(w), rnd.randrange(h)] = (0, 0, 0) if rnd.random() < 0.5 else (255, 255, 255)
    return out


def rotate(img: Image.Image, strength: float) -> Image.Image:
    """Поворот на strength·45°."""
    bg = img.getpixel((0, 0))
    return img.rotate(strength * 45, resample=Image.BICUBIC, expand=True, fillcolor=bg)


DAMAGES = {
    'scribble': ('Почеркать ручкой', scribble, 'число линий = 20·сила'),
    'blot': ('Клякса / логотип в центре', blot, 'доля закрытой площади кода'),
    'cut_br': ('Отрезать правый нижний угол', lambda i, s: cut_corner(i, s, 'br'), 'катет / сторона кода'),
    'cut_tl': ('Отрезать левый верхний угол', lambda i, s: cut_corner(i, s, 'tl'), 'катет / сторона кода'),
    'blur': ('Размыть', blur, 'радиус размытия = сила · сторона кода / 20'),
    'recolor': ('Изменить цвета (синий на жёлтом)', recolor, 'насколько сильно сменить цвета'),
    'contrast': ('Снизить контраст', contrast, 'доля смешивания с серым'),
    'invert': ('Инвертировать цвета', invert, '≥ 0,5 — инверсия'),
    'noise': ('Шум «соль и перец»', noise, 'доля испорченных пикселей'),
    'rotate': ('Повернуть', rotate, 'угол = 45°·сила'),
}


def apply(img: Image.Image, name: str, strength: float) -> Image.Image:
    return DAMAGES[name][1](img, strength)
