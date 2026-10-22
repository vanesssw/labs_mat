"""Графический интерфейс ЛР №4 «QR и штрих-код» (tkinter + Pillow).

Запуск из папки lab4:   python gui.py     (или двойной щелчок по start_gui.bat)

Вкладки:
  «QR-код»             — построить QR-код и посмотреть все этапы построения;
  «Устройство QR»      — матрица, раскрашенная по назначению модулей, маски, данные без маски;
  «Штрих-коды»         — EAN-13 и Code 128 с расчётом контрольной цифры/символа;
  «Помехоустойчивость» — испортить код (почеркать, цвета, размыть, срезать угол…) и прочитать его
                         собственным сканером; серия опытов для уровней L, M, Q, H.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from codes import analysis, code128, damage, ean13, explain, imaging
from codes import qr_tables as T
from codes.qr_encode import MASK_FORMULAS, MASKS, QRError, apply_mask, function_patterns, make_qr, place_data

APP_DIR = Path(__file__).resolve().parent

BG = '#f3f3f1'
SURFACE = '#fcfcfb'
INK = '#0b0b0b'
INK_2 = '#52514e'
MUTED = '#898781'
GRID = '#e1e0d9'
AXIS = '#c3c2b7'
GOOD_TEXT = '#006300'
GOOD_LIGHT = '#d9f2d9'
CRITICAL = '#d03b3b'
CRITICAL_LIGHT = '#fadcdc'
ACCENT = '#2a78d6'
ACCENT_DARK = '#256abf'
ACCENT_LIGHT = '#cde2fb'
LEVEL_COLORS = {'L': '#2a78d6', 'M': '#eb6834', 'Q': '#0f9d8a', 'H': '#8a4fd1'}

SCALE = 1.0
FONTS: dict[str, tkfont.Font] = {}
DEFAULT_TEXT = 'Лабораторная работа №4: QR и штрих-коды. Патрин Арсений, РИ-430933'


def px(value: float) -> int:
    return int(round(value * SCALE))


class Background:
    """Долгая работа в отдельном потоке, чтобы окно не «зависало»."""

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
                self.widget.after(50, poll)

        threading.Thread(target=target, daemon=True).start()
        self.widget.after(50, poll)


class RichText(tk.Text):
    """Текст с заголовками, формулами и таблицами (только для чтения), как в ЛР №3."""

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
        margin, gap = px(10), px(20)
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


class ImageView(tk.Canvas):
    """Холст, показывающий картинку Pillow целиком (с сохранением пропорций)."""

    def __init__(self, master, **kw) -> None:
        super().__init__(master, bg=SURFACE, highlightthickness=0, **kw)
        self.image: Image.Image | None = None
        self._tk = None
        self.bind('<Configure>', lambda e: self.redraw())

    def show(self, img: Image.Image | None) -> None:
        self.image = img
        self.redraw()

    def redraw(self) -> None:
        self.delete('all')
        if self.image is None:
            return
        w, h = max(1, self.winfo_width()), max(1, self.winfo_height())
        k = min((w - 10) / self.image.width, (h - 10) / self.image.height)
        size = (max(1, int(self.image.width * k)), max(1, int(self.image.height * k)))
        resample = Image.NEAREST if k >= 1 else Image.LANCZOS
        self._tk = ImageTk.PhotoImage(self.image.resize(size, resample))
        self.create_image(w // 2, h // 2, image=self._tk)


def save_png(img: Image.Image | None, name: str) -> None:
    if img is None:
        return
    path = filedialog.asksaveasfilename(defaultextension='.png', initialfile=name,
                                        filetypes=[('PNG', '*.png')], title='Сохранить изображение')
    if path:
        img.save(path)


# ==========================================================================
# Вкладка 1. QR-код
# ==========================================================================

class QRTab(ttk.Frame):
    def __init__(self, master, app: App) -> None:
        super().__init__(master, padding=px(10))
        self.app = app
        self.qr = None
        self.image = None
        paned = ttk.PanedWindow(self, orient='horizontal')
        paned.pack(fill='both', expand=True)
        left = ttk.Frame(paned, padding=(px(6), px(6), px(14), px(6)))
        ttk.Label(left, text='Сообщение', style='H.TLabel').pack(anchor='w')
        self.text = tk.Text(left, width=40, height=4, wrap='word', font=FONTS['ui'], relief='solid', borderwidth=1)
        self.text.insert('1.0', DEFAULT_TEXT)
        self.text.pack(fill='x', pady=(px(2), px(8)))
        ttk.Label(left, text='Уровень коррекции', style='H.TLabel').pack(anchor='w')
        row = ttk.Frame(left)
        row.pack(anchor='w', pady=(px(2), px(8)))
        self.level = tk.StringVar(value='M')
        for lv in T.LEVELS:
            ttk.Radiobutton(row, text=f'{lv} (~{T.LEVEL_PERCENT[lv]} %)', value=lv, variable=self.level,
                            command=self.build).pack(side='left', padx=(0, px(8)))
        form = ttk.Frame(left)
        form.pack(anchor='w')
        self.version = tk.StringVar(value='авто')
        self.mask = tk.StringVar(value='авто')
        ttk.Label(form, text='Версия').grid(row=0, column=0, sticky='w')
        ttk.Combobox(form, textvariable=self.version, width=6, state='readonly',
                     values=['авто'] + [str(v) for v in range(1, 41)]).grid(row=0, column=1, padx=px(6))
        ttk.Label(form, text='Маска').grid(row=0, column=2, sticky='w', padx=(px(10), 0))
        ttk.Combobox(form, textvariable=self.mask, width=6, state='readonly',
                     values=['авто'] + [str(k) for k in range(8)]).grid(row=0, column=3, padx=px(6))
        buttons = ttk.Frame(left)
        buttons.pack(anchor='w', pady=(px(10), px(8)))
        ttk.Button(buttons, text='Построить', style='Accent.TButton', command=self.build).pack(side='left')
        ttk.Button(buttons, text='Сохранить PNG…', command=lambda: save_png(self.image, 'qr.png')).pack(
            side='left', padx=px(8))
        self.info = ttk.Label(left, text='', style='Muted.TLabel', wraplength=px(380), justify='left')
        self.info.pack(anchor='w')
        self.view = ImageView(left, width=px(380), height=px(380))
        self.view.pack(fill='both', expand=True, pady=(px(6), 0))
        right, self.doc = scrolled(paned, RichText)
        paned.add(left, weight=0)
        paned.add(right, weight=1)
        self.build()

    def build(self) -> None:
        text = self.text.get('1.0', 'end').strip()
        try:
            v = None if self.version.get() == 'авто' else int(self.version.get())
            mk = None if self.mask.get() == 'авто' else int(self.mask.get())
            self.qr = make_qr(text, self.level.get(), version=v, mask=mk)
        except QRError as e:
            messagebox.showwarning('QR-код', str(e))
            return
        q = self.qr
        self.image = imaging.render_qr(q.modules, scale=10)
        self.view.show(self.image)
        layout = T.block_layout(q.version, q.level)
        self.info.configure(text=f'Версия {q.version} ({q.size}×{q.size} модулей), режим «{T.MODE_NAMES[q.mode]}», '
                                 f'маска {q.mask}. Блоков: {len(layout)}, байтов коррекции в блоке: {layout[0][1]} — '
                                 f'каждый блок исправит до {layout[0][1] // 2} байтов.')
        self.doc.render(explain.qr_doc(q))
        self.app.structure_tab.refresh()


# ==========================================================================
# Вкладка 2. Устройство QR
# ==========================================================================

class StructureTab(ttk.Frame):
    VIEWS = ['Назначение модулей', 'Данные без маски', 'Узор маски', 'Итоговый код']

    def __init__(self, master, app: App) -> None:
        super().__init__(master, padding=px(10))
        self.app = app
        paned = ttk.PanedWindow(self, orient='horizontal')
        paned.pack(fill='both', expand=True)
        left = ttk.Frame(paned, padding=(px(6), px(6), px(14), px(6)))
        row = ttk.Frame(left)
        row.pack(anchor='w', pady=(0, px(6)))
        ttk.Label(row, text='Показать', style='H.TLabel').pack(side='left')
        self.mode = tk.StringVar(value=self.VIEWS[0])
        box = ttk.Combobox(row, textvariable=self.mode, values=self.VIEWS, state='readonly', width=22)
        box.pack(side='left', padx=px(8))
        box.bind('<<ComboboxSelected>>', lambda e: self.refresh())
        ttk.Label(row, text='маска').pack(side='left', padx=(px(8), 0))
        self.mask = tk.StringVar(value='0')
        mbox = ttk.Combobox(row, textvariable=self.mask, values=[str(k) for k in range(8)], state='readonly', width=3)
        mbox.pack(side='left', padx=px(6))
        mbox.bind('<<ComboboxSelected>>', lambda e: self.refresh())
        self.caption = ttk.Label(left, text='', style='Muted.TLabel', wraplength=px(560), justify='left')
        self.caption.pack(anchor='w', pady=(0, px(6)))
        self.view = ImageView(left, width=px(560), height=px(560))
        self.view.pack(fill='both', expand=True)
        right = ttk.Frame(paned, padding=(px(10), px(6)))
        ttk.Label(right, text='Обозначения', style='H.TLabel').pack(anchor='w')
        self.legend = tk.Canvas(right, bg=BG, highlightthickness=0, height=px(240))
        self.legend.pack(fill='x', pady=(px(4), px(10)))
        frame, self.notes = scrolled(right, RichText, height=12)
        frame.pack(fill='both', expand=True)
        paned.add(left, weight=1)
        paned.add(right, weight=1)
        self.draw_legend()
        notes = explain.Doc()
        notes.h2('Как читать картинку')
        notes.p('Насыщенным цветом показаны тёмные служебные модули, бледным — светлые. Серые и чёрные модули — '
                'данные и байты коррекции после маски.')
        notes.p('Шаблоны поиска (синие) находятся в трёх углах. Отношение ширин «тёмный–светлый–тёмный–светлый–тёмный» '
                'вдоль любой прямой через центр равно 1:1:3:1:1, при любом повороте. По трём шаблонам сканер '
                'определяет положение, размер и поворот кода.')
        notes.p('Синхронизирующие линии (зелёные) чередуют тёмные и светлые модули — по ним считается шаг сетки. '
                'Выравнивающие узоры (оранжевые) появляются с версии 2 и помогают при изгибе и перспективе.')
        notes.p('Служебная информация (фиолетовая) записана дважды: уровень коррекции и номер маски, защищённые '
                'БЧХ-кодом (15,5). Начиная с версии 7 есть два блока номера версии (бирюзовые).')
        notes.p('«Узор маски» показывает, какие модули данных инвертируются выбранной маской: маска убирает большие '
                'одноцветные области и ложные шаблоны поиска.')
        self.notes.render(notes)

    def draw_legend(self) -> None:
        c = self.legend
        y = px(6)
        for k in ['finder', 'separator', 'timing', 'alignment', 'format', 'version', 'dark', None]:
            color = '#282828' if k is None else '#%02x%02x%02x' % imaging.KIND_COLORS[k]
            c.create_rectangle(px(4), y, px(22), y + px(18), fill=color, outline='')
            c.create_text(px(32), y + px(9), text=imaging.KIND_NAMES[k], anchor='w', font=FONTS['ui'], fill=INK)
            y += px(28)

    def refresh(self) -> None:
        q = self.app.qr_tab.qr if hasattr(self.app, 'qr_tab') else None
        if q is None:
            return
        view = self.mode.get()
        mk = int(self.mask.get())
        if view == 'Назначение модулей':
            img = imaging.render_kinds(q.modules, q.kind)
            cap = f'Версия {q.version}: {q.size}×{q.size} модулей. Цвет показывает назначение каждого модуля.'
        elif view == 'Данные без маски':
            base, kind = function_patterns(q.version)
            place_data(base, kind, q.codewords)
            img = imaging.render_kinds(base, kind)
            cap = 'Данные и коррекция уложены «змейкой» до наложения маски: видны полосы и пятна.'
        elif view == 'Узор маски':
            base, kind = function_patterns(q.version)
            pattern = [[1 if kind[r][c] is None and MASKS[mk](r, c) else 0 for c in range(q.size)]
                       for r in range(q.size)]
            img = imaging.render_kinds(pattern, [[None] * q.size for _ in range(q.size)])
            cap = f'Маска {mk}: инвертировать модуль данных, если {MASK_FORMULAS[mk]} (i — строка, j — столбец). ' \
                  f'Штраф маски: {sum(q.penalties[mk])}.'
        else:
            img = imaging.render_qr(q.modules, scale=10)
            cap = f'Готовый код: выбрана маска {q.mask} с наименьшим штрафом {sum(q.penalties[q.mask])}.'
        self.caption.configure(text=cap)
        self.view.show(img)


# ==========================================================================
# Вкладка 3. Штрих-коды
# ==========================================================================

class BarcodeTab(ttk.Frame):
    def __init__(self, master, app: App) -> None:
        super().__init__(master, padding=px(10))
        self.app = app
        self.image = None
        self.value = None
        paned = ttk.PanedWindow(self, orient='horizontal')
        paned.pack(fill='both', expand=True)
        left = ttk.Frame(paned, padding=(px(6), px(6), px(14), px(6)))
        ttk.Label(left, text='Тип штрих-кода', style='H.TLabel').pack(anchor='w')
        self.kind = tk.StringVar(value='ean13')
        row = ttk.Frame(left)
        row.pack(anchor='w', pady=(px(2), px(8)))
        ttk.Radiobutton(row, text='EAN-13 (12 цифр)', value='ean13', variable=self.kind,
                        command=self.kind_changed).pack(side='left', padx=(0, px(10)))
        ttk.Radiobutton(row, text='Code 128 (латиница, цифры)', value='code128', variable=self.kind,
                        command=self.kind_changed).pack(side='left')
        ttk.Label(left, text='Данные', style='H.TLabel').pack(anchor='w')
        self.data = tk.StringVar(value='460123456789')
        entry = ttk.Entry(left, textvariable=self.data, font=FONTS['mono'], width=34)
        entry.pack(anchor='w', pady=(px(2), px(8)))
        entry.bind('<Return>', lambda e: self.build())
        buttons = ttk.Frame(left)
        buttons.pack(anchor='w', pady=(0, px(8)))
        ttk.Button(buttons, text='Построить', style='Accent.TButton', command=self.build).pack(side='left')
        ttk.Button(buttons, text='Сохранить PNG…', command=lambda: save_png(self.image, 'barcode.png')).pack(
            side='left', padx=px(8))
        self.hint = ttk.Label(left, style='Muted.TLabel', wraplength=px(420), justify='left',
                              text='EAN-13: 12 цифр, контрольная (13-я) будет вычислена. Можно ввести и 13 цифр — '
                                   'программа проверит контрольную. Первые цифры 460–469 — код России.')
        self.hint.pack(anchor='w')
        self.view = ImageView(left, width=px(430), height=px(260))
        self.view.pack(fill='both', expand=True, pady=(px(8), 0))
        right, self.doc = scrolled(paned, RichText)
        paned.add(left, weight=0)
        paned.add(right, weight=1)
        self.build()

    def kind_changed(self) -> None:
        if self.kind.get() == 'ean13':
            self.data.set('460123456789')
            self.hint.configure(text='EAN-13: 12 цифр, контрольная (13-я) будет вычислена. Можно ввести и 13 цифр — '
                                     'программа проверит контрольную. Первые цифры 460–469 — код России.')
        else:
            self.data.set('LAB4-QR 2026-10-19')
            self.hint.configure(text='Code 128: символы ASCII 32–126 (латиница, цифры, знаки). Кириллица в Code 128 '
                                     'не входит. Серии из 4 и более цифр кодируются набором C — по две цифры на символ.')
        self.build()

    def build(self) -> None:
        value = self.data.get().strip()
        try:
            if self.kind.get() == 'ean13':
                full = ean13.normalize(value)
                mods, _ = ean13.encode(full)
                self.image = imaging.render_barcode(mods, full, guards=imaging.ean13_guards())
                doc = explain.ean13_doc(full)
                self.value = ('ean13', full)
            else:
                mods, _ = code128.encode(value)
                self.image = imaging.render_barcode(mods, value, quiet=code128.QUIET)
                doc = explain.code128_doc(value)
                self.value = ('code128', value)
        except ean13.BarcodeError as e:
            messagebox.showwarning('Штрих-код', str(e))
            return
        self.view.show(self.image)
        self.doc.render(doc)


# ==========================================================================
# Вкладка 4. Помехоустойчивость
# ==========================================================================

class DamageTab(ttk.Frame):
    def __init__(self, master, app: App) -> None:
        super().__init__(master, padding=px(10))
        self.app = app
        self.source_img = None
        self.damaged = None
        self.file_img = None
        paned = ttk.PanedWindow(self, orient='horizontal')
        paned.pack(fill='both', expand=True)
        left = ttk.Frame(paned, padding=(px(6), px(6), px(14), px(6)))
        ttk.Label(left, text='Что портим', style='H.TLabel').pack(anchor='w')
        self.source = tk.StringVar(value='qr')
        row = ttk.Frame(left)
        row.pack(anchor='w', pady=(px(2), px(8)))
        ttk.Radiobutton(row, text='QR-код (вкладка 1)', value='qr', variable=self.source,
                        command=self.apply).pack(side='left', padx=(0, px(8)))
        ttk.Radiobutton(row, text='Штрих-код (вкладка 3)', value='bar', variable=self.source,
                        command=self.apply).pack(side='left', padx=(0, px(8)))
        ttk.Button(row, text='Картинка из файла…', command=self.open_file).pack(side='left')
        ttk.Label(left, text='Повреждение', style='H.TLabel').pack(anchor='w')
        self.names = {v[0]: k for k, v in damage.DAMAGES.items()}
        self.damage = tk.StringVar(value=damage.DAMAGES['scribble'][0])
        box = ttk.Combobox(left, textvariable=self.damage, values=list(self.names), state='readonly', width=34)
        box.pack(anchor='w', pady=(px(2), px(6)))
        box.bind('<<ComboboxSelected>>', lambda e: self.apply())
        srow = ttk.Frame(left)
        srow.pack(fill='x')
        ttk.Label(srow, text='Сила').pack(side='left')
        self.strength = tk.DoubleVar(value=0.2)
        scale = ttk.Scale(srow, from_=0, to=1, variable=self.strength, orient='horizontal', length=px(220))
        scale.pack(side='left', padx=px(8))
        scale.bind('<ButtonRelease-1>', lambda e: self.apply())
        self.value_label = ttk.Label(srow, text='0,20', width=6)
        self.value_label.pack(side='left')
        self.strength.trace_add('write', lambda *a: self.value_label.configure(
            text=f'{self.strength.get():.2f}'.replace('.', ',')))
        self.meaning = ttk.Label(left, text='', style='Muted.TLabel')
        self.meaning.pack(anchor='w', pady=(px(2), px(6)))
        buttons = ttk.Frame(left)
        buttons.pack(anchor='w', pady=(0, px(6)))
        ttk.Button(buttons, text='Испортить и прочитать', style='Accent.TButton', command=self.apply).pack(side='left')
        self.series_btn = ttk.Button(buttons, text='Серия опытов L/M/Q/H', command=self.series)
        self.series_btn.pack(side='left', padx=px(8))
        ttk.Button(buttons, text='Сохранить PNG…', command=lambda: save_png(self.damaged, 'damaged.png')).pack(
            side='left')
        self.view = ImageView(left, width=px(420), height=px(400))
        self.view.pack(fill='both', expand=True)
        right = ttk.Frame(paned)
        frame, self.doc = scrolled(right, RichText, height=14)
        frame.pack(fill='both', expand=True)
        ttk.Label(right, text='Доля удачных чтений в зависимости от силы повреждения', style='H.TLabel').pack(
            anchor='w', pady=(px(8), px(2)))
        self.chart = tk.Canvas(right, bg=SURFACE, highlightthickness=0, height=px(260))
        self.chart.pack(fill='x')
        self.chart.bind('<Configure>', lambda e: self.draw_chart())
        self.series_data = None
        paned.add(left, weight=0)
        paned.add(right, weight=1)

    def open_file(self) -> None:
        path = filedialog.askopenfilename(title='Изображение с QR-кодом или штрих-кодом',
                                          filetypes=[('Изображения', '*.png *.jpg *.jpeg *.bmp *.gif'), ('Все', '*.*')])
        if path:
            self.file_img = Image.open(path).convert('RGB')
            self.source.set('file')
            self.apply()

    def current_source(self):
        if self.source.get() == 'file' and self.file_img is not None:
            return self.file_img, None, None
        if self.source.get() == 'bar':
            tab = self.app.barcode_tab
            return tab.image, 'bar', tab.value
        q = self.app.qr_tab.qr
        return imaging.render_qr(q.modules, scale=8), 'qr', q.text

    def apply(self) -> None:
        img, kind, expected = self.current_source()
        if img is None:
            return
        name = self.names[self.damage.get()]
        st = round(self.strength.get(), 2)
        self.meaning.configure(text='Сила: ' + damage.DAMAGES[name][2])
        self.damaged = damage.apply(img, name, st)
        self.view.show(self.damaged)
        if kind == 'bar':
            res = imaging.scan_barcode(self.damaged, expected[0])
            doc = explain.Doc()
            ok = res.text == expected[1]
            doc.h1('Штрих-код прочитан' if ok else 'Штрих-код не прочитан' if res.text is None else 'Прочитан НЕВЕРНО')
            doc.formula(f'Результат: {res.text}' if res.text else f'Причина: {res.error}', 'good' if ok else 'bad')
            doc.p(f'Строк сканирования, давших этот ответ: {res.lines_ok} из {res.lines_total}. У штрих-кода нет '
                  'исправления ошибок: информация повторяется только по высоте штрихов, поэтому достаточно одной '
                  'целой строки. Контрольная цифра (символ) отбрасывает неверные чтения.')
            self.doc.render(doc)
            return
        scan = imaging.scan_qr(self.damaged)
        if kind == 'qr' or scan.decoded:
            self.doc.render(explain.scan_doc(scan, expected))
        else:
            res = imaging.scan_barcode(self.damaged)
            doc = explain.Doc()
            doc.h1('Штрих-код: ' + (res.text or 'не прочитан'))
            doc.p(f'QR-код не найден ({scan.error}). Строк, прочитанных как {res.kind or "штрих-код"}: '
                  f'{res.lines_ok} из {res.lines_total}.')
            self.doc.render(doc)

    def series(self) -> None:
        name = self.names[self.damage.get()]
        if self.source.get() != 'qr':
            messagebox.showinfo('Серия опытов', 'Серия опытов делается для QR-кода из вкладки 1 '
                                                'на всех четырёх уровнях коррекции.')
            return
        text = self.app.qr_tab.qr.text
        strengths = [i / 10 for i in range(0, 11)] if name != 'blot' else [i / 20 for i in range(0, 9)]
        self.series_btn.configure(state='disabled', text='Считаю…')

        def work():
            return analysis.qr_damage_series(text, name, strengths, scale=6, seeds=(1, 2, 3))

        def done(result):
            self.series_btn.configure(state='normal', text='Серия опытов L/M/Q/H')
            self.series_data = (damage.DAMAGES[name][0], result)
            self.draw_chart()

        def fail(e):
            self.series_btn.configure(state='normal', text='Серия опытов L/M/Q/H')
            messagebox.showerror('Серия опытов', str(e))

        self.app.bg.start(work, done, fail)

    def draw_chart(self) -> None:
        c = self.chart
        c.delete('all')
        w, h = c.winfo_width(), c.winfo_height()
        if not self.series_data:
            c.create_text(w / 2, h / 2, text='Нажмите «Серия опытов L/M/Q/H»: QR-код из вкладки 1 строится на четырёх '
                                             'уровнях\nи портится всё сильнее; по 3 попытки на точку.',
                          fill=MUTED, font=FONTS['ui'], justify='center')
            return
        title, series = self.series_data
        x0, x1, y0, y1 = px(50), w - px(150), px(16), h - px(36)
        for k in range(0, 5):
            y = y1 - (y1 - y0) * k / 4
            c.create_line(x0, y, x1, y, fill=GRID)
            c.create_text(x0 - px(6), y, text=f'{k * 25} %', anchor='e', fill=MUTED, font=FONTS['small'])
        smax = max(p.strength for s in series for p in s.points) or 1
        for k in range(0, 6):
            x = x0 + (x1 - x0) * k / 5
            c.create_text(x, y1 + px(12), text=f'{smax * k / 5:.2f}'.replace('.', ','), fill=MUTED, font=FONTS['small'])
        c.create_text((x0 + x1) / 2, y1 + px(28), text=f'сила повреждения: {title}', fill=INK_2, font=FONTS['small'])
        c.create_line(x0, y1, x1, y1, fill=AXIS)
        for i, s in enumerate(series):
            lv = s.label[0]
            color = LEVEL_COLORS[lv]
            pts = [(x0 + (x1 - x0) * p.strength / smax, y1 - (y1 - y0) * p.rate) for p in s.points]
            if len(pts) > 1:
                c.create_line(*[v for p in pts for v in p], fill=color, width=px(2))
            for x, y in pts:
                c.create_oval(x - px(3), y - px(3), x + px(3), y + px(3), fill=color, outline=SURFACE)
            ly = y0 + px(8) + i * px(24)
            c.create_line(x1 + px(14), ly, x1 + px(34), ly, fill=color, width=px(3))
            c.create_text(x1 + px(40), ly, text=f'{lv}: порог {s.threshold():.2f}'.replace('.', ','), anchor='w',
                          fill=INK, font=FONTS['small'])


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
        self.title('ЛР №4 — QR-код и штрих-коды: построение, устройство, помехоустойчивость')
        width = min(px(1280), self.winfo_screenwidth() - px(40))
        height = min(px(840), self.winfo_screenheight() - px(90))
        self.geometry(f'{width}x{height}+{px(10)}+{px(10)}')
        self.minsize(min(px(1000), width), min(px(620), height))
        self.configure(background=BG)
        self.setup_style()
        self.bg = Background(self)
        notebook = ttk.Notebook(self)
        self.structure_tab = StructureTab(notebook, self)
        self.qr_tab = QRTab(notebook, self)
        self.barcode_tab = BarcodeTab(notebook, self)
        self.damage_tab = DamageTab(notebook, self)
        notebook.add(self.qr_tab, text='QR-код')
        notebook.add(self.structure_tab, text='Устройство QR')
        notebook.add(self.barcode_tab, text='Штрих-коды')
        notebook.add(self.damage_tab, text='Помехоустойчивость')
        notebook.pack(fill='both', expand=True, padx=px(10), pady=px(10))
        notebook.bind('<<NotebookTabChanged>>', self.tab_changed)
        self.notebook = notebook
        self.structure_tab.refresh()

    def tab_changed(self, _event=None) -> None:
        if self.notebook.select() == str(self.damage_tab):
            self.damage_tab.apply()

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
