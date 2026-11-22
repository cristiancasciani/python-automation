"""Command line interface.

  ordo run FOLDER [--apply] [--by-date] [--no-rename]    organise + invoices + report
  ordo organize FOLDER [--apply] [--by-date]             only sort files into folders
  ordo rename FOLDER --pattern "{date}_{name}" [--apply]  bulk rename
  ordo invoices FOLDER [--xlsx out.xlsx]                 read the invoices in a folder
  ordo undo FOLDER                                       reverse the last applied change
  ordo gui                                               open the window

Without --apply nothing changes: Ordo shows what it would do.
"""
import argparse
import sys
import webbrowser
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__, journal
from .i18n import LANGS, set_lang, t
from .invoices import read_folder
from .organize import plan_organize
from .pipeline import run
from .rename import PatternError, order_for_apply, plan_rename
from .report import RunResult, display_path, eur, human_size, write_xlsx

console = Console(highlight=False)
STATUS_STYLE = {'ok': '[green]● {}[/]', 'check': '[yellow]▲ {}[/]', 'unreadable': '[red]✖ {}[/]'}


def folder_arg(value: str) -> Path:
    p = Path(value).expanduser().resolve()
    if not p.is_dir():
        raise argparse.ArgumentTypeError(f'not a folder: {value}')
    return p


def dry_note(apply: bool):
    if not apply:
        console.print(f'\n[yellow]{t("cli.preview")}[/] {t("cli.add_apply")} '
                      f'([dim]{t("cli.undo_hint")}[/] [bold]ordo undo[/]).')


def category_table(plan) -> Table:
    tb = Table(box=None, pad_edge=False, show_header=False)
    tb.add_column(style='bold')
    tb.add_column(justify='right')
    tb.add_column(style='dim')
    for cat, n in sorted(plan.categories.items(), key=lambda x: -x[1]):
        tb.add_row(cat, str(n), f'→ {cat}/')
    return tb


def invoice_table(invoices) -> Table:
    tb = Table(title=t('cli.invoices'), title_justify='left', header_style='dim', expand=False)
    for col in ('status', 'supplier', 'number', 'date'):
        tb.add_column(t(f'cli.col.{col}'))
    tb.add_column(t('cli.col.total'), justify='right')
    for i in invoices:
        tb.add_row(STATUS_STYLE[i.status].format(t('status.' + i.status)), i.supplier or f'[dim]{i.file}[/]',
                   i.number or '—', i.date or '—', eur(i.total))
    return tb


# --------------------------------------------------------------- commands
def cmd_run(a) -> int:
    with console.status(t('cli.working') + '…') as st:
        res, files = run(a.folder, apply=a.apply, by_date=a.by_date, rename_invoices=not a.no_rename,
                         progress=lambda m: st.update(m + '…'))
    p = res.plan
    console.print(Panel.fit(f'[bold]{display_path(a.folder)}[/]', title='Ordo', border_style='dim'))
    console.print(category_table(p))
    if p.duplicates:
        console.print('\n' + t('cli.duplicates', n=f'[bold]{len(p.duplicates)}[/]', size=human_size(p.duplicate_bytes)))
    if res.invoices:
        console.print()
        console.print(invoice_table(res.invoices))
        console.print(f'{t("cli.total")}: [bold]{eur(res.invoice_total)}[/]'
                      + (f'   [yellow]▲ {t("cli.to_review", n=len(res.to_check))}[/]' if res.to_check else ''))
    if res.renames:
        console.print('\n' + t('cli.renamed', n=f'[bold]{len(res.renames)}[/]') + f' [dim]{Path(res.renames[0].src).name}[/] → '
                      f'[cyan]{Path(res.renames[0].dst).name}[/]')
    for f in files:
        console.print(f'{t("cli.report")}: [link={f.as_uri()}]{display_path(f)}[/link]')
    if a.open and files:
        webbrowser.open(files[0].as_uri())
    dry_note(a.apply)
    return 0


def cmd_organize(a) -> int:
    plan = plan_organize(a.folder, by_date=a.by_date)
    if not plan.moves:
        console.print(t('cli.nothing'))
        return 0
    console.print(category_table(plan))
    if plan.duplicates:
        console.print('\n' + t('cli.duplicates', n=len(plan.duplicates), size=human_size(plan.duplicate_bytes)))
    if a.apply:
        journal.apply(plan.moves, plan.root, 'organize')
        console.print(f'\n[green]✓[/] {t("cli.moved", n=plan.total)}')
    dry_note(a.apply)
    return 0


def cmd_rename(a) -> int:
    files = sorted(p for p in a.folder.iterdir() if p.is_file() and not p.name.startswith('.')
                   and (not a.ext or p.suffix.lower().lstrip('.') in a.ext))
    try:
        plan = plan_rename(files, a.pattern, start=a.start, lower=a.lower, clean=a.clean, find=a.find,
                           replace=a.replace, sort=a.sort)
    except PatternError as e:
        console.print(f'[red]{e}[/]')
        return 2
    tb = Table(header_style='dim')
    tb.add_column(t('cli.col.before'))
    tb.add_column(t('cli.col.after'), style='cyan')
    for o in plan.ops[:a.limit]:
        tb.add_row(Path(o.src).name, Path(o.dst).name)
    console.print(tb)
    if len(plan.ops) > a.limit:
        console.print(f'[dim]{t("cli.more", n=len(plan.ops) - a.limit)}[/]')
    for c in plan.conflicts:
        console.print(f'[yellow]▲ {t("cli.skipped")}[/] {c}')
    if a.apply and plan.ops:
        journal.apply(order_for_apply(plan.ops), a.folder, 'rename')
        console.print(f'[green]✓[/] {t("cli.renamed_n", n=len(plan.ops))}')
    dry_note(a.apply)
    return 0


def cmd_invoices(a) -> int:
    invoices = read_folder(a.folder)
    if not invoices:
        console.print(t('cli.no_pdf'))
        return 0
    console.print(invoice_table(invoices))
    for i in invoices:
        if i.notes:
            console.print(f'[yellow]▲[/] {i.file}: {"; ".join(i.notes)}')
    if a.xlsx:
        write_xlsx(RunResult(folder=a.folder, invoices=invoices, applied=True), a.xlsx)
        console.print(f'[green]✓[/] {t("cli.saved", path=a.xlsx)}')
    return 0


def cmd_undo(a) -> int:
    n, j = journal.undo(a.folder)
    console.print(f'[green]✓[/] {t("cli.restored", n=n, name=j.name)}' if j else t('cli.nothing_undo'))
    return 0


def cmd_gui(a) -> int:
    from .gui import main as gui_main
    gui_main(a.folder)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog='ordo', description='Tidy a folder, rename files and read PDF invoices.',
                                 epilog='Nothing changes without --apply. Every change can be undone with "ordo undo".')
    ap.add_argument('--version', action='version', version=f'ordo {__version__}')
    ap.add_argument('--lang', choices=LANGS, default=None, help='interface and report language (default: from $LANG)')
    sub = ap.add_subparsers(dest='cmd', required=True)

    r = sub.add_parser('run', help='organise + read and rename invoices + write the report')
    r.add_argument('folder', type=folder_arg)
    r.add_argument('--apply', action='store_true', help='really move and rename the files')
    r.add_argument('--by-date', action='store_true', help='add YYYY-MM subfolders')
    r.add_argument('--no-rename', action='store_true', help='keep the original invoice file names')
    r.add_argument('--open', action='store_true', help='open the HTML report in the browser')
    r.set_defaults(func=cmd_run)

    o = sub.add_parser('organize', help='sort files into category folders, set duplicates aside')
    o.add_argument('folder', type=folder_arg)
    o.add_argument('--apply', action='store_true')
    o.add_argument('--by-date', action='store_true')
    o.set_defaults(func=cmd_organize)

    n = sub.add_parser('rename', help='rename many files with a pattern',
                       description='Fields: {name} {ext} {n} {n:03} {date} {parent}')
    n.add_argument('folder', type=folder_arg)
    n.add_argument('-p', '--pattern', default='{name}', help='e.g. "{date}_{name}" or "photo_{n:03}"')
    n.add_argument('--ext', nargs='*', help='only these extensions, e.g. --ext jpg png')
    n.add_argument('--find', help='regular expression to replace in the new name')
    n.add_argument('--replace', default='', help='replacement for --find')
    n.add_argument('--lower', action='store_true', help='lowercase')
    n.add_argument('--clean', action='store_true', help='only letters, numbers and dashes')
    n.add_argument('--start', type=int, default=1, help='first value of {n}')
    n.add_argument('--sort', choices=['name', 'date', 'size'], default='name', help='order used by {n}')
    n.add_argument('--limit', type=int, default=20, help='rows shown in the preview')
    n.add_argument('--apply', action='store_true')
    n.set_defaults(func=cmd_rename)

    i = sub.add_parser('invoices', help='read the PDF invoices in a folder')
    i.add_argument('folder', type=folder_arg)
    i.add_argument('--xlsx', type=Path, help='also save them to an Excel file')
    i.set_defaults(func=cmd_invoices)

    u = sub.add_parser('undo', help='reverse the last applied change in a folder')
    u.add_argument('folder', type=folder_arg)
    u.set_defaults(func=cmd_undo)

    g = sub.add_parser('gui', help='open the graphical window')
    g.add_argument('folder', type=folder_arg, nargs='?')
    g.set_defaults(func=cmd_gui)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.lang:
        set_lang(args.lang)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        console.print(f'[red]{t("cli.interrupted")}[/]')
        return 130
    except OSError as e:
        console.print(f'[red]{t("cli.error")}[/] {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
