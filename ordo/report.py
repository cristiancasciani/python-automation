"""Write the results of a run as a self-contained HTML page and an Excel workbook."""
import html
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .i18n import get_lang, money, t
from .invoices import Invoice
from .journal import Op
from .organize import Plan


@dataclass
class RunResult:
    folder: Path
    started: datetime = field(default_factory=datetime.now)
    plan: Plan | None = None
    renames: list[Op] = field(default_factory=list)
    invoices: list[Invoice] = field(default_factory=list)
    applied: bool = False

    @property
    def invoice_total(self) -> Decimal:
        return sum((i.total for i in self.invoices if i.total is not None), Decimal(0))

    @property
    def to_check(self) -> list[Invoice]:
        return [i for i in self.invoices if i.status != 'ok']


def human_size(n: float) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            text = f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
            return text.replace('.', ',') if get_lang() == 'it' else text
        n /= 1024
    return f'{n} B'


def display_path(p: Path) -> str:
    """Show the home folder as ~ so a shared report does not reveal the user name."""
    try:
        return '~/' + str(p.relative_to(Path.home()))
    except ValueError:
        return str(p)


def eur(v: Decimal | float | None) -> str:
    return money(v)


# ------------------------------------------------------------------ HTML
CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#15181d;--ink2:#4b5260;--muted:#7b8291;--line:#e5e7ec;--s1:#2a78d6;
--ok:#1f8a4c;--okbg:#e7f5ec;--warn:#a86400;--warnbg:#fdf1dc;--crit:#c0352b;--critbg:#fbe9e7}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Inter,system-ui,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:40px 24px 64px}
header{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;margin-bottom:28px}
.brand{display:flex;align-items:center;gap:12px}.mark{width:40px;height:40px;border-radius:10px;background:var(--ink);color:#fff;display:grid;place-items:center;font-weight:800}
h1{margin:0;font-size:26px;letter-spacing:-.02em}h2{font-size:17px;margin:0 0 14px}.sub{color:var(--muted);font-size:13px}
.kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-bottom:20px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi span{color:var(--muted);font-size:12.5px;display:flex;align-items:center;gap:6px}.kpi b{display:block;font-size:22px;letter-spacing:-.02em;margin-top:4px}
.kpi small{color:var(--muted);font-size:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;margin-bottom:20px;overflow:hidden}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.grid .card{margin:0}
table{width:100%;border-collapse:collapse;font-size:13.5px}th{text-align:left;color:var(--muted);font-weight:500;font-size:12px;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--line);padding:8px 10px}
td{border-bottom:1px solid var(--line);padding:8px 10px;vertical-align:top}tr:last-child td{border:0}.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tfoot td{font-weight:600;border-top:2px solid var(--line)}
.badge{display:inline-flex;align-items:center;gap:5px;padding:2px 9px;border-radius:99px;font-size:12px;font-weight:500;white-space:nowrap}
.ok{background:var(--okbg);color:var(--ok)}.check{background:var(--warnbg);color:var(--warn)}.unreadable{background:var(--critbg);color:var(--crit)}
.ic{width:9px;height:9px;display:inline-block}.ic-ok{background:var(--ok);border-radius:50%}.ic-check{background:var(--warn);clip-path:polygon(50% 0,100% 100%,0 100%)}
.ic-unreadable{background:var(--crit);clip-path:polygon(20% 0,50% 30%,80% 0,100% 20%,70% 50%,100% 80%,80% 100%,50% 70%,20% 100%,0 80%,30% 50%,0 20%)}
.note{color:var(--muted);font-size:12.5px}.mono{font-family:ui-monospace,Menlo,monospace;font-size:12.5px}
details summary{cursor:pointer;color:var(--s1);font-weight:500;margin-bottom:10px}
svg text{font:12px Inter,system-ui,sans-serif;fill:var(--ink2)}svg .val{fill:var(--ink);font-weight:600}svg .bar{fill:var(--s1)}
svg g:hover .bar{opacity:.8}
.dry{background:var(--warnbg);color:var(--warn);border-radius:10px;padding:10px 14px;margin-bottom:20px;font-weight:500}
footer{color:var(--muted);font-size:12px;text-align:center;margin-top:30px}
@media (max-width:760px){.kpis{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr}.hide-sm{display:none}}
"""


def bars_svg(items: list[tuple[str, float, str]], width: int = 460) -> str:
    """Horizontal bars, one series. items: (label, value, value_text). Native <title> gives the tooltip."""
    if not items:
        return '<p class="note">—</p>'
    bar, gap, right = 18, 10, 90
    label_w = min(230, max(70, 7 * max(len(l) for l, _, _ in items) + 14))
    height = len(items) * (bar + gap) - gap
    vmax = max(v for _, v, _ in items) or 1
    iw = width - label_w - right
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img">']
    for i, (label, v, vt) in enumerate(items):
        y = i * (bar + gap)
        w = max(2, v / vmax * iw)
        x0, x1, r = label_w, label_w + w, min(4, w / 2)
        path = f'M{x0},{y}H{x1 - r}Q{x1},{y} {x1},{y + r}V{y + bar - r}Q{x1},{y + bar} {x1 - r},{y + bar}H{x0}Z'
        out.append(f'<g><title>{html.escape(label)}: {html.escape(vt)}</title>'
                   f'<rect x="0" y="{y - gap / 2}" width="{width}" height="{bar + gap}" fill="transparent"/>'
                   f'<text x="{label_w - 10}" y="{y + 13}" text-anchor="end">{html.escape(label)}</text>'
                   f'<path class="bar" d="{path}"/><text class="val" x="{x1 + 8}" y="{y + 13}">{html.escape(vt)}</text></g>')
    out.append('</svg>')
    return ''.join(out)




def write_html(res: RunResult, path: Path) -> Path:
    e = html.escape
    p = res.plan
    moved = p.total if p else 0
    dup_n = len(p.duplicates) if p else 0
    cats = sorted(((c, n) for c, n in (p.categories.items() if p else []) if n), key=lambda x: -x[1])

    by_supplier: dict[str, Decimal] = defaultdict(Decimal)
    for inv in res.invoices:
        if inv.total is not None:
            by_supplier[inv.supplier or '?'] += inv.total
    sup_items = sorted(by_supplier.items(), key=lambda x: -x[1])

    h = [f'<!doctype html><html lang="{get_lang()}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
         f'<title>{t('rep.title')} — {e(res.folder.name)}</title><style>{CSS}</style></head><body><div class="wrap">']
    h.append(f'<header><div class="brand"><div class="mark">O</div><div><h1>{t('rep.title')}</h1>'
             f'<div class="sub">{e(display_path(res.folder))}</div></div></div><div class="sub">{res.started.strftime(t('rep.date_fmt'))}</div></header>')
    if not res.applied:
        h.append(f'<div class="dry">{t("rep.dry")}</div>')

    h.append('<section class="kpis">'
             f'<div class="kpi"><span>{t("rep.k.files")}</span><b>{moved}</b><small>{t("rep.k.files_sub", n=len(cats))}</small></div>'
             f'<div class="kpi"><span>{t("rep.k.dups")}</span><b>{dup_n}</b><small>{t("rep.k.dups_sub", size=human_size(p.duplicate_bytes) if p else "0 B")}</small></div>'
             f'<div class="kpi"><span>{t("rep.k.ren")}</span><b>{len(res.renames)}</b><small>{t("rep.k.ren_sub")}</small></div>'
             f'<div class="kpi"><span>{t("rep.k.inv")}</span><b>{len(res.invoices)}</b><small>{t("rep.k.inv_sub", total=eur(res.invoice_total))}</small></div>'
             f'<div class="kpi"><span><i class="ic ic-check"></i>{t("rep.k.check")}</span><b>{len(res.to_check)}</b><small>{t("rep.k.check_sub")}</small></div>'
             '</section>')

    h.append('<div class="grid">')
    h.append(f'<section class="card"><h2>{t("rep.per_folder")}</h2>'
             + bars_svg([(c, n, t('rep.file' if n == 1 else 'rep.files', n=n)) for c, n in cats]) + '</section>')
    h.append(f'<section class="card"><h2>{t("rep.per_supplier")}</h2>'
             + bars_svg([(s, float(v), eur(v)) for s, v in sup_items]) + '</section>')
    h.append('</div><br>')

    if res.invoices:
        rows = []
        for inv in sorted(res.invoices, key=lambda i: (i.status == 'ok', i.date)):
            rows.append(f'<tr><td><span class="badge {inv.status}"><i class="ic ic-{inv.status}"></i>{t("status." + inv.status)}</span></td>'
                        f'<td>{e(inv.supplier) or "—"}<div class="note mono">{e(inv.file)}</div></td><td class="mono">{e(inv.number) or "—"}</td>'
                        f'<td class="nowrap">{e(inv.date) or "—"}</td><td class="num hide-sm">{eur(inv.net)}</td><td class="num hide-sm">{eur(inv.vat)}</td>'
                        f'<td class="num"><b>{eur(inv.total)}</b></td></tr>'
                        + (f'<tr><td></td><td colspan="6" class="note">⚠ {e("; ".join(inv.notes))}</td></tr>' if inv.notes else ''))
        net = sum((i.net for i in res.invoices if i.net is not None), Decimal(0))
        vat = sum((i.vat for i in res.invoices if i.vat is not None), Decimal(0))
        h.append(f'<section class="card"><h2>{t("rep.invoices")}</h2><div style="overflow-x:auto"><table><thead><tr><th>{t("rep.col.status")}</th>'
                 f'<th>{t("rep.col.supplier")}</th><th>{t("rep.col.number")}</th><th>{t("rep.col.date")}</th><th class="num hide-sm">{t("rep.col.net")}</th>'
                 f'<th class="num hide-sm">{t("rep.col.vat")}</th><th class="num">{t("rep.col.total")}</th></tr></thead><tbody>'
                 + ''.join(rows) + f'</tbody><tfoot><tr><td colspan="4">{t("rep.total")}</td><td class="num hide-sm">{eur(net)}</td>'
                 f'<td class="num hide-sm">{eur(vat)}</td><td class="num">{eur(res.invoice_total)}</td></tr></tfoot></table></div></section>')

    if p and p.duplicates:
        h.append(f'<section class="card"><h2>{t("rep.dups")}</h2><details><summary>{t("rep.dups_show", n=dup_n)}</summary>'
                 f'<table><thead><tr><th>{t("rep.col.dup")}</th><th>{t("rep.col.same")}</th></tr></thead><tbody>'
                 + ''.join(f'<tr><td class="mono">{e(d)}</td><td class="mono">{e(o)}</td></tr>' for d, o in p.duplicates)
                 + '</tbody></table></details></section>')
    if p and p.moves:
        h.append(f'<section class="card"><h2>{t("rep.moves")}</h2><details><summary>{t("rep.moves_show", n=moved)}</summary>'
                 f'<table><thead><tr><th>{t("rep.col.file")}</th><th>{t("rep.col.folder")}</th></tr></thead><tbody>'
                 + ''.join(f'<tr><td class="mono">{e(Path(m.src).name)}</td><td class="mono">{e(str(Path(m.dst).parent.relative_to(res.folder)))}/</td></tr>'
                           for m in p.moves) + '</tbody></table></details></section>')
    if res.renames:
        h.append(f'<section class="card"><h2>{t("rep.ren")}</h2><details><summary>{t("rep.ren_show", n=len(res.renames))}</summary>'
                 f'<table><thead><tr><th>{t("rep.col.before")}</th><th>{t("rep.col.after")}</th></tr></thead><tbody>'
                 + ''.join(f'<tr><td class="mono">{e(Path(o.src).name)}</td><td class="mono">{e(Path(o.dst).name)}</td></tr>' for o in res.renames)
                 + '</tbody></table></details></section>')
    h.append(f'<footer>{t("rep.footer")} <span class="mono">ordo undo</span></footer></div></body></html>')
    path.write_text(''.join(h), encoding='utf-8')
    return path


# ----------------------------------------------------------------- Excel
def write_xlsx(res: RunResult, path: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    head_fill, head_font = PatternFill('solid', fgColor='15181D'), Font(bold=True, color='FFFFFF')
    money = '#,##0.00 [$€-x-euro2]'
    wb = Workbook()

    def sheet(title, headers, rows, widths, money_cols=()):
        ws = wb.create_sheet(title)
        ws.append(headers)
        for c in ws[1]:
            c.fill, c.font, c.alignment = head_fill, head_font, Alignment(vertical='center')
        for r in rows:
            ws.append(r)
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        for col in money_cols:
            for c in ws[col][1:]:
                c.number_format = money
        ws.freeze_panes = 'A2'
        if rows:
            ws.auto_filter.ref = ws.dimensions
        return ws

    # Invoices, with live SUM formulas and status colours.
    inv_rows = [[t('status.' + i.status), i.supplier, i.number, i.date, i.vat_id, i.as_row()['net'], i.as_row()['vat'], i.as_row()['total'],
                 i.file, '; '.join(i.notes)] for i in res.invoices]
    ws = sheet(t('x.invoices'), [t('rep.col.status'), t('rep.col.supplier'), t('rep.col.number'), t('rep.col.date'), t('x.vat_id'),
                                 t('rep.col.net'), t('rep.col.vat'), t('rep.col.total'), t('x.file'), t('x.notes')],
               inv_rows, [12, 30, 12, 12, 16, 12, 12, 12, 28, 50], ('F', 'G', 'H'))
    if inv_rows:
        n = len(inv_rows) + 1
        ws.append(['', t('x.TOTAL'), '', '', '', f'=SUM(F2:F{n})', f'=SUM(G2:G{n})', f'=SUM(H2:H{n})'])
        for c in ws[n + 1]:
            c.font = Font(bold=True)
            c.number_format = money
        ws.conditional_formatting.add(f'A2:A{n}', CellIsRule(operator='equal', formula=[f'"{t("status.check")}"'], fill=PatternFill('solid', fgColor='FDF1DC')))
        ws.conditional_formatting.add(f'A2:A{n}', CellIsRule(operator='equal', formula=[f'"{t("status.unreadable")}"'], fill=PatternFill('solid', fgColor='FBE9E7')))

    p = res.plan
    sheet(t('x.moved'), [t('x.file'), t('x.from'), t('x.to')],
          [[Path(m.src).name, str(Path(m.src).parent), str(Path(m.dst).parent)] for m in (p.moves if p else [])], [40, 40, 50])
    sheet(t('x.dups'), [t('rep.col.dup'), t('rep.col.same')], list(p.duplicates) if p else [], [45, 45])
    sheet(t('x.renamed'), [t('rep.col.before'), t('rep.col.after')], [[Path(o.src).name, Path(o.dst).name] for o in res.renames], [45, 45])

    summary = wb['Sheet']
    summary.title = t('x.summary')
    rows = [(t('x.folder'), display_path(res.folder)), (t('x.date'), res.started.strftime('%Y-%m-%d %H:%M')),
            (t('x.mode'), t('x.applied') if res.applied else t('x.preview')),
            (t('rep.k.files'), p.total if p else 0), (t('x.dups'), len(p.duplicates) if p else 0),
            (t('x.space'), human_size(p.duplicate_bytes) if p else '0 B'), (t('rep.k.ren'), len(res.renames)),
            (t('rep.k.inv'), len(res.invoices)), (t('x.total_inv'), float(res.invoice_total)), (t('x.review'), len(res.to_check))]
    summary.append([t('rep.title')])
    summary['A1'].font = Font(bold=True, size=16)
    for r in rows:
        summary.append(list(r))
    summary['B10'].number_format = money
    summary.column_dimensions['A'].width = 24
    summary.column_dimensions['B'].width = 60
    wb.save(path)
    return path
