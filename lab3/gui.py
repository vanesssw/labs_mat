"""Графический интерфейс ЛР №3 «Помехоустойчивое кодирование» (tkinter входит в стандартный Python).

Запуск из папки lab3:   python gui.py     (или двойной щелчок по start_gui.bat)

Вкладки:
  «1. Групповой код»        — задание 1: код (9,5), контрольные соотношения, синдромы;
  «2. Код на 18 комбинаций» — задание 2: построение кода, исправляющего двойные ошибки;
  «3. Циклический код»      — задание 3: деление на образующий многочлен, остатки, сдвиги;
  «Канал с помехами»        — передача текста через канал с ошибками всеми тремя кодами.
В каждой вкладке заданий есть блок «Попробуй сам»: щелчок по разряду вносит ошибку,
а программа сразу показывает синдром и результат исправления.
"""
from __future__ import annotations

import difflib
import queue
import random
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

from coding import channel, explain
from coding import polynomials as poly
from coding import variants as V
from coding.cyclic_code import CyclicCode
from coding.design import design_code
from coding.gf2 import bits, to_str
from coding.group_code import GroupCode

# Палитра (светлая тема, как в ЛР №2)
BG = '#f3f3f1'            # фон окна
SURFACE = '#fcfcfb'       # фон текста и рисунков
INK = '#0b0b0b'           # основной текст
INK_2 = '#52514e'         # второстепенный текст
MUTED = '#898781'         # подписи
GRID = '#e1e0d9'          # рамки ячеек
AXIS_DARK = '#b5b3a8'     # рамки ячеек, по которым можно щёлкать
GOOD = '#0ca30c'
GOOD_TEXT = '#006300'
GOOD_LIGHT = '#d9f2d9'
CRITICAL = '#d03b3b'
CRITICAL_LIGHT = '#fadcdc'
WARN_TEXT = '#a34a00'
ACCENT = '#2a78d6'
ACCENT_DARK = '#256abf'
ACCENT_LIGHT = '#cde2fb'

SCALE = 1.0               # множитель размеров для экранов с высоким DPI
FONTS: dict[str, tkfont.Font] = {}

DEFAULT_TEXT = ('Помехоустойчивый код добавляет к сообщению контрольные разряды. '
                'По ним приёмник находит и исправляет ошибки, которые внёс канал связи.')


def px(value: float) -> int:
    return int(round(value * SCALE))


class Background:
    """Выполняет долгую работу в отдельном потоке, чтобы окно не «зависало»."""

    def __init__(self, widget: tk.Misc) -> None:
        self.widget = widget

    def start(self, work, on_done, on_error) -> None:
        q: queue.Queue = queue.Queue()

        def target():
            try:
                q.put(('done', work()))
            except Exception as e:  # noqa: BLE001 — показываем любую ошибку пользователю
                q.put(('error', e))

        def poll():
            try:
                kind, value = q.get_nowait()
                (on_done if kind == 'done' else on_error)(value)
            except queue.Empty:
                self.widget.after(40, poll)

        threading.Thread(target=target, daemon=True).start()
        self.widget.after(40, poll)


class RichText(tk.Text):
    """Текстовое поле с заголовками, формулами, таблицами и моноширинными блоками (только для чтения)."""

    def __init__(self, master, **kw) -> None:
        super().__init__(master, wrap='word', relief='flat', bg=SURFACE, fg=INK,
                         padx=px(16), pady=px(12), font=FONTS['ui'], highlightthickness=0, **kw)
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
        self.tag_configure('err', background=CRITICAL_LIGHT, foreground=CRITICAL)
        self._tables = 0

    def clear(self) -> None:
        self.configure(state='normal')
        self.delete('1.0', 'end')

    def table(self, rows: list[tuple], right: set[int] = frozenset(), marks: dict | None = None) -> None:
        """Таблица на позициях табуляции; right — столбцы с выравниванием вправо; marks — подсветка строк."""
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
        self.tag_configure(tag, tabs=tabs, lmargin1=margin, lmargin2=margin, wrap='none')
        for k, row in enumerate(rows):
            line = ('\t' if 0 in right else '') + '\t'.join(str(c) for c in row)
            tags = (tag, 'th') if k == 0 else (tag,)
            if marks and k in marks:
                tags += ('row_' + marks[k],)
            self.insert('end', line + '\n', tags)

    def render(self, doc: explain.Doc) -> None:
        self.clear()
        for kind, data, tags in doc.blocks:
            if kind in ('h1', 'h2'):
                self.insert('end', data + '\n', (kind,))
            elif kind == 'p':
                self.insert('end', data + '\n', ('p',) + tags)
            elif kind == 'formula':
                self.insert('end', data + '\n', ('formula',) + tags)
            elif kind == 'mono':
                self.insert('end', '\n'.join(data) + '\n', ('mono',) + tags)
            elif kind == 'table':
                rows, right, marks = data
                self.table(rows, right, marks)
        self.done()

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


def field(parent, row: int, label: str, var: tk.StringVar, width: int = 22, mono: bool = True) -> ttk.Entry:
    """Подпись и поле ввода в две колонки сетки."""
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', pady=px(3))
    entry = ttk.Entry(parent, textvariable=var, width=width, font=FONTS['mono' if mono else 'ui'])
    entry.grid(row=row, column=1, sticky='ew', padx=(px(8), 0), pady=px(3))
    return entry


def parse_bits(text: str, what: str, length: int | None = None) -> list[int]:
    v = bits(text)
    if length is not None and len(v) != length:
        raise ValueError(f'{what}: нужно {length} разрядов, а введено {len(v)}')
    return v


# ==========================================================================
# «Попробуй сам»: внесение ошибок щелчком
# ==========================================================================

class ErrorLab(ttk.Frame):
    """Передано → принято (с ошибками) → исправлено. Щелчок по разряду инвертирует его."""

    ROWS = ('Передано', 'Принято', 'Исправлено')

    def __init__(self, master, syndrome_name: str = 'Синдром S') -> None:
        super().__init__(master)
        self.syndrome_name = syndrome_name
        self.code = None
        self.sent: list[int] = []
        self.received: list[int] = []
        self.rng = random.Random()
        self.decoded = None

        ttk.Label(self, text='Попробуй сам', style='H.TLabel').pack(anchor='w')
        self.hint = ttk.Label(self, style='Muted.TLabel', justify='left', wraplength=px(420),
                              text='Щёлкните по разряду в строке «Принято» — он инвертируется (это ошибка канала). '
                                   'Программа пересчитает синдром и попробует исправить ошибку.')
        self.hint.pack(anchor='w', pady=(px(2), px(6)))
        row = ttk.Frame(self)
        row.pack(fill='x')
        ttk.Label(row, text='Сообщение').pack(side='left')
        self.info = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.info, width=14, font=FONTS['mono'])
        entry.pack(side='left', padx=px(6))
        entry.bind('<Return>', lambda e: self.encode())
        ttk.Button(row, text='Закодировать', command=self.encode).pack(side='left')

        self.canvas = tk.Canvas(self, height=px(122), bg=SURFACE, highlightthickness=0, cursor='hand2')
        self.canvas.pack(fill='x', pady=(px(8), px(4)))
        self.canvas.bind('<Configure>', lambda e: self.draw())
        self.canvas.bind('<Button-1>', self.click)

        buttons = ttk.Frame(self)
        buttons.pack(fill='x', pady=(0, px(4)))
        ttk.Button(buttons, text='1 случайная ошибка', command=lambda: self.random_errors(1)).pack(side='left')
        ttk.Button(buttons, text='2 ошибки', command=lambda: self.random_errors(2)).pack(side='left', padx=px(6))
        ttk.Button(buttons, text='Сбросить', command=self.reset).pack(side='left')

        self.out = tk.Text(self, width=30, height=5, wrap='word', relief='flat', bg=BG, fg=INK, font=FONTS['ui'],
                           highlightthickness=0, padx=0, pady=px(2))
        self.out.tag_configure('good', foreground=GOOD_TEXT)
        self.out.tag_configure('bad', foreground=CRITICAL)
        self.out.tag_configure('warn', foreground=WARN_TEXT)
        self.out.tag_configure('mono', font=FONTS['mono'])
        self.out.pack(fill='x')
        self.out.configure(state='disabled')
        self.geom = None

    def set_code(self, code, info) -> None:
        self.code = code
        self.info.set(to_str(info))
        self.encode()

    def encode(self) -> None:
        if not self.code:
            return
        try:
            info = parse_bits(self.info.get(), 'Сообщение', self.code.k)
        except ValueError as e:
            messagebox.showwarning('Сообщение', str(e))
            return
        self.sent = self.code.encode(info)
        self.received = self.sent[:]
        self.update_view()

    def reset(self) -> None:
        self.received = self.sent[:]
        self.update_view()

    def random_errors(self, count: int) -> None:
        if not self.sent:
            return
        self.received = self.sent[:]
        for p in self.rng.sample(range(len(self.sent)), min(count, len(self.sent))):
            self.received[p] ^= 1
        self.update_view()

    def click(self, event) -> None:
        if not self.geom:
            return
        x0, cell, n = self.geom
        i = int((event.x - x0) // cell)
        if 0 <= i < n:
            self.received[i] ^= 1
            self.update_view()

    def update_view(self) -> None:
        code = self.code
        errors = [i + 1 for i, (a, b) in enumerate(zip(self.sent, self.received)) if a != b]
        dec = code.decode(self.received)
        self.decoded = dec
        self.draw()
        self.out.configure(state='normal')
        self.out.delete('1.0', 'end')
        self.out.insert('end', f'{self.syndrome_name} = ')
        self.out.insert('end', to_str(dec.syndrome), ('mono',))
        if errors:
            self.out.insert('end', f'      ошибки внесены в разряды: {", ".join(map(str, errors))}')
        self.out.insert('end', '\n')
        s = code.corrects
        if not errors:
            self.out.insert('end', '✔ Ошибок нет: синдром нулевой.\n', 'good')
        elif dec.status == 'ok':
            self.out.insert('end', '✖ Ошибка НЕ обнаружена: вектор ошибки сам оказался разрешённой комбинацией '
                                   f'(его вес ≥ d0 = {code.min_distance}).\n', 'bad')
        elif dec.status == 'detected':
            self.out.insert('end', f'⚠ Ошибка обнаружена, но не исправлена: такой синдром не соответствует '
                                   f'ни одной ошибке кратности ≤ {s}.\n', 'warn')
        elif dec.corrected == self.sent:
            where = ', '.join(map(str, dec.positions))
            self.out.insert('end', f'✔ Исправлено верно: декодер инвертировал разряд {where}.\n', 'good')
        else:
            where = ', '.join(map(str, dec.positions))
            self.out.insert('end', f'✖ Декодер ошибся: «исправил» разряд {where}, а ошибки были в '
                                   f'{", ".join(map(str, errors))}. Ошибок больше, чем s = {s}, — '
                                   'принятое слово оказалось ближе к другой разрешённой комбинации.\n', 'bad')
        self.out.insert('end', f'Код {code.name}: d0 = {code.min_distance} → обнаруживает ошибки кратности ≤ {code.detects}, '
                               f'исправляет ≤ {s}.')
        self.out.configure(state='disabled')

    def draw(self) -> None:
        c = self.canvas
        c.delete('all')
        if not self.sent:
            return
        n = len(self.sent)
        width = c.winfo_width()
        label_w = px(78)
        cell = max(px(14), min(px(32), (width - label_w - px(6)) // n))
        x0 = label_w
        self.geom = (x0, cell, n)
        top, h, gap = px(18), px(28), px(4)
        dec = self.decoded
        rows = [self.sent, self.received, dec.corrected if dec else self.received]
        small, mono = FONTS['small'], FONTS['mono']
        for i in range(n):
            label = self.code.label(i + 1)
            c.create_text(x0 + i * cell + cell / 2, px(9), text=label, font=small,
                          fill=ACCENT if label.startswith('b') else INK_2)
        for r, (name, word) in enumerate(zip(self.ROWS, rows)):
            y = top + r * (h + gap)
            c.create_text(px(4), y + h / 2, text=name, anchor='w', font=small, fill=INK_2)
            for i, b in enumerate(word):
                x = x0 + i * cell
                fill, color, outline = SURFACE, INK, GRID
                if r == 1 and b != self.sent[i]:
                    fill, color = CRITICAL_LIGHT, CRITICAL
                if r == 2 and dec and (i + 1) in dec.positions:
                    fill = GOOD_LIGHT if b == self.sent[i] else CRITICAL_LIGHT
                if r == 2 and b != self.sent[i]:
                    color = CRITICAL
                if r == 1:
                    outline = AXIS_DARK
                c.create_rectangle(x + 1, y, x + cell - 1, y + h, fill=fill, outline=outline)
                c.create_text(x + cell / 2, y + h / 2, text=str(b), font=mono, fill=color)



# ==========================================================================
# Вкладка 1. Групповой код
# ==========================================================================

class TaskTab(ttk.Frame):
    """Общий каркас вкладки задания: слева ввод и «Попробуй сам», справа решение."""

    def __init__(self, master, app: App, syndrome_name: str) -> None:
        super().__init__(master, padding=px(10))
        self.app = app
        self.code = None
        paned = ttk.PanedWindow(self, orient='horizontal')
        paned.pack(fill='both', expand=True)
        self.left = ttk.Frame(paned, padding=(px(6), px(6), px(14), px(6)))
        self.form = ttk.Frame(self.left)
        self.form.pack(fill='x')
        self.form.columnconfigure(1, weight=1)
        self.actions = ttk.Frame(self.left)
        self.actions.pack(fill='x', pady=(px(10), px(14)))
        ttk.Separator(self.left).pack(fill='x', pady=(0, px(10)))
        self.lab = ErrorLab(self.left, syndrome_name)
        self.lab.pack(fill='x')
        right, self.text = scrolled(paned, RichText)
        paned.add(self.left, weight=0)
        paned.add(right, weight=1)


class GroupTab(TaskTab):
    def __init__(self, master, app: App) -> None:
        super().__init__(master, app, 'Синдром S')
        f = self.form
        ttk.Label(f, text='Задание 1. Групповой код (9,5)', style='H.TLabel').grid(row=0, column=0, columnspan=2, sticky='w')
        self.number = tk.StringVar(value=str(V.MY_NUMBER))
        self.group = tk.IntVar(value=V.MY_GROUP)
        ttk.Label(f, text='Вариант (табл. 2.1)').grid(row=1, column=0, sticky='w', pady=px(3))
        row = ttk.Frame(f)
        row.grid(row=1, column=1, sticky='w', padx=(px(8), 0))
        spin = ttk.Spinbox(row, from_=1, to=18, width=4, textvariable=self.number, command=self.load_variant)
        spin.pack(side='left')
        spin.bind('<Return>', lambda e: self.load_variant())
        ttk.Radiobutton(row, text='Группа 1', value=1, variable=self.group).pack(side='left', padx=(px(10), 0))
        ttk.Radiobutton(row, text='Группа 2', value=2, variable=self.group).pack(side='left', padx=(px(6), 0))
        ttk.Label(f, text='Проверочная\nматрица P').grid(row=2, column=0, sticky='nw', pady=px(3))
        self.P = tk.Text(f, width=14, height=5, font=FONTS['mono'], relief='solid', borderwidth=1)
        self.P.grid(row=2, column=1, sticky='w', padx=(px(8), 0), pady=px(3))
        self.info = tk.StringVar()
        self.w1 = tk.StringVar()
        self.w2 = tk.StringVar()
        field(f, 3, 'Информационная часть', self.info)
        field(f, 4, 'Принятая комбинация 1', self.w1)
        field(f, 5, 'Принятая комбинация 2', self.w2)
        ttk.Label(f, text='Табл. 2.2 берётся по последней цифре номера варианта.', style='Muted.TLabel').grid(
            row=6, column=0, columnspan=2, sticky='w')
        ttk.Button(self.actions, text='Решить', style='Accent.TButton', command=self.solve).pack(side='left')
        ttk.Button(self.actions, text='Вариант из методички', command=self.load_variant).pack(side='left', padx=px(8))
        self.load_variant()

    def load_variant(self) -> None:
        try:
            number = int(self.number.get())
            rows = V.CHECK_PARTS[number]
        except (ValueError, KeyError):
            messagebox.showwarning('Вариант', 'Номер варианта — число от 1 до 18.')
            return
        self.P.delete('1.0', 'end')
        self.P.insert('1.0', '\n'.join(' '.join(r) for r in rows))
        info, w1, w2 = V.GROUP_TASKS[V.table_variant(number)]
        self.info.set(info)
        self.w1.set(w1)
        self.w2.set(w2)
        self.solve()

    def solve(self) -> None:
        try:
            lines = [ln for ln in self.P.get('1.0', 'end').splitlines() if ln.strip()]
            P = [parse_bits(ln, 'Строка P') for ln in lines]
            if len({len(r) for r in P}) != 1:
                raise ValueError('все строки P должны быть одной длины')
            code = GroupCode.from_variant(P, self.group.get())
            info = parse_bits(self.info.get(), 'Информационная часть', code.k)
            words = [parse_bits(w.get(), f'Комбинация {i}', code.n) for i, w in enumerate((self.w1, self.w2), 1)]
        except ValueError as e:
            messagebox.showwarning('Исходные данные', str(e))
            return
        self.code = code
        title = f'Задание 1. Групповой код {code.name} — вариант {self.number.get()}, «Группа {self.group.get()}»'
        self.text.render(explain.task1(code, info, words, title))
        self.lab.set_code(code, info)


# ==========================================================================
# Вкладка 2. Код для 18 комбинаций
# ==========================================================================

class DesignTab(TaskTab):
    def __init__(self, master, app: App) -> None:
        super().__init__(master, app, 'Синдром S')
        f = self.form
        ttk.Label(f, text='Задание 2. Код, исправляющий ошибки', style='H.TLabel').grid(row=0, column=0, columnspan=2, sticky='w')
        self.M = tk.StringVar(value='18')
        self.s = tk.StringVar(value='2')
        ttk.Label(f, text='Число комбинаций M').grid(row=1, column=0, sticky='w', pady=px(3))
        ttk.Spinbox(f, from_=2, to=4096, width=6, textvariable=self.M).grid(row=1, column=1, sticky='w', padx=(px(8), 0))
        ttk.Label(f, text='Исправлять ошибки\nкратности до s').grid(row=2, column=0, sticky='w', pady=px(3))
        ttk.Spinbox(f, from_=1, to=4, width=6, textvariable=self.s).grid(row=2, column=1, sticky='w', padx=(px(8), 0))
        ttk.Label(f, text='Методичка: M = 18, s = 2 (одиночные и двойные ошибки). При s = 3 и 4 получаются\n'
                          'таблицы опознавателей для трёх- и четырёхкратных ошибок (варианты 2 и 3 задания).',
                  style='Muted.TLabel', justify='left').grid(row=3, column=0, columnspan=2, sticky='w', pady=(px(4), 0))
        self.btn = ttk.Button(self.actions, text='Построить код', style='Accent.TButton', command=self.build)
        self.btn.pack(side='left')
        self.progress = ttk.Progressbar(self.actions, mode='indeterminate', length=px(140))
        self.build()

    def build(self) -> None:
        try:
            M, s = int(self.M.get()), int(self.s.get())
            if not (2 <= M <= 4096 and 1 <= s <= 4):
                raise ValueError
        except ValueError:
            messagebox.showwarning('Исходные данные', 'M — от 2 до 4096, s — от 1 до 4.')
            return
        self.btn.configure(state='disabled')
        self.progress.pack(side='left', padx=px(12))
        self.progress.start(12)
        self.app.bg.start(lambda: (design_code(M, s), M), self.on_done, self.on_error)

    def finish(self) -> None:
        self.btn.configure(state='normal')
        self.progress.stop()
        self.progress.pack_forget()

    def on_done(self, result) -> None:
        self.finish()
        res, M = result
        self.text.render(explain.task2(res))
        if res.code:
            self.code = res.code
            last = min(M, 2 ** res.k) - 1
            self.lab.set_code(res.code, [int(b) for b in format(last, f'0{res.k}b')])

    def on_error(self, error: Exception) -> None:
        self.finish()
        messagebox.showerror('Ошибка', str(error))


# ==========================================================================
# Вкладка 3. Циклический код
# ==========================================================================

class CyclicTab(TaskTab):
    def __init__(self, master, app: App) -> None:
        super().__init__(master, app, 'Остаток R')
        f = self.form
        ttk.Label(f, text='Задание 3. Циклический код', style='H.TLabel').grid(row=0, column=0, columnspan=2, sticky='w')
        self.number = tk.StringVar(value=str(V.table_variant(V.MY_NUMBER)))
        ttk.Label(f, text='Вариант (табл. 2.3)').grid(row=1, column=0, sticky='w', pady=px(3))
        spin = ttk.Spinbox(f, from_=0, to=9, width=4, textvariable=self.number, command=self.load_variant)
        spin.grid(row=1, column=1, sticky='w', padx=(px(8), 0))
        spin.bind('<Return>', lambda e: self.load_variant())
        self.g = tk.StringVar()
        self.info = tk.StringVar()
        self.word = tk.StringVar()
        field(f, 2, 'Образующий многочлен', self.g)
        self.g_text = ttk.Label(f, text='', style='Muted.TLabel')
        self.g_text.grid(row=3, column=1, sticky='w', padx=(px(8), 0))
        self.g.trace_add('write', lambda *a: self.show_poly())
        field(f, 4, 'Информационная часть', self.info)
        field(f, 5, 'Проверяемая комбинация', self.word)
        ttk.Button(self.actions, text='Решить', style='Accent.TButton', command=self.solve).pack(side='left')
        ttk.Button(self.actions, text='Вариант из методички', command=self.load_variant).pack(side='left', padx=px(8))
        self.load_variant()

    def show_poly(self) -> None:
        try:
            self.g_text.configure(text='K(x) = ' + poly.poly_str(bits(self.g.get())))
        except ValueError:
            self.g_text.configure(text='')

    def load_variant(self) -> None:
        try:
            g, info, word = V.CYCLIC_TASKS[int(self.number.get())]
        except (ValueError, KeyError):
            messagebox.showwarning('Вариант', 'Номер варианта — цифра от 0 до 9.')
            return
        self.g.set(g)
        self.info.set(info)
        self.word.set(word)
        self.solve()

    def solve(self) -> None:
        try:
            g = parse_bits(self.g.get(), 'Образующий многочлен')
            info = parse_bits(self.info.get(), 'Информационная часть')
            n = len(info) + poly.degree(g)
            code = CyclicCode(g, n)
            word = parse_bits(self.word.get(), 'Проверяемая комбинация', n)
        except ValueError as e:
            messagebox.showwarning('Исходные данные', str(e))
            return
        self.code = code
        self.text.render(explain.task3(code, info, word, f'Задание 3. Циклический код {code.name} — '
                                                          f'K(x) = {poly.poly_str(code.g)}'))
        self.lab.set_code(code, info)


# ==========================================================================
# Вкладка 4. Канал с помехами
# ==========================================================================

class ChannelTab(ttk.Frame):
    COLUMNS = (('code', 'Код', 120), ('rate', 'k/n', 48), ('s', 's', 32), ('bits', 'Бит в канале', 92),
               ('flips', 'Искажено', 72), ('blocks', 'Блоки: верно/испр./обн./неверно', 210),
               ('left', 'Ошибок в итоге', 104), ('theory', 'P(блок не испр.)', 112))

    def __init__(self, master, app: App) -> None:
        super().__init__(master, padding=px(10))
        self.app = app
        paned = ttk.PanedWindow(self, orient='horizontal')
        paned.pack(fill='both', expand=True)
        left = ttk.Frame(paned, padding=(px(6), px(6), px(14), px(6)))
        ttk.Label(left, text='Передача текста через канал с помехами', style='H.TLabel').pack(anchor='w')
        ttk.Label(left, text='Каждый бит в канале искажается с вероятностью p. Текст переводится в биты (UTF-8), '
                             'режется на блоки по k бит, каждый блок кодируется кодом из вкладок 1–3, '
                             'проходит через канал и декодируется.', style='Muted.TLabel', wraplength=px(300),
                  justify='left').pack(anchor='w', pady=(px(2), px(8)))
        ttk.Label(left, text='Сообщение').pack(anchor='w')
        self.msg = tk.Text(left, width=34, height=7, wrap='word', font=FONTS['ui'], relief='solid', borderwidth=1)
        self.msg.insert('1.0', DEFAULT_TEXT)
        self.msg.pack(fill='x', pady=(px(2), px(8)))
        form = ttk.Frame(left)
        form.pack(fill='x')
        self.p = tk.StringVar(value='2')
        self.seed = tk.StringVar(value='1')
        ttk.Label(form, text='Вероятность ошибки бита p, %').grid(row=0, column=0, sticky='w', pady=px(3))
        ttk.Spinbox(form, from_=0, to=30, increment=0.5, width=6, textvariable=self.p).grid(row=0, column=1, padx=px(8))
        ttk.Label(form, text='Зерно генератора помех').grid(row=1, column=0, sticky='w', pady=px(3))
        ttk.Spinbox(form, from_=1, to=9999, width=6, textvariable=self.seed).grid(row=1, column=1, padx=px(8))
        ttk.Label(left, text='Одинаковое зерно — одинаковые помехи; меняйте его, чтобы повторить опыт.',
                  style='Muted.TLabel', wraplength=px(300), justify='left').pack(anchor='w', pady=(px(2), px(10)))
        ttk.Button(left, text='Передать по каналу', style='Accent.TButton', command=self.run).pack(anchor='w')

        right = ttk.Frame(paned)
        self.tree = ttk.Treeview(right, columns=[c[0] for c in self.COLUMNS], show='headings', height=4)
        for key, title, width in self.COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=px(width), minwidth=px(30), anchor='w' if key == 'code' else 'center',
                             stretch=key == 'blocks')
        self.tree.pack(fill='x')
        frame, self.text = scrolled(right, RichText)
        frame.pack(fill='both', expand=True, pady=(px(8), 0))
        paned.add(left, weight=0)
        paned.add(right, weight=1)

    def codes(self):
        app = self.app
        return [None, app.group_tab.code, app.design_tab.code, app.cyclic_tab.code]

    def run(self) -> None:
        text = self.msg.get('1.0', 'end').strip()
        try:
            p = float(self.p.get().replace(',', '.')) / 100
            seed = int(self.seed.get())
            if not 0 <= p <= 0.5:
                raise ValueError
        except ValueError:
            messagebox.showwarning('Исходные данные', 'p — число от 0 до 50 %, зерно — целое число.')
            return
        if not text:
            messagebox.showwarning('Сообщение', 'Введите текст.')
            return
        codes = [None] + [c for c in self.codes()[1:] if c is not None]
        results = [channel.transmit(text, c, p, seed) for c in codes]
        self.show(text, results, codes)

    def show(self, text: str, results, codes) -> None:
        self.tree.delete(*self.tree.get_children())
        for res, code in zip(results, codes):
            if code is None:
                row = (res.code_name, '1', '0', res.channel_bits, res.channel_errors, '—', res.residual_errors, '—')
            else:
                theory = channel.block_failure_probability(code.n, code.corrects, res.p)
                row = (f'{code.name}  d0={code.min_distance}', f'{code.k}/{code.n}', code.corrects, res.channel_bits,
                       res.channel_errors, f'{res.clean} / {res.corrected} / {res.detected} / {res.wrong}',
                       res.residual_errors, f'{theory:.4f}')
            self.tree.insert('', 'end', values=row)
        t = self.text
        t.clear()
        t.insert('end', 'Что получил приёмник\n', ('h1',))
        t.insert('end', 'Красным выделены символы, которые отличаются от исходного текста.\n', ('muted',))
        for res, code in zip(results, codes):
            name = 'Без кодирования' if code is None else f'Код {code.name}'
            t.insert('end', f'{name}: искажено {res.residual_errors} бит из {res.message_bits}\n', ('h2',))
            sm = difflib.SequenceMatcher(None, text, res.text, autojunk=False)
            for op, a0, a1, b0, b1 in sm.get_opcodes():
                t.insert('end', res.text[b0:b1], () if op == 'equal' else ('err',))
            t.insert('end', '\n')
        t.insert('end', 'Почему так получается\n', ('h2',))
        p = results[0].p
        t.insert('end', 'Вероятность ровно i ошибок в блоке из n бит (формула Бернулли):\n', ('p',))
        t.insert('end', 'P(i) = C(n, i) · pⁱ · (1 − p)ⁿ⁻ⁱ\n', ('formula',))
        t.insert('end', 'Код, исправляющий s ошибок, ошибается только если в блоке больше s ошибок:\n', ('p',))
        t.insert('end', 'P(блок не исправлен) = 1 − Σ P(i), i = 0 … s\n', ('formula',))
        blocks = 10000
        t.insert('end', f'Проверка опытом: через канал пропускаются {blocks} случайных блоков каждого кода.\n', ('p',))
        rows = [('Код', 'n', 's', 'P теория', 'P опыт', 'Исправлено блоков', 'Неисправлено')]
        for code in codes[1:]:
            fail = channel.block_failure_probability(code.n, code.corrects, p)
            sim = channel.simulate_blocks(code, p, blocks, int(self.seed.get()))
            bad = sim['detected'] + sim['wrong']
            rows.append((code.name, code.n, code.corrects, f'{fail:.5f}', f'{bad / blocks:.5f}',
                         sim['corrected'], bad))
        t.table(rows, right={1, 2, 5, 6})
        t.insert('end', 'Плата за надёжность — избыточность: по каналу идёт n бит вместо k, скорость кода k/n < 1. '
                        'Чем больше ошибок код исправляет, тем больше контрольных разрядов ему нужно.\n', ('p', 'muted'))
        t.done()


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
        self.title('ЛР №3 — Помехоустойчивое кодирование: групповые и циклические коды')
        width = min(px(1280), self.winfo_screenwidth() - px(40))
        height = min(px(820), self.winfo_screenheight() - px(90))
        self.geometry(f'{width}x{height}+{px(10)}+{px(10)}')
        self.minsize(min(px(1000), width), min(px(620), height))
        self.configure(background=BG)
        self.setup_style()
        self.bg = Background(self)

        notebook = ttk.Notebook(self)
        self.group_tab = GroupTab(notebook, self)
        self.design_tab = DesignTab(notebook, self)
        self.cyclic_tab = CyclicTab(notebook, self)
        self.channel_tab = ChannelTab(notebook, self)
        notebook.add(self.group_tab, text='1. Групповой код')
        notebook.add(self.design_tab, text='2. Код на 18 комбинаций')
        notebook.add(self.cyclic_tab, text='3. Циклический код')
        notebook.add(self.channel_tab, text='Канал с помехами')
        notebook.pack(fill='both', expand=True, padx=px(10), pady=px(10))
        notebook.bind('<<NotebookTabChanged>>', self.tab_changed)
        self.notebook = notebook

    def tab_changed(self, _event=None) -> None:
        if self.notebook.select() == str(self.channel_tab):
            self.channel_tab.run()   # коды могли измениться во вкладках 1–3

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
