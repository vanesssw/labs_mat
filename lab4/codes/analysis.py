"""Опыты по помехоустойчивости: как уровень коррекции и вид повреждения влияют на чтение кода."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import code128, damage, ean13, imaging
from . import qr_tables as T
from .qr_decode import QRDecodeError, decode_matrix
from .qr_encode import make_qr


def correctable_share(version: int, level: str) -> float:
    """Доля байтов, которую Рид–Соломон гарантированно восстановит: Σ⌊n/2⌋ / всего байтов."""
    layout = T.block_layout(version, level)
    return sum(e // 2 for _, e in layout) / T.total_codewords(version)


@dataclass
class Point:
    strength: float
    ok: int
    trials: int
    corrected: float = 0.0            # среднее число исправленных байтов в удачных попытках

    @property
    def rate(self) -> float:
        return self.ok / self.trials if self.trials else 0.0


@dataclass
class Series:
    label: str
    points: list[Point] = field(default_factory=list)

    def threshold(self) -> float:
        """Наибольшая сила повреждения, при которой код ещё читается во всех попытках подряд от нуля."""
        last = 0.0
        for p in self.points:
            if p.rate < 1:
                break
            last = p.strength
        return last


def qr_damage_series(text: str, damage_name: str, strengths, levels=T.LEVELS, scale: int = 6,
                     version: int | None = None, seeds=(1,)) -> list[Series]:
    """Для каждого уровня коррекции: доля успешных чтений при нарастающем повреждении картинки."""
    out = []
    for lv in levels:
        q = make_qr(text, lv, version=version)
        img = imaging.render_qr(q.modules, scale=scale)
        s = Series(f'{lv} (версия {q.version}, ~{T.LEVEL_PERCENT[lv]} %)')
        for st in strengths:
            ok, corr = 0, 0
            for seed in seeds:
                fn = damage.DAMAGES[damage_name][1]
                bad = fn(img, st, seed=seed) if damage_name in ('scribble', 'noise') else fn(img, st)
                res = imaging.scan_qr(bad)
                if res.decoded and res.decoded.text == text:
                    ok += 1
                    corr += res.decoded.corrected
            s.points.append(Point(st, ok, len(seeds), corr / ok if ok else 0))
        out.append(s)
    return out


def qr_flip_series(text: str, shares, levels=T.LEVELS, trials: int = 40, version: int | None = None,
                   seed: int = 7) -> list[Series]:
    """Случайно испортить долю байтов (кодовых слов) матрицы: проверка теории Рида–Соломона.

    Портим целые байты (все 8 модулей), поэтому результат зависит только от числа испорченных
    байтов в каждом блоке, а не от формы повреждения.
    """
    from .qr_encode import data_order
    rnd = random.Random(seed)
    out = []
    for lv in levels:
        q = make_qr(text, lv, version=version)
        order = data_order(q.kind)
        total = T.total_codewords(q.version)
        s = Series(f'{lv}: можно исправить {correctable_share(q.version, lv) * 100:.0f} % байтов')
        for share in shares:
            ok = 0
            for _ in range(trials):
                m = [row[:] for row in q.modules]
                for cw in rnd.sample(range(total), int(round(share * total))):
                    for bit in range(8):
                        r, c = order[cw * 8 + bit]
                        m[r][c] ^= rnd.randint(0, 1) if bit else 1      # хотя бы один бит байта меняется
                try:
                    ok += decode_matrix(m).text == text
                except QRDecodeError:
                    pass
            s.points.append(Point(share, ok, trials))
        out.append(s)
    return out


def barcode_damage_series(kind: str, value: str, damage_name: str, strengths, seeds=(1,)) -> Series:
    """Доля удачных чтений штрих-кода (по большинству строк сканирования)."""
    if kind == 'ean13':
        mods, _ = ean13.encode(value)
        img = imaging.render_barcode(mods, ean13.normalize(value), guards=imaging.ean13_guards())
        expect = ean13.normalize(value)
    else:
        mods, _ = code128.encode(value)
        img = imaging.render_barcode(mods, value, quiet=code128.QUIET)
        expect = value
    s = Series(kind.upper())
    for st in strengths:
        ok = 0
        for seed in seeds:
            fn = damage.DAMAGES[damage_name][1]
            bad = fn(img, st, seed=seed) if damage_name in ('scribble', 'noise') else fn(img, st)
            ok += imaging.scan_barcode(bad, kind).text == expect
        s.points.append(Point(st, ok, len(seeds)))
    return s
