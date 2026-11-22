"""The full job: organise a folder, read and rename invoices, write the report."""
from pathlib import Path

from . import journal
from .invoices import Invoice, is_invoice, parse_invoice
from .i18n import folder_name, t
from .journal import Op, unique_path
from .organize import INVOICES, plan_organize
from .rename import slug
from .report import RunResult, write_html, write_xlsx



def invoice_name(inv: Invoice, src: Path) -> str:
    """'2026-10-10_tipografia-rossi-s-r-l_2026-118.pdf' when date, supplier and number are known."""
    if inv.status == 'unreadable' or not (inv.date and inv.supplier and inv.number):
        return src.name
    return f'{inv.date}_{slug(inv.supplier)[:30]}_{slug(inv.number)}{src.suffix.lower()}'


def run(folder: Path, apply: bool = False, by_date: bool = False, rename_invoices: bool = True,
        report: bool = True, progress=None) -> tuple[RunResult, list[Path]]:
    """Plan (and with apply=True carry out) the whole job. Returns the result and the report files."""
    say = progress or (lambda msg: None)
    folder = folder.expanduser().resolve()
    say(t('step.scan'))
    plan = plan_organize(folder, by_date=by_date, is_invoice=is_invoice)
    res = RunResult(folder=folder, plan=plan, applied=apply)

    say(t('step.invoices'))
    renames: list[Op] = []
    taken: set[Path] = set()
    for move in plan.moves:
        dst = Path(move.dst)
        if dst.parent.name != folder_name(INVOICES):
            continue
        inv = parse_invoice(Path(move.src))  # read before moving: same content
        res.invoices.append(inv)
        if rename_invoices:
            new = unique_path(dst.with_name(invoice_name(inv, dst)), taken)
            taken.add(new)
            if new != dst:
                renames.append(Op(str(dst), str(new), 'rename'))
                inv.file = new.name
    res.renames = renames

    if apply:
        say(t('step.apply'))
        journal.apply(plan.moves + renames, folder, 'run')

    files: list[Path] = []
    if report:
        say(t('step.report'))
        out = folder / folder_name('Reports')
        out.mkdir(exist_ok=True)
        stem = f'ordo-report-{res.started:%Y-%m-%d_%H%M%S}' + ('' if apply else '-preview')
        files = [write_html(res, out / f'{stem}.html'), write_xlsx(res, out / f'{stem}.xlsx')]
    return res, files
