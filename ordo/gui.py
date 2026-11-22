"""Ordo window (Tkinter): pick a folder, preview, apply, undo, open the report."""
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import journal
from .i18n import get_lang, set_lang, t
from .pipeline import run
from .report import eur, human_size

BG, CARD, INK, MUTED, LINE, ACCENT = '#f6f7f9', '#ffffff', '#15181d', '#7b8291', '#e5e7ec', '#2459c7'
ICON = {'ok': '●', 'check': '▲', 'unreadable': '✖'}


class App(tk.Tk):
    def __init__(self, folder: Path | None = None):
        super().__init__()
        self.geometry('980x660')
        self.minsize(760, 520)
        self.configure(bg=BG)
        self.folder = tk.StringVar(value=str(folder) if folder else str(Path.home() / 'Downloads'))
        self.by_date = tk.BooleanVar(value=False)
        self.rename = tk.BooleanVar(value=True)
        self.status = tk.StringVar()
        self.report_file: Path | None = None
        self.previewed = False
        self._style()
        self._build()

    def toggle_lang(self):
        """Switch Italian/English: rebuild the window, keep folder and options."""
        set_lang('en' if get_lang() == 'it' else 'it')
        for w in self.winfo_children():
            w.destroy()
        self.report_file, self.previewed = None, False
        self._build()

    # ---------------------------------------------------------------- layout
    def _style(self):
        s = ttk.Style(self)
        s.theme_use('clam')
        base = ('TkDefaultFont', 10)
        s.configure('.', background=BG, foreground=INK, font=base)
        s.configure('Card.TFrame', background=CARD)
        s.configure('Card.TLabel', background=CARD)
        s.configure('Muted.TLabel', background=BG, foreground=MUTED)
        s.configure('H1.TLabel', background=BG, font=('TkDefaultFont', 17, 'bold'))
        s.configure('KpiV.TLabel', background=CARD, font=('TkDefaultFont', 18, 'bold'))
        s.configure('KpiL.TLabel', background=CARD, foreground=MUTED, font=('TkDefaultFont', 9))
        s.configure('TCheckbutton', background=BG)
        s.configure('TButton', padding=(14, 7), background=CARD, bordercolor=LINE)
        s.configure('Accent.TButton', background=ACCENT, foreground='#fff', bordercolor=ACCENT)
        s.map('Accent.TButton', background=[('active', '#1d4aa8'), ('disabled', '#9fb3e0')])
        s.configure('Treeview', rowheight=26, background=CARD, fieldbackground=CARD, bordercolor=LINE)
        s.configure('Treeview.Heading', background=BG, foreground=MUTED, relief='flat')
        s.configure('TNotebook', background=BG, borderwidth=0)
        s.configure('TNotebook.Tab', padding=(14, 6), background=BG, bordercolor=LINE)
        s.map('TNotebook.Tab', background=[('selected', CARD)])

    def _build(self):
        self.title(t('g.title'))
        self.status.set(t('g.start'))
        pad = {'padx': 20}
        head = ttk.Frame(self)
        head.pack(fill='x', pady=(18, 6), **pad)
        ttk.Label(head, text='Ordo', style='H1.TLabel').pack(side='left')
        ttk.Label(head, text='  ' + t('g.tagline'), style='Muted.TLabel').pack(side='left', pady=(6, 0))
        ttk.Button(head, text='🌐 ' + t('g.lang'), command=self.toggle_lang).pack(side='right')

        row = ttk.Frame(self)
        row.pack(fill='x', pady=6, **pad)
        ttk.Entry(row, textvariable=self.folder).pack(side='left', fill='x', expand=True, ipady=4)
        ttk.Button(row, text=t('g.browse'), command=self.browse).pack(side='left', padx=(8, 0))

        opts = ttk.Frame(self)
        opts.pack(fill='x', pady=(2, 8), **pad)
        ttk.Checkbutton(opts, text=t('g.by_date'), variable=self.by_date, command=self.invalidate).pack(side='left')
        ttk.Checkbutton(opts, text=t('g.rename'), variable=self.rename, command=self.invalidate).pack(side='left', padx=16)

        acts = ttk.Frame(self)
        acts.pack(fill='x', pady=(0, 10), **pad)
        self.btn_preview = ttk.Button(acts, text=t('g.preview'), command=lambda: self.start(False))
        self.btn_apply = ttk.Button(acts, text=t('g.apply'), style='Accent.TButton', command=self.confirm_apply, state='disabled')
        self.btn_undo = ttk.Button(acts, text=t('g.undo'), command=self.undo)
        self.btn_report = ttk.Button(acts, text=t('g.open'), command=self.open_report, state='disabled')
        for b in (self.btn_preview, self.btn_apply, self.btn_undo, self.btn_report):
            b.pack(side='left', padx=(0, 8))
        self.bar = ttk.Progressbar(acts, mode='indeterminate', length=140)

        kpis = ttk.Frame(self)
        kpis.pack(fill='x', **pad)
        self.kpi = {}
        for key in ('files', 'dups', 'inv', 'total', 'check'):
            label = t(f'g.k.{key}')
            card = ttk.Frame(kpis, style='Card.TFrame', padding=(14, 10))
            card.pack(side='left', fill='x', expand=True, padx=(0, 10))
            ttk.Label(card, text=label, style='KpiL.TLabel').pack(anchor='w')
            v = ttk.Label(card, text='—', style='KpiV.TLabel')
            v.pack(anchor='w')
            self.kpi[key] = v

        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True, pady=12, **pad)
        self.t_inv = self._tree(nb, t('g.tab.inv'), (t('rep.col.status'), t('rep.col.supplier'), t('rep.col.number'), t('rep.col.date'),
                                                   t('rep.col.total'), t('g.col.notes')), (130, 210, 90, 90, 90, 300), money_col=4)
        self.t_moves = self._tree(nb, t('g.tab.files'), (t('rep.col.file'), t('g.col.goes')), (420, 380))
        self.t_dups = self._tree(nb, t('g.tab.dups'), (t('rep.col.dup'), t('rep.col.same')), (400, 400))
        self.t_ren = self._tree(nb, t('g.tab.ren'), (t('rep.col.before'), t('rep.col.after')), (360, 440))

        ttk.Label(self, textvariable=self.status, style='Muted.TLabel').pack(fill='x', pady=(0, 12), **pad)

    def _tree(self, nb, title, cols, widths, money_col=None):
        frame = ttk.Frame(nb)
        tree = ttk.Treeview(frame, columns=cols, show='headings')
        for k, (c, w) in enumerate(zip(cols, widths)):
            tree.heading(c, text=c, anchor='w')
            tree.column(c, width=w, anchor='e' if k == money_col else 'w', stretch=True)
        sb = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        tree.tag_configure('check', foreground='#a86400')
        tree.tag_configure('unreadable', foreground='#c0352b')
        nb.add(frame, text=title)
        return tree

    # --------------------------------------------------------------- actions
    def browse(self):
        d = filedialog.askdirectory(initialdir=self.folder.get() or str(Path.home()))
        if d:
            self.folder.set(d)
            self.invalidate()

    def invalidate(self):
        self.previewed = False
        self.btn_apply.configure(state='disabled')

    def busy(self, on: bool):
        for b in (self.btn_preview, self.btn_undo):
            b.configure(state='disabled' if on else 'normal')
        if on:
            self.btn_apply.configure(state='disabled')
            self.bar.pack(side='left', padx=8)
            self.bar.start(12)
        else:
            self.bar.stop()
            self.bar.pack_forget()

    def start(self, apply: bool):
        folder = Path(self.folder.get()).expanduser()
        if not folder.is_dir():
            messagebox.showerror('Ordo', f'{t("g.not_found")}\n{folder}')
            return
        self.busy(True)

        def work():
            try:
                res, files = run(folder, apply=apply, by_date=self.by_date.get(), rename_invoices=self.rename.get(),
                                 progress=lambda m: self.after(0, self.status.set, m + '…'))
                self.after(0, self.show, res, files, apply)
            except Exception as e:  # show any error in the window
                self.after(0, lambda: (self.busy(False), messagebox.showerror('Ordo', str(e))))

        threading.Thread(target=work, daemon=True).start()

    def show(self, res, files, applied):
        self.busy(False)
        p = res.plan
        self.kpi['files'].configure(text=str(p.total))
        self.kpi['dups'].configure(text=f'{len(p.duplicates)}  ·  {human_size(p.duplicate_bytes)}')
        self.kpi['inv'].configure(text=str(len(res.invoices)))
        self.kpi['total'].configure(text=eur(res.invoice_total))
        self.kpi['check'].configure(text=str(len(res.to_check)))
        for tree in (self.t_inv, self.t_moves, self.t_dups, self.t_ren):
            tree.delete(*tree.get_children())
        for i in res.invoices:
            self.t_inv.insert('', 'end', values=(f'{ICON[i.status]} {t("status." + i.status)}', i.supplier or i.file, i.number or '—', i.date or '—', eur(i.total),
                                                 '; '.join(i.notes)), tags=(i.status,))
        for m in p.moves:
            self.t_moves.insert('', 'end', values=(Path(m.src).name, str(Path(m.dst).parent.relative_to(res.folder)) + '/'))
        for d, o in p.duplicates:
            self.t_dups.insert('', 'end', values=(d, o))
        for o in res.renames:
            self.t_ren.insert('', 'end', values=(Path(o.src).name, Path(o.dst).name))
        self.report_file = files[0] if files else None
        self.btn_report.configure(state='normal' if self.report_file else 'disabled')
        if applied:
            self.previewed = False
            self.btn_apply.configure(state='disabled')
            self.status.set(t('g.done', n=p.total, r=len(res.renames)))
        else:
            self.previewed = bool(p.total)
            self.btn_apply.configure(state='normal' if p.total else 'disabled')
            self.status.set(t('g.ready') if p.total else t('g.empty'))

    def confirm_apply(self):
        if self.previewed and messagebox.askyesno('Ordo', t('g.confirm')):
            self.start(True)

    def undo(self):
        folder = Path(self.folder.get()).expanduser()
        if not journal.latest(folder):
            messagebox.showinfo('Ordo', t('g.no_undo'))
            return
        if messagebox.askyesno('Ordo', t('g.confirm_undo')):
            n, _ = journal.undo(folder)
            self.status.set(t('g.undone', n=n))
            self.invalidate()

    def open_report(self):
        if self.report_file:
            webbrowser.open(self.report_file.as_uri())


def main(folder: Path | None = None):
    if folder is None and len(sys.argv) > 1:
        folder = Path(sys.argv[1])
    App(folder).mainloop()


if __name__ == '__main__':
    main()
