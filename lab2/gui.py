"""Графический интерфейс архиватора ЛР №2 (tkinter входит в стандартный Python).

Запуск из папки lab2:   python gui.py     (или двойной щелчок по start_gui.bat)

Вкладки:
  «Архиватор»          — сжать или распаковать файл выбранным методом;
  «Сравнение методов»  — прогнать все методы на нескольких файлах и сравнить;
  «Как это работает»   — пошаговая демонстрация алгоритма на короткой строке.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from math import floor, log10
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from packer import container, explain, stats
from packer.fmt import human, num, pct
from packer.methods import AUTO, METHODS

APP_DIR = Path(__file__).resolve().parent
TEST_FILES = APP_DIR / 'test_files'

# Палитра (светлая тема)
BG = '#f3f3f1'            # фон окна
SURFACE = '#fcfcfb'       # фон графиков и текста
INK = '#0b0b0b'           # основной текст
INK_2 = '#52514e'         # второстепенный текст
MUTED = '#898781'         # подписи осей
GRID = '#e1e0d9'          # линии сетки
AXIS = '#c3c2b7'          # оси, рёбра деревьев
GOOD = '#0ca30c'          # статус «файл уменьшился»
GOOD_TEXT = '#006300'
CRITICAL = '#d03b3b'      # статус «файл увеличился»
ACCENT = '#2a78d6'        # основной синий
ACCENT_DARK = '#256abf'
ACCENT_LIGHT = '#cde2fb'
ORANGE = '#eb6834'

SCALE = 1.0               # множитель размеров для экранов с высоким DPI
FONTS: dict[str, tkfont.Font] = {}


def px(value: float) -> int:
    return int(round(value * SCALE))


def nice_step(max_value: float, ticks: int = 5) -> float:
    """Красивый шаг делений оси: 1, 2, 2.5, 5 × 10^k."""
    raw = max_value / ticks
    magnitude = 10 ** floor(log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * magnitude:
            return m * magnitude
    return 10 * magnitude


def rounded_bar(canvas: tk.Canvas, x0, y_top, x1, y_base, color: str, r: int = 4) -> None:
    """Столбик со скруглённым верхом (4 px) и прямым основанием."""
    r = min(px(r), (x1 - x0) / 2, max(0, y_base - y_top))
    if r < 1:
        canvas.create_rectangle(x0, y_top, x1, y_base, fill=color, width=0)
        return
    canvas.create_rectangle(x0, y_top + r, x1, y_base, fill=color, width=0)
    canvas.create_rectangle(x0 + r, y_top, x1 - r, y_top + r, fill=color, width=0)
    canvas.create_oval(x0, y_top, x0 + 2 * r, y_top + 2 * r, fill=color, width=0)
    canvas.create_oval(x1 - 2 * r, y_top, x1, y_top + 2 * r, fill=color, width=0)


class Background:
    """Выполняет долгую работу в отдельном потоке, чтобы окно не «зависало»."""

    def __init__(self, widget: tk.Misc) -> None:
        self.widget = widget

    def start(self, work, on_done, on_error, on_progress=None) -> None:
        q: queue.Queue = queue.Queue()

        def target():
            try:
                q.put(('done', work(lambda *a: q.put(('progress', a)))))
            except Exception as e:  # noqa: BLE001 — показываем любую ошибку пользователю
                q.put(('error', e))

        def poll():
            try:
                while True:
                    kind, value = q.get_nowait()
                    if kind == 'progress':
                        if on_progress:
                            on_progress(*value)
                    else:
                        (on_done if kind == 'done' else on_error)(value)
                        return
            except queue.Empty:
                self.widget.after(40, poll)

        threading.Thread(target=target, daemon=True).start()
        self.widget.after(40, poll)


class RichText(tk.Text):
    """Текстовое поле с заголовками, таблицами и формулами (только для чтения).

    Моноширинный шрифт — только для строк из нулей и единиц: в Consolas
    кириллическая «б» похожа на цифру «6», и запись LZW «1б» читалась бы как «16».
    """

    def __init__(self, master, **kw) -> None:
        super().__init__(master, wrap='word', relief='flat', bg=SURFACE, fg=INK,
                         padx=px(16), pady=px(12), font=FONTS['ui'], highlightthickness=0, **kw)
        self.tag_configure('h1', font=FONTS['h1'], spacing3=px(6))
        self.tag_configure('h2', font=FONTS['bold'], spacing1=px(12), spacing3=px(4))
        self.tag_configure('th', font=FONTS['bold'], spacing3=px(3))
        self.tag_configure('mono', font=FONTS['mono'], lmargin1=px(10), lmargin2=px(10))
        self.tag_configure('formula', lmargin1=px(10), lmargin2=px(24), spacing1=px(2))
        self.tag_configure('muted', foreground=INK_2)
        self.tag_configure('good', foreground=GOOD_TEXT)
        self.tag_configure('bad', foreground=CRITICAL)
        self._tables = 0

    def clear(self) -> None:
        self.configure(state='normal')
        self.delete('1.0', 'end')

    def h1(self, text: str) -> None:
        self.insert('end', text + '\n', ('h1',))

    def h2(self, text: str) -> None:
        self.insert('end', text + '\n', ('h2',))

    def p(self, text: str, *tags: str) -> None:
        self.insert('end', text + '\n', tags)

    def formula(self, text: str, *tags: str) -> None:
        self.insert('end', text + '\n', ('formula',) + tags)

    def mono(self, text: str) -> None:
        self.insert('end', text + '\n', ('mono',))

    def table(self, rows: list[tuple], right: set[int] = frozenset()) -> None:
        """Таблица на позициях табуляции; right — номера столбцов с выравниванием вправо."""
        ui, bold = FONTS['ui'], FONTS['bold']
        widths = [max([bold.measure(str(rows[0][i]))] + [ui.measure(str(row[i])) for row in rows[1:]])
                  for i in range(len(rows[0]))]
        margin, gap = px(10), px(22)
        tabs, x = [], margin
        for i, w in enumerate(widths):
            if i in right:
                tabs += [x + w, 'right']
            elif i:
                tabs += [x, 'left']
            x += w + gap
        self._tables += 1
        tag = f'table{self._tables}'
        self.tag_configure(tag, tabs=tabs, lmargin1=margin, lmargin2=margin)
        for k, row in enumerate(rows):
            line = ('\t' if 0 in right else '') + '\t'.join(str(c) for c in row)
            self.insert('end', line + '\n', (tag, 'th') if k == 0 else (tag,))

    def done(self) -> None:
        self.configure(state='disabled')
        self.see('1.0')


def scrolled(master, widget_cls, **kw):
    """Виджет с вертикальной прокруткой в общей рамке."""
    frame = ttk.Frame(master)
    widget = widget_cls(frame, **kw)
    bar = ttk.Scrollbar(frame, orient='vertical', command=widget.yview)
    widget.configure(yscrollcommand=bar.set)
    widget.pack(side='left', fill='both', expand=True)
    bar.pack(side='right', fill='y')
    return frame, widget


# ==========================================================================
# Вкладка 1. Архиватор
# ==========================================================================

class ArchiverTab(ttk.Frame):
    def __init__(self, master, app: App) -> None:
        super().__init__(master, padding=px(16))
        self.app = app
        self.path = tk.StringVar()
        self.method = tk.StringVar(value='huffman')
        self.columnconfigure(0, weight=1)

        ttk.Label(self, text='1. Файл', style='H.TLabel').grid(row=0, column=0, sticky='w')
        row = ttk.Frame(self)
        row.grid(row=1, column=0, sticky='ew', pady=(px(4), px(14)))
        ttk.Entry(row, textvariable=self.path, font=FONTS['ui']).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Выбрать файл…', command=self.browse).pack(side='left', padx=(px(8), 0))

        ttk.Label(self, text='2. Метод сжатия', style='H.TLabel').grid(row=2, column=0, sticky='w')
        box = ttk.Frame(self)
        box.grid(row=3, column=0, sticky='w', pady=(px(4), px(14)))
        options = [(m.key, m.title, m.summary) for m in METHODS.values()]
        options.append((AUTO, 'Авто', 'сжать всеми методами и оставить самый маленький результат'))
        for i, (key, title, summary) in enumerate(options):
            ttk.Radiobutton(box, text=title, value=key, variable=self.method).grid(
                row=i, column=0, sticky='w', pady=px(1))
            ttk.Label(box, text='— ' + summary, style='Muted.TLabel').grid(
                row=i, column=1, sticky='w', padx=(px(10), 0))

        ttk.Label(self, text='3. Действие', style='H.TLabel').grid(row=4, column=0, sticky='w')
        actions = ttk.Frame(self)
        actions.grid(row=5, column=0, sticky='w', pady=(px(6), px(16)))
        self.btn_pack = ttk.Button(actions, text='Сжать  →  .lab2', style='Accent.TButton', command=self.compress)
        self.btn_pack.pack(side='left')
        self.btn_unpack = ttk.Button(actions, text='Распаковать .lab2', command=self.decompress)
        self.btn_unpack.pack(side='left', padx=(px(8), 0))
        self.progress = ttk.Progressbar(actions, mode='indeterminate', length=px(180))

        ttk.Label(self, text='Результат', style='H.TLabel').grid(row=6, column=0, sticky='w')
        tiles = ttk.Frame(self)
        tiles.grid(row=7, column=0, sticky='ew', pady=(px(6), px(4)))
        self.tiles = []
        for i in range(4):
            tiles.columnconfigure(i, weight=1, uniform='tile')
            tile = ttk.Frame(tiles, style='Tile.TFrame', padding=(px(12), px(8)))
            tile.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else px(8), 0))
            label = ttk.Label(tile, text='—', style='TileLabel.TLabel')
            value = ttk.Label(tile, text='', style='TileValue.TLabel')
            label.pack(anchor='w')
            value.pack(anchor='w')
            self.tiles.append((label, value))
        self.meter = tk.Canvas(self, height=px(64), bg=SURFACE, highlightthickness=0)
        self.meter.grid(row=8, column=0, sticky='ew', pady=(px(4), px(10)))
        self.meter.bind('<Configure>', lambda e: self.draw_meter())
        self.meter_data = None

        frame, self.log = scrolled(self, tk.Text, height=7, wrap='word', relief='flat', bg=SURFACE,
                                   font=FONTS['ui'], padx=px(10), pady=px(6), highlightthickness=0)
        self.log.tag_configure('good', foreground=GOOD_TEXT)
        self.log.tag_configure('bad', foreground=CRITICAL)
        self.log.configure(state='disabled')
        frame.grid(row=9, column=0, sticky='nsew')
        self.rowconfigure(9, weight=1)
        self.write_log('Выберите файл и метод, нажмите «Сжать». Готовый архив <имя>.lab2 появится рядом с файлом; '
                       'его можно сразу распаковать кнопкой «Распаковать» — программа проверит CRC-32.')

    # --- действия ---
    def browse(self) -> None:
        start = TEST_FILES if TEST_FILES.exists() else APP_DIR
        name = filedialog.askopenfilename(initialdir=start, title='Файл для сжатия или архив .lab2')
        if name:
            self.path.set(str(Path(name)))

    def selected_file(self) -> Path | None:
        path = Path(self.path.get().strip().strip('"'))
        if not path.is_file():
            messagebox.showwarning('Нет файла', 'Сначала выберите существующий файл.')
            return None
        return path

    def set_busy(self, busy: bool) -> None:
        state = 'disabled' if busy else 'normal'
        self.btn_pack.configure(state=state)
        self.btn_unpack.configure(state=state)
        if busy:
            self.progress.pack(side='left', padx=(px(16), 0))
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()

    def compress(self) -> None:
        path = self.selected_file()
        if not path:
            return
        method = self.method.get()
        self.set_busy(True)
        self.app.bg.start(lambda report: container.compress_file(path, None, method),
                          self.on_compressed, self.on_error)

    def decompress(self) -> None:
        path = self.selected_file()
        if not path:
            return
        self.set_busy(True)
        self.app.bg.start(lambda report: container.decompress_file(path), self.on_decompressed, self.on_error)

    # --- результаты ---
    def on_compressed(self, r: container.Result) -> None:
        self.set_busy(False)
        shrunk = r.archive_size < r.original_size
        self.set_tiles([('Исходный файл', f'{human(r.original_size)} Б'),
                        ('Архив .lab2', f'{human(r.archive_size)} Б'),
                        ('Размер архива', pct(r.percent) if r.original_size else '—'),
                        ('Коэффициент сжатия', f'k = {num(r.ratio, 3)}' if r.original_size else '—')])
        self.meter_data = (r.original_size, r.archive_size, 'исходный файл', 'архив')
        self.draw_meter()
        verdict = 'файл уменьшился' if shrunk else 'файл УВЕЛИЧИЛСЯ'
        self.write_log(f'✔ Сжатие ({r.method.title}): {r.source.name} {human(r.original_size)} Б → '
                       f'{r.target.name} {human(r.archive_size)} Б — {verdict}; {num(r.seconds, 3)} с',
                       'good' if shrunk else 'bad')
        self.path.set(str(r.target))  # теперь можно сразу нажать «Распаковать»

    def on_decompressed(self, r: container.Result) -> None:
        self.set_busy(False)
        self.set_tiles([('Архив', f'{human(r.archive_size)} Б'),
                        ('Восстановлено', f'{human(r.original_size)} Б'),
                        ('Метод', r.method.title),
                        ('Проверка CRC-32', 'совпала ✓')])
        self.meter_data = (r.original_size, r.archive_size, 'восстановленный файл', 'архив')
        self.draw_meter()
        self.write_log(f'✔ Распаковка ({r.method.title}): {r.source.name} → {r.target.name}, '
                       f'{human(r.original_size)} Б; CRC-32 совпала — данные восстановлены без потерь; '
                       f'{num(r.seconds, 3)} с', 'good')

    def on_error(self, error: Exception) -> None:
        self.set_busy(False)
        self.write_log(f'✖ Ошибка: {error}', 'bad')
        messagebox.showerror('Ошибка', str(error))

    def set_tiles(self, items: list[tuple[str, str]]) -> None:
        for (label, value), (text_label, text_value) in zip(self.tiles, items):
            label.configure(text=text_label)
            value.configure(text=text_value)

    def write_log(self, text: str, *tags: str) -> None:
        self.log.configure(state='normal')
        self.log.insert('end', text + '\n', tags)
        self.log.see('end')
        self.log.configure(state='disabled')

    def draw_meter(self) -> None:
        """Две полоски в одном масштабе: исходный размер и размер архива."""
        c = self.meter
        c.delete('all')
        if not self.meter_data:
            return
        original, archive, name_a, name_b = self.meter_data
        width = c.winfo_width()
        label_w = px(170)
        left, right = px(10), width - label_w - px(10)
        unit = (right - left) / max(original, archive, 1)
        for i, (size, name, color) in enumerate(((original, name_a, AXIS),
                                                 (archive, name_b, GOOD if archive < original else CRITICAL))):
            y = px(12) + i * px(26)
            c.create_rectangle(left, y, left + max(px(2), size * unit), y + px(14), fill=color, width=0)
            c.create_text(left + size * unit + px(8), y + px(7), anchor='w', fill=INK_2, font=FONTS['small'],
                          text=f'{name}: {human(size)} Б')


# ==========================================================================
# Вкладка 2. Сравнение методов
# ==========================================================================

class CompareTab(ttk.Frame):
    COLUMNS = [('file', 'Файл', 210, 'w'), ('size', 'Размер', 90, 'e'), ('h0', 'H₀', 60, 'e'),
               ('h1', 'H₁', 60, 'e'), ('limit', 'Предел n·H₀/8', 110, 'e')] + \
              [(m.key, m.title, 100, 'e') for m in METHODS.values()] + [('best', 'Лучший', 100, 'w')]

    def __init__(self, master, app: App) -> None:
        super().__init__(master, padding=px(12))
        self.app = app
        self.files: list[Path] = []
        self.results: dict[str, dict] = {}

        bar = ttk.Frame(self)
        bar.pack(fill='x')
        ttk.Button(bar, text='Добавить файлы…', command=self.add_files).pack(side='left')
        ttk.Button(bar, text='Тестовый набор', command=self.add_test_set).pack(side='left', padx=(px(6), 0))
        ttk.Button(bar, text='Очистить', command=self.clear).pack(side='left', padx=(px(6), 0))
        self.btn_run = ttk.Button(bar, text='▶  Сравнить методы', style='Accent.TButton', command=self.run)
        self.btn_run.pack(side='left', padx=(px(16), 0))
        self.status = ttk.Label(bar, text='', style='Muted.TLabel')
        self.status.pack(side='left', padx=(px(12), 0))

        table = ttk.Frame(self)
        table.pack(fill='both', expand=True, pady=(px(10), px(8)))
        self.tree = ttk.Treeview(table, columns=[c[0] for c in self.COLUMNS], show='headings', height=9)
        for key, title, width, anchor in self.COLUMNS:
            self.tree.heading(key, text=title, anchor=anchor)
            self.tree.column(key, width=px(width), anchor=anchor, stretch=(key == 'file'))
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.draw_charts())

        charts = ttk.Frame(self)
        charts.pack(fill='both', expand=True)
        charts.columnconfigure(0, weight=1, uniform='c')
        charts.columnconfigure(1, weight=1, uniform='c')
        charts.rowconfigure(0, weight=1)
        self.bars = tk.Canvas(charts, height=px(250), bg=SURFACE, highlightthickness=0)
        self.hist = tk.Canvas(charts, height=px(250), bg=SURFACE, highlightthickness=0)
        self.bars.grid(row=0, column=0, sticky='nsew', padx=(0, px(6)))
        self.hist.grid(row=0, column=1, sticky='nsew', padx=(px(6), 0))
        for canvas in (self.bars, self.hist):
            canvas.bind('<Configure>', lambda e: self.draw_charts())

        ttk.Label(self, style='Muted.TLabel', wraplength=px(1100), justify='left', text=(
            'В ячейках — размер архива в % от исходного файла: ▼ — файл уменьшился, ▲ — увеличился. '
            'H₀ — энтропия по частотам байтов, H₁ — с учётом предыдущего байта (бит/байт; '
            'на коротких файлах оценка H₁ занижена). '
            'Предел n·H₀/8 — меньше него посимвольные коды (Хаффман, Шеннон–Фано) сжать не могут; '
            'LZW может, потому что кодирует повторяющиеся цепочки.')).pack(fill='x', pady=(px(8), 0))

    # --- список файлов ---
    def add_files(self) -> None:
        names = filedialog.askopenfilenames(initialdir=TEST_FILES if TEST_FILES.exists() else APP_DIR,
                                            title='Файлы для сравнения методов')
        self.add_paths(Path(n) for n in names)

    def add_test_set(self) -> None:
        if not TEST_FILES.exists():
            messagebox.showinfo('Нет тестового набора', 'Запустите python tools/make_test_files.py')
            return
        self.add_paths(sorted(p for p in TEST_FILES.iterdir() if p.is_file() and p.suffix != '.lab2'))

    def add_paths(self, paths) -> None:
        for path in paths:
            if path not in self.files:
                self.files.append(path)
                self.tree.insert('', 'end', iid=str(path), values=[path.name] + [''] * (len(self.COLUMNS) - 1))
        self.status.configure(text=f'файлов: {len(self.files)} — нажмите «Сравнить методы»')

    def clear(self) -> None:
        self.files.clear()
        self.results.clear()
        self.tree.delete(*self.tree.get_children())
        self.status.configure(text='')
        self.draw_charts()

    # --- расчёт ---
    def run(self) -> None:
        if not self.files:
            self.add_test_set()
            if not self.files:
                return
        files = list(self.files)
        self.btn_run.configure(state='disabled')

        def work(report):
            results = {}
            for i, path in enumerate(files, 1):
                report(i, len(files), path.name)
                data = path.read_bytes()
                freqs = stats.frequencies(data)
                results[str(path)] = {'size': len(data), 'profile': stats.profile(data),
                                      'freqs': [freqs.get(b, 0) for b in range(256)],
                                      'rows': container.benchmark(data, path.name)}
            return results

        self.app.bg.start(work, self.on_done, self.on_error,
                          lambda i, n, name: self.status.configure(text=f'обработка {i} из {n}: {name}…'))

    def on_done(self, results: dict) -> None:
        self.btn_run.configure(state='normal')
        self.results.update(results)
        for key, res in results.items():
            size, prof = res['size'], res['profile']
            cells = []
            for row in res['rows']:
                if not size:
                    cells.append(f'{human(row.archive_size)} Б')
                else:
                    mark = '▼' if row.archive_size < size else '▲'
                    cells.append(f'{mark} {pct(stats.percent(size, row.archive_size))}' + ('' if row.ok else ' ОШИБКА'))
            best = min(r.archive_size for r in res['rows'])
            winners = ', '.join(r.method.title for r in res['rows'] if r.archive_size == best)
            limit = f'{human(prof.limit_bytes)} Б' if size else '—'
            self.tree.item(key, values=[Path(key).name, f'{human(size)} Б', num(prof.entropy),
                                        num(prof.cond_entropy), limit] + cells + [winners])
        self.status.configure(text=f'готово: файлов {len(results)}; все распаковки проверены по CRC-32')
        if results and not self.tree.selection():
            self.tree.selection_set(next(iter(results)))
        self.draw_charts()

    def on_error(self, error: Exception) -> None:
        self.btn_run.configure(state='normal')
        self.status.configure(text='')
        messagebox.showerror('Ошибка', str(error))

    # --- графики ---
    def current(self):
        sel = self.tree.selection()
        if sel and sel[0] in self.results:
            return Path(sel[0]).name, self.results[sel[0]]
        return None, None

    def draw_charts(self) -> None:
        name, res = self.current()
        self.draw_bars(name, res)
        self.draw_hist(name, res)

    def placeholder(self, canvas: tk.Canvas, text: str) -> None:
        canvas.create_text(canvas.winfo_width() / 2, canvas.winfo_height() / 2, text=text,
                           fill=MUTED, font=FONTS['ui'], width=canvas.winfo_width() - px(40), justify='center')

    def draw_bars(self, name, res) -> None:
        c = self.bars
        c.delete('all')
        if res is None:
            self.placeholder(c, 'Нажмите «Тестовый набор», затем «Сравнить методы»\n'
                                'и выберите строку таблицы')
            return
        size = res['size']
        c.create_text(px(14), px(14), anchor='nw', font=FONTS['bold'], fill=INK,
                      text=f'Размер архива, % от исходного — {name}')
        if not size:
            self.placeholder(c, 'Файл пустой: проценты не определены.\nАрхив состоит только из заголовка '
                                f'({min(r.archive_size for r in res["rows"])} Б).')
            return
        values = [(r.method.title, stats.percent(size, r.archive_size)) for r in res['rows']]
        limit = 100 * res['profile'].entropy / 8
        w, h = c.winfo_width(), c.winfo_height()
        left, right, top, bottom = px(52), w - px(16), px(66), h - px(34)
        # Легенда опорных линий — под заголовком, чтобы подписи не наезжали на столбики.
        small, ly = FONTS['small'], px(44)
        c.create_line(px(14), ly, px(40), ly, fill=INK_2)
        text_100 = '100 % — исходный размер'
        c.create_text(px(46), ly, anchor='w', text=text_100, fill=INK_2, font=small)
        x2 = px(46) + small.measure(text_100) + px(24)
        c.create_line(x2, ly, x2 + px(26), ly, fill=MUTED, dash=(4, 3))
        c.create_text(x2 + px(32), ly, anchor='w', fill=INK_2, font=small,
                      text=f'предел для посимвольных кодов n·H₀/8 = {pct(limit)}')
        vmax = max([110] + [v for _, v in values])
        step = nice_step(vmax)
        vmax = step * (int(vmax / step) + 1)
        y = lambda v: bottom - (bottom - top) * v / vmax  # noqa: E731
        tick = 0.0
        while tick <= vmax + 1e-9:
            c.create_line(left, y(tick), right, y(tick), fill=GRID)
            c.create_text(left - px(6), y(tick), anchor='e', fill=MUTED, font=FONTS['small'], text=f'{tick:g} %')
            tick += step
        c.create_line(left, y(0), right, y(0), fill=AXIS)
        slot = (right - left) / len(values)
        bar_w = min(px(24), slot * 0.5)
        for i, (title, value) in enumerate(values):
            cx = left + slot * (i + 0.5)
            rounded_bar(c, cx - bar_w / 2, y(value), cx + bar_w / 2, y(0), GOOD if value < 100 else CRITICAL)
            mark = '▼' if value < 100 else '▲'
            c.create_text(cx, y(value) - px(4), anchor='s', fill=INK_2, font=FONTS['small'], text=f'{mark} {pct(value)}')
            c.create_text(cx, bottom + px(8), anchor='n', fill=INK_2, font=FONTS['small'], text=title)
        c.create_line(left, y(100), right, y(100), fill=INK_2)
        c.create_line(left, y(limit), right, y(limit), fill=MUTED, dash=(4, 3))

    def draw_hist(self, name, res) -> None:
        c = self.hist
        c.delete('all')
        if res is None:
            self.placeholder(c, 'Здесь появится гистограмма частот байтов выбранного файла')
            return
        prof = res['profile']
        c.create_text(px(14), px(14), anchor='nw', font=FONTS['bold'], fill=INK,
                      text=f'Частоты байтов — H₀ = {num(prof.entropy)} бит/байт, различных байтов N = {prof.distinct}')
        if not res['size']:
            self.placeholder(c, 'Файл пустой')
            return
        w, h = c.winfo_width(), c.winfo_height()
        left, right, top, bottom = px(52), w - px(16), px(48), h - px(34)
        probs = [100 * f / res['size'] for f in res['freqs']]
        step = nice_step(max(probs), 4)
        vmax = step * (int(max(probs) / step) + 1)
        y = lambda v: bottom - (bottom - top) * v / vmax  # noqa: E731
        tick = 0.0
        while tick <= vmax + 1e-9:
            c.create_line(left, y(tick), right, y(tick), fill=GRID)
            c.create_text(left - px(6), y(tick), anchor='e', fill=MUTED, font=FONTS['small'], text=f'{tick:g} %')
            tick += step
        bw = (right - left) / 256
        for b, p in enumerate(probs):
            if p:
                x0 = left + b * bw
                c.create_rectangle(x0, y(p), x0 + max(1.0, bw - (1 if bw >= 3 else 0)), y(0), fill=ACCENT, width=0)
        c.create_line(left, y(0), right, y(0), fill=AXIS)
        for b in (0, 64, 128, 192, 255):
            x = left + (b + 0.5) * bw
            c.create_line(x, bottom, x, bottom + px(4), fill=AXIS)
            c.create_text(x, bottom + px(6), anchor='n', fill=MUTED, font=FONTS['small'], text=str(b))
        c.create_text(right, bottom + px(20), anchor='ne', fill=MUTED, font=FONTS['small'], text='значение байта')


# ==========================================================================
# Вкладка 3. Как это работает
# ==========================================================================

HUFFMAN_EXAMPLE = 'C' * 30 + 'E' * 25 + 'B' * 20 + 'F' * 10 + 'A' * 10 + 'D' * 5
PRESETS = {
    'Хаффман: пример из методички (A×10, B×20, C×30, D×5, E×25, F×10)': (HUFFMAN_EXAMPLE, 'huffman'),
    'Шеннон–Фано: те же данные из методички': (HUFFMAN_EXAMPLE, 'shannon'),
    'Шеннон–Фано хуже Хаффмана: частоты 35, 17, 17, 16, 15':
        ('a' * 35 + 'b' * 17 + 'c' * 17 + 'd' * 16 + 'e' * 15, 'shannon'),
    'Хаффман: «абракадабра»': ('абракадабра', 'huffman'),
    'LZW: пример из методички «абабвбабабааааааа»': ('абабвбабабааааааа', 'lzw'),
    'LZW: TOBEORNOTTOBEORTOBEORNOT': ('TOBEORNOTTOBEORTOBEORNOT', 'lzw'),
    'RLE: строка с 40 пробелами (пример из методички)': ('Строка текста' + ' ' * 40, 'rle'),
    'RLE: WWWWWWWWWWWWBWWWWWWWWWWWWBBB…':
        ('WWWWWWWWWWWWBWWWWWWWWWWWWBBBWWWWWWWWWWWWWWWWWWWWWWWWBWWWWWWWWWWWWWW', 'rle'),
    'RLE: текст без повторов — файл растёт': ('абракадабра', 'rle'),
}
MAX_DEMO = 400  # символов: на длинных сообщениях таблицы и дерево не помещаются


class ExplainTab(ttk.Frame):
    def __init__(self, master, app: App) -> None:
        super().__init__(master, padding=px(12))
        self.app = app
        self.message = tk.StringVar(value='абракадабра')
        self.method = tk.StringVar(value='huffman')
        self.preset = tk.StringVar()
        self.tree_root = None
        self.rle = None

        top = ttk.Frame(self)
        top.pack(fill='x')
        ttk.Label(top, text='Сообщение:').pack(side='left')
        entry = ttk.Entry(top, textvariable=self.message, font=FONTS['mono'])
        entry.pack(side='left', fill='x', expand=True, padx=(px(6), px(12)))
        entry.bind('<Return>', lambda e: self.show())
        ttk.Label(top, text='Пример:').pack(side='left')
        combo = ttk.Combobox(top, textvariable=self.preset, values=list(PRESETS), state='readonly', width=46)
        combo.pack(side='left', padx=(px(6), 0))
        combo.bind('<<ComboboxSelected>>', self.load_preset)

        row = ttk.Frame(self)
        row.pack(fill='x', pady=(px(8), px(8)))
        for key, title in (('huffman', 'Хаффман'), ('shannon', 'Шеннон–Фано'), ('lzw', 'LZW'), ('rle', 'RLE')):
            ttk.Radiobutton(row, text=title, value=key, variable=self.method,
                            command=self.show).pack(side='left', padx=(0, px(14)))
        ttk.Button(row, text='Показать по шагам', style='Accent.TButton', command=self.show).pack(side='left')

        panes = ttk.PanedWindow(self, orient='horizontal')
        panes.pack(fill='both', expand=True)
        left, self.text = scrolled(panes, RichText)
        panes.add(left, weight=5)
        right = ttk.Frame(panes)
        self.canvas = tk.Canvas(right, bg=SURFACE, highlightthickness=0)
        xs = ttk.Scrollbar(right, orient='horizontal', command=self.canvas.xview)
        ys = ttk.Scrollbar(right, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        ys.grid(row=0, column=1, sticky='ns')
        xs.grid(row=1, column=0, sticky='ew')
        panes.add(right, weight=4)
        self.canvas.bind('<Configure>', lambda e: self.redraw())
        self.after(100, self.show)

    def load_preset(self, _event=None) -> None:
        text, method = PRESETS[self.preset.get()]
        self.message.set(text)
        self.method.set(method)
        self.show()

    def show(self) -> None:
        text = self.message.get()
        t = self.text
        t.clear()
        self.tree_root, self.rle = None, None
        if not text:
            t.p('Введите сообщение или выберите пример.', 'muted')
            t.done()
            self.redraw()
            return
        cut = len(text) > MAX_DEMO
        text = text[:MAX_DEMO]
        method = self.method.get()
        if method in ('huffman', 'shannon'):
            self.render_prefix(explain.prefix_demo(text, method))
        elif method == 'lzw':
            self.render_lzw(explain.lzw_demo(text))
        else:
            self.render_rle(explain.rle_demo(text))
        if cut:
            t.p(f'\n(Сообщение обрезано до {MAX_DEMO} символов.)', 'muted')
        t.done()
        self.redraw()

    # --- Хаффман и Шеннон–Фано ---
    def render_prefix(self, d: explain.PrefixDemo) -> None:
        t, q, n = self.text, d.quality, len(d.text)
        t.h1('Код Хаффмана' if d.method == 'huffman' else 'Код Шеннона–Фано')
        t.p(f'Сообщение: «{explain.show(d.text)}» — n = {n} символов, различных символов N = {len(d.rows)}.')

        t.h2('Шаг 1. Частоты и вероятности символов')
        t.p('Первый проход по данным: считаем, сколько раз встречается каждый символ. '
            'Вероятность p = f / n; собственная информация символа I = −log₂p бит — '
            'чем реже символ, тем больше информации он несёт.', 'muted')
        t.table([('Символ', 'f', 'p = f/n', '−log₂p')] +
                [(r.symbol, r.freq, num(r.prob, 4), num(r.info, 3)) for r in d.rows], right={1, 2, 3})
        t.formula(f'H    = −Σ p·log₂p = {num(q.entropy)} бит/символ   (энтропия)')
        t.formula(f'Hmax = log₂N = log₂{len(d.rows)} = {num(q.max_entropy)} бит/символ')
        if q.max_entropy:
            t.formula(f'R    = 1 − H/Hmax = {num(1 - q.entropy / q.max_entropy)}   (избыточность)')

        if d.method == 'huffman':
            t.h2('Шаг 2. Строим дерево снизу вверх')
            t.p('Берём два узла с наименьшими частотами и объединяем их в новый узел с суммарной частотой. '
                'Повторяем, пока не останется один узел — корень. Дерево нарисовано справа: '
                'в кружках частоты, у листьев — символ и его код.', 'muted')
        else:
            t.h2('Шаг 2. Делим алфавит сверху вниз')
            t.p('Символы выписаны по убыванию частот. Делим список на две группы с как можно более близкими '
                'суммами частот: верхней группе приписываем 0, нижней — 1. Каждую группу делим так же, '
                'пока в группах не останется по одному символу. Дерево делений — справа.', 'muted')
        for step in d.steps:
            t.formula(step)
        if not d.steps:
            t.p('В сообщении один различный символ — делить нечего, его код «0».', 'muted')

        t.h2('Шаг 3. Коды символов')
        t.p('Код — путь от корня до листа: влево — 0, вправо — 1. Символы стоят только в листьях, '
            'поэтому ни один код не является началом другого — код префиксный и декодируется однозначно. '
            'В архиве используются канонические коды той же длины: тогда достаточно хранить только длины.',
            'muted')
        t.table([('Символ', 'f', 'Код', 'l', 'p·l', 'Канонический')] +
                [(r.symbol, r.freq, r.code, len(r.code), num(r.prob * len(r.code), 3), r.canonical)
                 for r in d.rows], right={1, 3, 4})

        t.h2('Шаг 4. Насколько хорош код')
        ok = q.entropy - 1e-9 <= q.avg_length < q.entropy + 1
        t.formula(f'lср = Σ p·l = {num(q.avg_length)} бит/символ   (средняя длина кода)')
        t.formula(f'H ≤ lср < H + 1:  {num(q.entropy)} ≤ {num(q.avg_length)} < {num(q.entropy + 1)}  '
                  + ('✓ (теорема Шеннона)' if ok else '✗'), 'good' if ok else 'bad')
        t.formula(f'Равномерный код: ⌈log₂N⌉ = {d.uniform_bits} бит/символ')
        t.formula(f'Kсс = Hmax / lср = {num(q.k_cc)}   (коэффициент статистического сжатия)')
        t.formula(f'Kоэ = H / lср = {num(q.k_oe)}   (коэффициент относительной эффективности, идеал — 1)')
        t.formula(f'Σ 2^(−l) = {num(d.kraft)} ≤ 1   (неравенство Крафта)')

        t.h2('Шаг 5. Кодируем сообщение')
        shown = 40
        t.mono(' '.join(d.codes[ch] for ch in d.text[:shown]) + (' …' if n > shown else ''))
        bits = len(d.encoded)
        t.p(f'Итого {bits} бит вместо {n} × 8 = {d.original_bits} бит — в {num(d.original_bits / bits, 2)} '
            f'раза меньше. В архив добавится ещё таблица длин кодов: 1 + 2·N = {1 + 2 * len(d.rows)} байт.')
        self.tree_root = d.tree

    # --- LZW ---
    def render_lzw(self, d: explain.LzwDemo) -> None:
        t, show, n = self.text, explain.show, len(d.text)
        t.h1('Алгоритм LZW (Лемпель — Зив — Велч)')
        t.p(f'Сообщение: «{show(d.text)}» — n = {n} символов.')

        t.h2('Шаг 1. Начальный словарь — алфавит сообщения')
        t.formula('     '.join(f'{show(ch)} = {code}' for ch, code in d.alphabet.items()))
        t.p('В архиваторе словарь изначально содержит все 256 возможных байтов (коды 0…255), '
            'код 256 — команда «очистить словарь», новые цепочки получают коды с 257.', 'muted')

        t.h2('Шаг 2. Кодирование')
        t.p('s — текущая цепочка (в столбце «sK» записан её код), K — следующий символ. Если цепочка sK '
            'уже есть в словаре — удлиняем: s = sK. Иначе выдаём код s, добавляем sK в словарь '
            'под новым номером и начинаем новую цепочку с K.', 'muted')
        rows = [('Символ K', 'sK', 'цепочка', 'Выход', 'Добавление в словарь')]
        for st in d.steps:
            rows.append((st.symbol or 'конец', st.sk, show(st.phrase),
                         '' if st.output is None else st.output,
                         f'{st.sk} ({st.added}) = «{show(st.phrase)}»' if st.added else ''))
        t.table(rows, right={3})
        t.formula('Выход кодера: ' + ' '.join(map(str, d.codes)) + f'   — {len(d.codes)} кодов')

        t.h2('Шаг 3. Декодирование')
        t.p('Распаковщик строит тот же словарь, но на шаг позже: цепочку «предыдущая + первый символ '
            'текущей» он добавляет, только прочитав следующий код. Поэтому словарь в архиве не хранится.',
            'muted')
        rows = [('Код', 'Выход', 'Добавление в словарь', '')]
        for st in d.decode_steps:
            rows.append((st.code, show(st.entry),
                         f'{st.added} = «{show(st.added_phrase)}»' if st.added else '—',
                         'кода ещё нет в словаре → предыдущая цепочка + её 1-й символ' if st.special else ''))
        t.table(rows, right={0})
        ok = d.decoded == d.text
        t.formula(f'Результат: «{show(d.decoded)}» ' + ('✓ совпадает с исходным' if ok else '✗ ошибка'),
                  'good' if ok else 'bad')

        t.h2('Шаг 4. Размер')
        t.formula(f'Исходно: {n} × 8 = {8 * n} бит')
        t.formula(f'Коды одинаковой длины: {len(d.codes)} × {d.fixed_width} = {len(d.codes) * d.fixed_width} бит '
                  f'(самый большой код {max(d.phrases)} → {d.fixed_width} бит)')
        t.formula(f'Коды переменной длины (по текущему размеру словаря): {d.variable_bits} бит')
        t.p('На коротком сообщении словарь не успевает «обучиться», и выигрыш небольшой. Чем длиннее данные '
            'и чем чаще в них повторяются цепочки, тем сильнее сжатие. Справа — словарь в виде дерева: '
            'каждая цепочка — путь от корня, в кружке её код.', 'muted')
        self.tree_root = explain.lzw_trie(d)

    # --- RLE ---
    def render_rle(self, d: explain.RleDemo) -> None:
        t = self.text
        t.h1('RLE — кодирование повторов')
        t.p(f'Сообщение: «{explain.show(d.text)}» — {d.original_size} байт (кодировка {d.encoding}).')

        t.h2('Шаг 1. Выбираем байт-флаг')
        t.p('Флаг — служебный байт со смыслом «размножить предыдущий байт». Берём самый редкий байт '
            'в данных: если он вообще не встречается, экранировать ничего не придётся.', 'muted')
        t.formula(f'{d.flag_label}; в данных встречается {d.flag_count} раз')

        t.h2('Шаг 2. Находим серии одинаковых символов')
        t.formula('   '.join(f'{ch}×{k}' for ch, k, _ in d.runs))

        t.h2('Шаг 3. Кодируем')
        t.p('Серия из L ≥ 4 одинаковых байтов b → три байта «b ⚑ L». Короткие серии (1–3 байта) '
            'остаются как есть: тройка заняла бы не меньше места. Сам байт-флаг в данных '
            'записывается как «⚑ 0». Схема — справа.', 'muted')
        t.formula('  |  '.join(tok.text for tok in d.tokens))

        t.h2('Шаг 4. Размер')
        tag = 'good' if d.packed_size < d.original_size else 'bad'
        t.formula(f'Было {d.original_size} байт → стало 1 (байт-флаг) + {d.packed_size - 1} = {d.packed_size} байт '
                  f'→ {pct(stats.percent(d.original_size, d.packed_size))} от исходного', tag)
        if d.packed_size >= d.original_size:
            t.p('Сообщение НЕ уменьшилось: длинных серий нет, а байт-флаг добавил 1 байт. RLE выгоден только '
                'для данных с длинными повторами — однотонные области картинок, пробелы, нули.', 'bad')
        self.rle = d

    # --- рисование ---
    def redraw(self) -> None:
        c = self.canvas
        c.delete('all')
        if self.tree_root is not None:
            self.draw_tree(self.tree_root)
        elif self.rle is not None:
            self.draw_rle(self.rle)
        _, _, x1, y1 = c.bbox('all') or (0, 0, 1, 1)
        c.configure(scrollregion=(0, 0, x1 + px(20), y1 + px(20)))  # от 0, чтобы не терять левый отступ
        c.xview_moveto(0)
        c.yview_moveto(0)

    def draw_tree(self, root: explain.DrawNode) -> None:
        c = self.canvas
        small, bold = FONTS['small'], FONTS['bold']
        captions = []

        def collect(node):
            captions.extend(node.caption.split('\n'))
            for _, child in node.children:
                collect(child)
        collect(root)
        r = px(15)
        side_captions = []  # подписи внутренних узлов рисуются справа от кружка

        def collect_side(node):
            if node.children and node.caption:
                side_captions.append(bold.measure(node.caption))
            for _, child in node.children:
                collect_side(child)
        collect_side(root)
        widest = max(max(bold.measure(s), FONTS['mono'].measure(s)) for s in captions)
        leaf_w = max([px(46), widest + px(12)] +
                     [w + 2 * r + px(16) for w in side_captions])
        level_h = px(68)
        positions = {}
        counter = [0]

        def place(node, depth):
            if node.children:
                xs = [place(child, depth + 1) for _, child in node.children]
                x = (xs[0] + xs[-1]) / 2
            else:
                x = counter[0]
                counter[0] += 1
            positions[id(node)] = (px(24) + x * leaf_w + leaf_w / 2, px(30) + depth * level_h)
            return x

        place(root, 0)
        width = px(48) + counter[0] * leaf_w
        offset = max(0, (c.winfo_width() - width) / 2)  # по центру, если дерево узкое

        def xy(node):
            x, y = positions[id(node)]
            return x + offset, y

        def edges(node):
            x0, y0 = xy(node)
            for label, child in node.children:
                x1, y1 = xy(child)
                c.create_line(x0, y0, x1, y1, fill=AXIS, width=px(1.5))
                side = -1 if x1 < x0 - 1 else 1  # «0»/левые ветки — слева от ребра, остальные — справа
                c.create_text((x0 + x1) / 2 + side * px(9), (y0 + y1) / 2 - px(3), text=label,
                              fill=ACCENT_DARK, font=bold)
                edges(child)

        def nodes(node):
            x, y = xy(node)
            leaf = node.leaf
            c.create_oval(x - r, y - r, x + r, y + r, fill=ACCENT_LIGHT if leaf else SURFACE,
                          outline=ACCENT if leaf else AXIS, width=px(1.5))
            c.create_text(x, y, text=node.text, fill=INK, font=small)
            if node.caption and node.children:  # внутренний узел: подпись справа, не на рёбрах
                c.create_text(x + r + px(5), y, anchor='w', text=node.caption, fill=INK, font=bold)
            elif node.caption:
                first, *rest = node.caption.split('\n')
                c.create_text(x, y + r + px(4), anchor='n', text=first, fill=INK, font=bold)
                if rest:
                    c.create_text(x, y + r + px(22), anchor='n', text='\n'.join(rest), fill=INK_2,
                                  font=FONTS['mono'])
            for _, child in node.children:
                nodes(child)

        edges(root)
        nodes(root)

    def draw_rle(self, d: explain.RleDemo) -> None:
        """Сверху — исходные данные и сжатый поток в одном масштабе (видно, насколько короче),
        снизу — сжатый поток побайтно: каждая клетка — один байт."""
        c = self.canvas
        small, bold = FONTS['small'], FONTS['bold']
        width = max(c.winfo_width(), px(300))
        left, gap = px(20), px(2)
        unit = min(px(14), (width - 2 * left) / max(d.original_size, d.packed_size))
        colors = {'flag': (ORANGE, 'white'), 'count': (ACCENT, 'white'), 'data': (GRID, INK)}

        def strip(y, title, blocks, h=px(30)):
            """Полоса из блоков; ширина блока пропорциональна числу байтов."""
            c.create_text(left, y - px(6), anchor='sw', text=title, fill=INK, font=bold)
            x = left
            for label, size, color, ink in blocks:
                w = max(size * unit, px(2))
                c.create_rectangle(x, y, x + max(w - gap, 1), y + h, fill=color, width=0)
                if label and small.measure(label) + px(6) < w - gap:  # подпись — только если помещается
                    c.create_text(x + (w - gap) / 2, y + h / 2, text=label, fill=ink, font=small)
                x += w

        strip(px(34), f'Исходные данные: {d.original_size} байт (серии одинаковых символов)',
              [(f'{ch}×{k}', size, GRID, INK) for ch, k, size in d.runs])
        strip(px(104), f'Сжатый поток в том же масштабе: {d.packed_size} байт',
              [('', 1, *colors[kind]) for _, kind in d.cells])

        y0 = px(178)
        c.create_text(left, y0 - px(6), anchor='sw', text='Сжатый поток побайтно (каждая клетка — 1 байт)',
                      fill=INK, font=bold)
        cell_w, cell_h = px(34), px(28)
        per_row = max(1, int((width - 2 * left + gap) // (cell_w + gap)))
        for k, (label, kind) in enumerate(d.cells):
            row, col = divmod(k, per_row)
            x, y = left + col * (cell_w + gap), y0 + row * (cell_h + gap)
            color, ink = colors[kind]
            c.create_rectangle(x, y, x + cell_w, y + cell_h, fill=color, width=0)
            c.create_text(x + cell_w / 2, y + cell_h / 2, text=label, fill=ink, font=small)

        y = y0 + ((len(d.cells) - 1) // per_row + 1) * (cell_h + gap) + px(14)
        for kind, label in (('data', 'байт данных — переписан как есть'),
                            ('flag', '⚑ — байт-флаг; первый байт потока сообщает, какой байт выбран флагом'),
                            ('count', 'счётчик L: размножить предыдущий байт до L штук; '
                                      'L = 0 — «флаг здесь обычный байт данных»')):
            c.create_rectangle(left, y, left + px(14), y + px(14), fill=colors[kind][0], width=0)
            item = c.create_text(left + px(22), y - px(1), anchor='nw', text=label, fill=INK_2, font=small,
                                 width=width - left - px(40))
            y = max(y + px(22), c.bbox(item)[3] + px(6))


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
            tile=tkfont.Font(family='Segoe UI Semibold', size=16),
            mono=tkfont.Font(family='Consolas', size=10),
        )
        self.title('ЛР №2 — Методы упаковки данных: RLE, Хаффман, Шеннон–Фано, LZW')
        self.geometry(f'{px(1200)}x{px(800)}')
        self.minsize(px(980), px(660))
        self.configure(background=BG)
        self.setup_style()
        self.bg = Background(self)

        notebook = ttk.Notebook(self)
        self.archiver = ArchiverTab(notebook, self)
        self.compare = CompareTab(notebook, self)
        self.explain = ExplainTab(notebook, self)
        notebook.add(self.archiver, text='Архиватор')
        notebook.add(self.compare, text='Сравнение методов')
        notebook.add(self.explain, text='Как это работает')
        notebook.pack(fill='both', expand=True, padx=px(10), pady=px(10))
        self.notebook = notebook

    def setup_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', background=BG, foreground=INK, font=FONTS['ui'])
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=INK)
        style.configure('H.TLabel', font=FONTS['bold'])
        style.configure('Muted.TLabel', foreground=INK_2)
        style.configure('Tile.TFrame', background=SURFACE)
        style.configure('TileLabel.TLabel', background=SURFACE, foreground=INK_2, font=FONTS['small'])
        style.configure('TileValue.TLabel', background=SURFACE, foreground=INK, font=FONTS['tile'])
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', padding=(px(16), px(6)), font=FONTS['bold'])
        style.map('TNotebook.Tab', background=[('selected', SURFACE), ('!selected', BG)])
        style.configure('TButton', padding=(px(12), px(5)))
        style.configure('Accent.TButton', background=ACCENT, foreground='white', bordercolor=ACCENT_DARK)
        style.map('Accent.TButton', background=[('disabled', '#9ec5f4'), ('active', ACCENT_DARK)],
                  foreground=[('disabled', 'white')])
        style.configure('TRadiobutton', background=BG)
        style.configure('Treeview', background=SURFACE, fieldbackground=SURFACE, rowheight=px(26))
        style.configure('Treeview.Heading', font=FONTS['bold'], background=BG)
        style.map('Treeview', background=[('selected', ACCENT_LIGHT)], foreground=[('selected', INK)])
        style.configure('TPanedwindow', background=BG)


def main() -> None:
    try:  # чёткий текст на экранах с масштабированием 125–200 %
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001 — не Windows или старая версия
        pass
    App().mainloop()


if __name__ == '__main__':
    main()
