"""Графический интерфейс ЛР №5 «Генераторы псевдослучайных чисел» (tkinter, numpy, Pillow).

Запуск из папки lab5:   python gui.py     (или двойной щелчок по start_gui.bat)

Вкладки:
  «Генератор»         — первые шаги датчика по формуле, гистограмма, пары (uₙ, uₙ₊₁), картинка из битов;
  «Проверка качества» — 14 статистических тестов с p-значениями для выбранного датчика;
  «Сравнение»         — все датчики через одни и те же тесты; «плоскости» RANDU.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

import numpy as np
from PIL import Image, ImageTk

from prng import explain, properties
from prng import generators as G
from prng import stat_tests as st

BG = '#f3f3f1'
SURFACE = '#fcfcfb'
INK = '#0b0b0b'
INK_2 = '#52514e'
MUTED = '#898781'
GRID = '#e1e0d9'
AXIS = '#c3c2b7'
GOOD = '#0ca30c'
GOOD_TEXT = '#006300'
GOOD_LIGHT = '#d9f2d9'
CRITICAL = '#d03b3b'
CRITICAL_LIGHT = '#fadcdc'
ACCENT = '#2a78d6'
ACCENT_DARK = '#256abf'

SCALE = 1.0
FONTS: dict[str, tkfont.Font] = {}
CUSTOM = 'Свой ЛКГ (a, c, m)'
SIZES = {'Быстро: 20 000 чисел, 200 000 бит': (20_000, 200_000),
         'Как в NIST: 100 000 чисел, 1 000 000 бит': (100_000, 1_000_000)}


def px(value: float) -> int:
    return int(round(value * SCALE))


class Background:
    def __init__(self, widget: tk.Misc) -> None:
        self.widget = widget

    def start(self, work, on_done, on_error) -> None:
        q: queue.Queue = queue.Queue()

        def target():
            try:
                q.put(('done', work()))
            except Exception as e:  # noqa: BLE001
                q.put(('error', e))

        def poll():
            try:
                kind, value = q.get_nowait()
                (on_done if kind == 'done' else on_error)(value)
            except queue.Empty:
                self.widget.after(60, poll)

        threading.Thread(target=target, daemon=True).start()
        self.widget.after(60, poll)


class RichText(tk.Text):
    def __init__(self, master, **kw) -> None:
        super().__init__(master, wrap='word', relief='flat', bg=SURFACE, fg=INK, padx=px(16), pady=px(12),
                         font=FONTS['ui'], highlightthickness=0, **kw)
        self.tag_configure('h1', font=FONTS['h1'], spacing3=px(6))
        self.tag_configure('h2', font=FONTS['bold'], spacing1=px(14), spacing3=px(4))
        self.tag_configure('th', font=FONTS['bold'], spacing3=px(3))
        self.tag_configure('mono', font=FONTS['mono'], lmargin1=px(10), lmargin2=px(10), wrap='none')
        self.tag_configure('formula', lmargin1=px(10), lmargin2=px(24), spacing1=px(2))
        self.tag_configure('p', spacing1=px(3), spacing3=px(3))
        self.tag_configure('muted', foreground=INK_2)
        self.tag_configure('good', foreground=GOOD_TEXT)
        self.tag_configure('bad', foreground=CRITICAL)
        self.tag_configure('row_good', background=GOOD_LIGHT)
        self.tag_configure('row_bad', background=CRITICAL_LIGHT)
        self._tables = 0

    def table(self, rows, right=frozenset(), marks=None) -> None:
        ui, bold = FONTS['ui'], FONTS['bold']
        widths = [max([bold.measure(str(rows[0][i]))] + [ui.measure(str(r[i])) for r in rows[1:]])
                  for i in range(len(rows[0]))]
        margin, gap = px(10), px(18)
        tabs, x = [], margin
        for i, w in enumerate(widths):
            if i in right:
                tabs += [x + w, 'right']
            elif i:
                tabs += [x, 'left']
            x += w + gap
        self._tables += 1
        tag = f'table{self._tables}'
        self.tag_configure(tag, tabs=tabs, lmargin1=margin, lmargin2=margin, wrap='none')
        for k, row in enumerate(rows):
            line = ('\t' if 0 in right else '') + '\t'.join(str(c) for c in row)
            tags = (tag, 'th') if k == 0 else (tag,)
            if marks and k in marks:
                tags += ('row_' + marks[k],)
            self.insert('end', line + '\n', tags)

    def render(self, doc: explain.Doc) -> None:
        self.configure(state='normal')
        self.delete('1.0', 'end')
        for kind, data, tags in doc.blocks:
            if kind in ('h1', 'h2'):
                self.insert('end', data + '\n', (kind,))
            elif kind in ('p', 'formula'):
                self.insert('end', data + '\n', (kind,) + tags)
            elif kind == 'mono':
                self.insert('end', '\n'.join(data) + '\n', ('mono',) + tags)
            elif kind == 'table':
                rows, right, marks = data
                self.table(rows, right, marks)
        self.configure(state='disabled')
        self.see('1.0')


def scrolled(master, widget_cls, **kw):
    frame = ttk.Frame(master)
    widget = widget_cls(frame, **kw)
    bar = ttk.Scrollbar(frame, orient='vertical', command=widget.yview)
    widget.configure(yscrollcommand=bar.set)
    widget.pack(side='left', fill='both', expand=True)
    bar.pack(side='right', fill='y')
    return frame, widget


# ==========================================================================
# Небольшие графики на холсте
# ==========================================================================

class Chart(tk.Canvas):
    """Холст с заголовком и областью построения; draw_fn(chart, x0, y0, x1, y1) рисует содержимое."""

    def __init__(self, master, title: str, **kw) -> None:
        super().__init__(master, bg=SURFACE, highlightthickness=0, **kw)
        self.title = title
        self.draw_fn = None
        self._img = None
        self.bind('<Configure>', lambda e: self.redraw())

    def set(self, draw_fn, title: str | None = None) -> None:
        self.draw_fn = draw_fn
        if title:
            self.title = title
        self.redraw()

    def redraw(self) -> None:
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        self.create_text(px(10), px(10), text=self.title, anchor='nw', font=FONTS['bold'], fill=INK)
        if self.draw_fn and w > px(120) and h > px(100):        # холст уже получил размеры
            self.draw_fn(self, px(44), px(34), w - px(14), h - px(26))


def draw_histogram(u: np.ndarray, bins: int = 20):
    counts = np.bincount(np.minimum((u * bins).astype(int), bins - 1), minlength=bins)
    expected = len(u) / bins

    def fn(c: Chart, x0, y0, x1, y1):
        top = max(counts.max(), expected) * 1.1
        for k in range(5):
            y = y1 - (y1 - y0) * k / 4
            c.create_line(x0, y, x1, y, fill=GRID)
            c.create_text(x0 - px(4), y, text=f'{top * k / 4:.0f}', anchor='e', font=FONTS['small'], fill=MUTED)
        bw = (x1 - x0) / bins
        for i, v in enumerate(counts):
            c.create_rectangle(x0 + i * bw + 1, y1 - (y1 - y0) * v / top, x0 + (i + 1) * bw - 1, y1,
                               fill=ACCENT, width=0)
        ye = y1 - (y1 - y0) * expected / top
        c.create_line(x0, ye, x1, ye, fill=CRITICAL, dash=(4, 3), width=px(1.5))
        c.create_text(x1, ye - px(8), text='ожидание n/k', anchor='e', font=FONTS['small'], fill=CRITICAL)
        c.create_text(x0, y1 + px(12), text='0', font=FONTS['small'], fill=MUTED)
        c.create_text(x1, y1 + px(12), text='1', font=FONTS['small'], fill=MUTED)
    return fn


def draw_scatter(xs: np.ndarray, ys: np.ndarray, ylabel: str = '', ymin: float = 0.0, ymax: float = 1.0):
    def fn(c: Chart, x0, y0, x1, y1):
        size = min(x1 - x0, y1 - y0)
        x1 = x0 + size if ymin == 0 and ymax == 1 else x1
        c.create_rectangle(x0, y0, x1, y1, outline=AXIS)
        w, h = int(x1 - x0), int(y1 - y0)
        img = np.full((h, w, 3), 252, np.uint8)
        px_ = np.clip(((xs - 0) / 1 * (w - 1)).astype(int), 0, w - 1)
        py_ = np.clip(((ymax - ys) / (ymax - ymin) * (h - 1)).astype(int), 0, h - 1)
        img[py_, px_] = (42, 120, 214)
        c._img = ImageTk.PhotoImage(Image.fromarray(img))
        c.create_image(x0, y0, image=c._img, anchor='nw')
        c.create_text(x0 - px(4), y1, text=f'{ymin:g}', anchor='e', font=FONTS['small'], fill=MUTED)
        c.create_text(x0 - px(4), y0, text=f'{ymax:g}', anchor='e', font=FONTS['small'], fill=MUTED)
        if ylabel:
            c.create_text(x0 + px(4), y1 + px(13), text=ylabel, anchor='w', font=FONTS['small'], fill=INK_2)
    return fn


def draw_bits(bits: np.ndarray, side: int = 128):
    bits = bits[:side * side]
    img = np.where(bits.reshape(-1, side) == 1, 30, 245).astype(np.uint8)

    def fn(c: Chart, x0, y0, x1, y1):
        size = int(min(x1 - x0, y1 - y0))
        pic = Image.fromarray(img).resize((size, size * img.shape[0] // side), Image.NEAREST)
        c._img = ImageTk.PhotoImage(pic)
        c.create_image(x0, y0, image=c._img, anchor='nw')
    return fn


def draw_pvalues(results):
    def fn(c: Chart, x0, y0, x1, y1):
        n = len(results)
        row = (y1 - y0) / n
        lx = x0 + px(230)
        # шкала: −lg p от 0 до 10 (p = 1 … 10⁻¹⁰)
        for k, label in [(0, '1'), (2, '0,01 = α'), (5, '10⁻⁵'), (10, '≤10⁻¹⁰')]:
            x = lx + (x1 - lx) * k / 10
            c.create_line(x, y0, x, y1, fill=CRITICAL if k == 2 else GRID, dash=(4, 3) if k == 2 else ())
            c.create_text(x, y1 + px(10), text=label, font=FONTS['small'], fill=CRITICAL if k == 2 else MUTED)
        for i, r in enumerate(results):
            y = y0 + i * row + row / 2
            c.create_text(lx - px(8), y, text=r.name[:34], anchor='e', font=FONTS['small'], fill=INK)
            v = min(10.0, -np.log10(max(r.p_value, 1e-300)))
            c.create_rectangle(lx, y - row * 0.32, lx + (x1 - lx) * v / 10 + 2, y + row * 0.32,
                               fill=GOOD if r.passed else CRITICAL, width=0)
    return fn


# ==========================================================================
# Выбор датчика (общий для вкладок)
# ==========================================================================

class GeneratorPicker(ttk.Frame):
    def __init__(self, master, app: App) -> None:
        super().__init__(master)
        self.app = app
        ttk.Label(self, text='Датчик', style='H.TLabel').grid(row=0, column=0, sticky='w')
        box = ttk.Combobox(self, textvariable=app.gen_name, values=list(G.CATALOG.values()) + [CUSTOM],
                           state='readonly', width=34)
        box.grid(row=0, column=1, columnspan=3, sticky='w', padx=px(8), pady=px(2))
        box.bind('<<ComboboxSelected>>', lambda e: self.update_custom())
        ttk.Label(self, text='Зерно (seed)').grid(row=1, column=0, sticky='w')
        ttk.Entry(self, textvariable=app.seed, width=14, font=FONTS['mono']).grid(row=1, column=1, sticky='w',
                                                                                    padx=px(8), pady=px(2))
        self.custom = ttk.Frame(self)
        for i, (label, var) in enumerate((('a', app.a), ('c', app.c), ('m', app.m))):
            ttk.Label(self.custom, text=label).grid(row=0, column=2 * i, padx=(0 if i == 0 else px(8), px(4)))
            ttk.Entry(self.custom, textvariable=var, width=12, font=FONTS['mono']).grid(row=0, column=2 * i + 1)
        self.update_custom()

    def update_custom(self) -> None:
        if self.app.gen_name.get() == CUSTOM:
            self.custom.grid(row=2, column=0, columnspan=4, sticky='w', pady=px(4))
        else:
            self.custom.grid_forget()


# ==========================================================================
# Вкладка 1. Генератор
# ==========================================================================

class GeneratorTab(ttk.Frame):
    def __init__(self, master, app: App) -> None:
        super().__init__(master, padding=px(10))
        self.app = app
        paned = ttk.PanedWindow(self, orient='horizontal')
        paned.pack(fill='both', expand=True)
        left = ttk.Frame(paned, padding=(px(6), px(6), px(14), px(6)))
        GeneratorPicker(left, app).pack(anchor='w')
        row = ttk.Frame(left)
        row.pack(anchor='w', pady=(px(6), px(8)))
        ttk.Label(row, text='Чисел для графиков').pack(side='left')
        self.count = tk.StringVar(value='20000')
        ttk.Combobox(row, textvariable=self.count, values=['1000', '5000', '20000', '100000'], width=8).pack(
            side='left', padx=px(8))
        ttk.Button(row, text='Сгенерировать', style='Accent.TButton', command=self.generate).pack(side='left')
        frame, self.doc = scrolled(left, RichText, width=60)
        frame.pack(fill='both', expand=True)
        right = ttk.Frame(paned)
        self.hist = Chart(right, 'Гистограмма чисел uₙ (20 интервалов)', height=px(230))
        self.hist.pack(fill='x', pady=(0, px(6)))
        bottom = ttk.Frame(right)
        bottom.pack(fill='both', expand=True)
        self.scatter = Chart(bottom, 'Пары (uₙ, uₙ₊₁)')
        self.scatter.pack(side='left', fill='both', expand=True, padx=(0, px(6)))
        self.bitmap = Chart(bottom, 'Биты потока 128×128')
        self.bitmap.pack(side='left', fill='both', expand=True)
        self.bit_mode = tk.StringVar(value='поток бит')
        mode = ttk.Combobox(right, textvariable=self.bit_mode, state='readonly', width=22,
                            values=['поток бит', 'младший бит чисел'])
        mode.pack(anchor='e', pady=(px(4), 0))
        mode.bind('<<ComboboxSelected>>', lambda e: self.generate())
        paned.add(left, weight=1)
        paned.add(right, weight=1)
        self.after(100, self.generate)

    def generate(self) -> None:
        try:
            n = int(self.count.get())
            gen = self.app.make_generator()
            self.doc.render(explain.generator_doc(self.app.make_generator()))
        except (ValueError, KeyError) as e:
            messagebox.showwarning('Датчик', str(e))
            return
        nums = gen.numbers(n)
        u = np.array(nums, dtype=np.float64) / gen.modulus
        self.hist.set(draw_histogram(u))
        k = min(len(u) - 1, 6000)
        self.scatter.set(draw_scatter(u[:k], u[1:k + 1], 'по горизонтали uₙ, по вертикали uₙ₊₁'))
        if self.bit_mode.get() == 'поток бит':
            bits = np.array(self.app.make_generator().bits(128 * 128), dtype=np.int8)
            title = 'Биты потока 128×128'
        else:
            m, kb = gen.modulus, gen.word_bits
            g2 = self.app.make_generator()
            bits = np.array([((g2.next() << kb) // m) & 1 for _ in range(128 * 128)], dtype=np.int8)
            title = 'Младший бит чисел 128×128'
        self.bitmap.set(draw_bits(bits), title)


# ==========================================================================
# Вкладка 2. Проверка качества
# ==========================================================================

class TestsTab(ttk.Frame):
    def __init__(self, master, app: App) -> None:
        super().__init__(master, padding=px(10))
        self.app = app
        paned = ttk.PanedWindow(self, orient='horizontal')
        paned.pack(fill='both', expand=True)
        left = ttk.Frame(paned, padding=(px(6), px(6), px(14), px(6)))
        GeneratorPicker(left, app).pack(anchor='w')
        ttk.Label(left, text='Объём выборки', style='H.TLabel').pack(anchor='w', pady=(px(8), 0))
        self.size = tk.StringVar(value=list(SIZES)[0])
        ttk.Combobox(left, textvariable=self.size, values=list(SIZES), state='readonly', width=40).pack(
            anchor='w', pady=px(2))
        self.btn = ttk.Button(left, text='Запустить тесты', style='Accent.TButton', command=self.run)
        self.btn.pack(anchor='w', pady=(px(8), px(8)))
        ttk.Label(left, style='Muted.TLabel', wraplength=px(420), justify='left',
                  text='Полоса — величина −lg p: чем длиннее, тем менее вероятно такое отклонение у случайной '
                       'последовательности. Красная — p < α = 0,01, тест не пройден.').pack(anchor='w')
        self.chart = Chart(left, 'p-значения тестов', height=px(470), width=px(520))
        self.chart.pack(fill='both', expand=True, pady=(px(6), 0))
        frame, self.doc = scrolled(paned, RichText)
        paned.add(left, weight=0)
        paned.add(frame, weight=1)

    def run(self) -> None:
        try:
            gen = self.app.make_generator()
        except (ValueError, KeyError) as e:
            messagebox.showwarning('Датчик', str(e))
            return
        n_num, n_bits = SIZES[self.size.get()]
        self.btn.configure(state='disabled', text='Считаю…')

        def done(results):
            self.btn.configure(state='normal', text='Запустить тесты')
            self.doc.render(explain.tests_doc(gen.name, results, n_num, n_bits))
            self.chart.set(draw_pvalues(results))

        def fail(e):
            self.btn.configure(state='normal', text='Запустить тесты')
            messagebox.showerror('Тесты', str(e))

        self.app.bg.start(lambda: st.run_battery(gen, n_num, n_bits), done, fail)


# ==========================================================================
# Вкладка 3. Сравнение
# ==========================================================================

class CompareTab(ttk.Frame):
    SHORT = ['freq', 'block', 'runs', 'long', 'cusum', 'apen', 'χ²', 'KS', 'пары', 'тройки', 'покер', 'корр', 'π',
             'мл.бит']

    def __init__(self, master, app: App) -> None:
        super().__init__(master, padding=px(10))
        self.app = app
        top = ttk.Frame(self)
        top.pack(fill='x')
        self.btn = ttk.Button(top, text='Сравнить все датчики', style='Accent.TButton', command=self.run)
        self.btn.pack(side='left')
        ttk.Label(top, style='Muted.TLabel', text='   Выборка 20 000 чисел и 200 000 бит, α = 0,01. «+» — тест '
                                                  'пройден, «−» — нет. Линейная сложность — по 400 битам (у '
                                                  'случайной последовательности ≈ 200).').pack(side='left')
        cols = ['gen'] + self.SHORT + ['total', 'lc']
        self.tree = ttk.Treeview(self, columns=cols, show='headings', height=len(G.CATALOG))
        self.tree.heading('gen', text='Датчик')
        self.tree.column('gen', width=px(220), anchor='w')
        for c in self.SHORT:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=px(46), anchor='center')
        self.tree.heading('total', text='Итого')
        self.tree.column('total', width=px(60), anchor='center')
        self.tree.heading('lc', text='Лин. сложн.')
        self.tree.column('lc', width=px(80), anchor='center')
        self.tree.tag_configure('bad', background=CRITICAL_LIGHT)
        self.tree.tag_configure('good', background=GOOD_LIGHT)
        self.tree.pack(fill='x', pady=(px(8), px(8)))
        charts = ttk.Frame(self)
        charts.pack(fill='both', expand=True)
        self.c1 = Chart(charts, 'RANDU: 9uₖ − 6uₖ₊₁ + uₖ₊₂')
        self.c1.pack(side='left', fill='both', expand=True, padx=(0, px(6)))
        self.c2 = Chart(charts, 'MT19937: то же выражение')
        self.c2.pack(side='left', fill='both', expand=True)
        self.after(150, self.draw_planes)

    def draw_planes(self) -> None:
        for chart, key in ((self.c1, 'randu'), (self.c2, 'mt')):
            u = np.array(G.make(key, 1).uniforms(30000))
            v = properties.randu_planes(u)
            chart.set(draw_scatter(u[:-2], v, 'по горизонтали uₖ; у RANDU все точки — на 15 линиях-плоскостях',
                                   -6, 10))

    def run(self) -> None:
        self.btn.configure(state='disabled', text='Считаю…')

        def work():
            rows = []
            for key, name in G.CATALOG.items():
                res = st.run_battery(G.make(key, 12345), 20_000, 200_000)
                lc = properties.linear_complexity(G.make(key, 12345).bits(400))
                rows.append((name, res, lc))
            return rows

        def done(rows):
            self.btn.configure(state='normal', text='Сравнить все датчики')
            self.tree.delete(*self.tree.get_children())
            for name, res, lc in rows:
                passed = sum(r.passed for r in res)
                vals = [name] + ['+' if r.passed else '−' for r in res] + [f'{passed}/{len(res)}', lc]
                tag = 'good' if passed == len(res) and lc > 150 else 'bad' if passed < len(res) - 1 else ''
                self.tree.insert('', 'end', values=vals, tags=(tag,))

        def fail(e):
            self.btn.configure(state='normal', text='Сравнить все датчики')
            messagebox.showerror('Сравнение', str(e))

        self.app.bg.start(work, done, fail)


# ==========================================================================
# Главное окно
# ==========================================================================

class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        global SCALE
        SCALE = max(1.0, self.winfo_fpixels('1i') / 96)
        FONTS.update(
            ui=tkfont.Font(family='Segoe UI', size=10),
            small=tkfont.Font(family='Segoe UI', size=9),
            bold=tkfont.Font(family='Segoe UI Semibold', size=10),
            h1=tkfont.Font(family='Segoe UI Semibold', size=14),
            mono=tkfont.Font(family='Consolas', size=10),
        )
        self.title('ЛР №5 — Генераторы псевдослучайных чисел и проверка их качества')
        width = min(px(1280), self.winfo_screenwidth() - px(40))
        height = min(px(840), self.winfo_screenheight() - px(90))
        self.geometry(f'{width}x{height}+{px(10)}+{px(10)}')
        self.minsize(min(px(1000), width), min(px(620), height))
        self.configure(background=BG)
        self.setup_style()
        self.bg = Background(self)
        self.gen_name = tk.StringVar(value=G.CATALOG['mt'])
        self.seed = tk.StringVar(value='12345')
        self.a, self.c, self.m = tk.StringVar(value='13'), tk.StringVar(value='7'), tk.StringVar(value='64')
        notebook = ttk.Notebook(self)
        self.gen_tab = GeneratorTab(notebook, self)
        self.tests_tab = TestsTab(notebook, self)
        self.compare_tab = CompareTab(notebook, self)
        notebook.add(self.gen_tab, text='Генератор')
        notebook.add(self.tests_tab, text='Проверка качества')
        notebook.add(self.compare_tab, text='Сравнение')
        notebook.pack(fill='both', expand=True, padx=px(10), pady=px(10))
        self.notebook = notebook

    def make_generator(self) -> G.Generator:
        seed = int(self.seed.get())
        name = self.gen_name.get()
        if name == CUSTOM:
            g = G.LCG(int(self.a.get()), int(self.c.get()), int(self.m.get()), seed)
            return g
        key = next(k for k, v in G.CATALOG.items() if v == name)
        return G.make(key, seed)

    def setup_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', background=BG, foreground=INK, font=FONTS['ui'])
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=INK)
        style.configure('H.TLabel', font=FONTS['bold'])
        style.configure('Muted.TLabel', foreground=INK_2, font=FONTS['small'])
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', padding=(px(16), px(6)), font=FONTS['bold'])
        style.map('TNotebook.Tab', background=[('selected', SURFACE), ('!selected', BG)])
        style.configure('TButton', padding=(px(12), px(5)))
        style.configure('Accent.TButton', background=ACCENT, foreground='white', bordercolor=ACCENT_DARK)
        style.map('Accent.TButton', background=[('disabled', '#9ec5f4'), ('active', ACCENT_DARK)],
                  foreground=[('disabled', 'white')])
        style.configure('Treeview', background=SURFACE, fieldbackground=SURFACE, rowheight=px(24))
        style.configure('Treeview.Heading', font=FONTS['bold'], background=BG)
        style.configure('TPanedwindow', background=BG)


def main() -> None:
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    App().mainloop()


if __name__ == '__main__':
    main()
