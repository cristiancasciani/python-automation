"""Create a messy demo folder ("Downloads") to try Ordo on.

    python scripts/make_demo.py [target]      (default: ./demo/Downloads)

All companies, numbers and amounts are made up.
"""
import os
import random
import shutil
import sys
import zipfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fpdf import FPDF

rng = random.Random(42)
DEJAVU = Path('/usr/share/fonts/truetype/dejavu')


def new_pdf() -> FPDF:
    """A4 PDF with a Unicode font when available (for the euro sign), Helvetica otherwise."""
    pdf = FPDF()
    if (DEJAVU / 'DejaVuSans.ttf').exists():
        pdf.add_font('Sans', '', str(DEJAVU / 'DejaVuSans.ttf'))
        pdf.add_font('Sans', 'B', str(DEJAVU / 'DejaVuSans-Bold.ttf'))
        pdf.add_font('Sans', 'I', str(DEJAVU / 'DejaVuSans.ttf'))  # oblique not always installed
        pdf.unicode = True
    else:
        pdf.unicode = False
    return pdf


def font(pdf: FPDF, style: str = '', size: int = 10):
    pdf.set_font('Sans' if pdf.unicode else 'Helvetica', style, size)


def txt(pdf: FPDF, text: str) -> str:
    return text if pdf.unicode else text.replace('€', 'EUR')
NOW = datetime(2026, 11, 20, 18, 0)


def touch(path: Path, size: int, days_ago: int):
    path.write_bytes(rng.randbytes(size))
    stamp(path, days_ago)


def stamp(path: Path, days_ago: int):
    t = (NOW - timedelta(days=days_ago, hours=rng.randint(0, 10))).timestamp()
    os.utime(path, (t, t))


def euro_it(v: Decimal) -> str:
    return f'{v:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


# ---------------------------------------------------------------- invoices
SUPPLIERS = [
    # name, vat, layout, items
    ('Tipografia Rossi S.r.l.', 'IT01234567890', 'it', [('Volantini A5 (5.000 pz)', 380), ('Biglietti da visita', 95), ('Roll-up 85x200', 210)]),
    ('Bright Cloud Ltd', 'GB123456789', 'en', [('Cloud hosting - monthly plan', 49), ('Extra storage 200 GB', 12), ('Daily backups', 9)]),
    ('Elettroforniture Bianchi S.p.A.', 'IT09876543210', 'it', [('Cavo FG16 3x2,5 (100 m)', 165), ('Quadro elettrico 24 moduli', 240), ('Interruttori assortiti', 88)]),
    ('Studio Verdi Consulenze', 'IT05550001112', 'it2', [('Consulenza fiscale trimestrale', 600), ('Dichiarazione IVA', 200)]),
]


def invoice_pdf(path: Path, supplier, number: str, when: datetime, lines, broken_total=False):
    name, vat_id, layout, _ = supplier
    net = sum((Decimal(q * p) for _, q, p in lines), Decimal(0))
    rate = Decimal('0.20') if layout == 'en' else Decimal('0.22')
    vat = (net * rate).quantize(Decimal('0.01'))
    total = net + vat + (Decimal('10.00') if broken_total else 0)

    pdf = new_pdf()
    pdf.add_page()
    pdf.set_auto_page_break(False)
    font(pdf, 'B', 16)
    pdf.cell(0, 9, name, new_x='LMARGIN', new_y='NEXT')
    font(pdf, '', 9)
    if layout == 'en':
        pdf.multi_cell(0, 5, f'12 Harbour Street, Bristol BS1 4XX\nVAT No: {vat_id}')
        pdf.ln(6)
        font(pdf, 'B', 20)
        pdf.cell(0, 10, 'INVOICE', new_x='LMARGIN', new_y='NEXT')
        font(pdf, '', 10)
        pdf.multi_cell(0, 6, f'Invoice No: {number}\nDate of issue: {when.day} {when:%B %Y}\nBill to: Demo Shop, Rome, Italy')
    else:
        pdf.multi_cell(0, 5, f'Via dei Mille 21, 00185 Roma\nP.IVA {vat_id}')
        pdf.ln(6)
        font(pdf, 'B', 16)
        title = f'FATTURA N. {number}' if layout == 'it' else f'Fattura nr. {number}'
        pdf.cell(0, 10, title, new_x='LMARGIN', new_y='NEXT')
        font(pdf, '', 10)
        d = when.strftime('%d/%m/%Y') if layout == 'it' else when.strftime('%Y-%m-%d')
        pdf.multi_cell(0, 6, f'Data documento: {d}\nCliente: Negozio Demo, Roma')
    pdf.ln(4)
    # Lines
    font(pdf, 'B', 9)
    heads = ('Description', 'Qty', 'Unit', 'Amount') if layout == 'en' else ('Descrizione', 'Q.ta', 'Prezzo', 'Importo')
    for h, w in zip(heads, (100, 20, 30, 30)):
        pdf.cell(w, 7, h, border='B')
    pdf.ln()
    font(pdf, '', 9)
    fmt = (lambda v: f'{v:,.2f}') if layout == 'en' else euro_it
    for desc, q, p in lines:
        pdf.cell(100, 7, desc)
        pdf.cell(20, 7, str(q))
        pdf.cell(30, 7, fmt(Decimal(p)))
        pdf.cell(30, 7, fmt(Decimal(q * p)), new_x='LMARGIN', new_y='NEXT')
    pdf.ln(4)
    pdf.set_x(110)
    if layout == 'en':
        rows = [('Subtotal', f'EUR {fmt(net)}'), ('VAT (20%)', f'EUR {fmt(vat)}'), ('Total due', f'EUR {fmt(total)}')]
    elif layout == 'it':
        rows = [('Imponibile', f'€ {fmt(net)}'), ('IVA 22%', f'€ {fmt(vat)}'), ('Totale documento', f'€ {fmt(total)}')]
    else:
        rows = [('Totale imponibile', fmt(net)), ('IVA 22%', fmt(vat)), ('Totale da pagare', fmt(total) + ' EUR')]
    for label, val in rows:
        pdf.set_x(110)
        font(pdf, 'B' if label == rows[-1][0] else '', 10)
        pdf.cell(45, 7, label)
        pdf.cell(35, 7, txt(pdf, val), align='R', new_x='LMARGIN', new_y='NEXT')
    pdf.set_y(270)
    font(pdf, 'I', 7)
    pdf.cell(0, 5, 'Demo document generated for Ordo. Fictional company.')
    pdf.output(str(path))
    return total


def scanned_pdf(path: Path):
    """An image-only 'scanned' invoice: no text layer."""
    pdf = new_pdf()
    pdf.add_page()
    pdf.set_fill_color(235, 235, 230)
    pdf.rect(15, 15, 180, 260, 'F')
    pdf.set_fill_color(90, 90, 90)
    for i in range(14):
        pdf.rect(25, 30 + i * 12, rng.randint(60, 160), 4, 'F')
    pdf.output(str(path))


def plain_pdf(path: Path, title: str, body: str):
    pdf = new_pdf()
    pdf.add_page()
    font(pdf, 'B', 16)
    pdf.cell(0, 10, title, new_x='LMARGIN', new_y='NEXT')
    font(pdf, '', 11)
    pdf.multi_cell(0, 6, body)
    pdf.output(str(path))


def main(target: Path):
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    # Invoices with irregular file names, like real downloads.
    names = ['fattura_ottobre.pdf', 'Invoice-BC-55821.pdf', 'FT7731.pdf', 'doc00231.pdf', 'fattura (1).pdf',
             'invoice_nov.pdf', 'scan_fornitore.pdf', 'Fattura Bianchi novembre.pdf', 'download.pdf', 'parcella_studio.pdf']
    plan = [(0, '2026/118', 40), (1, 'BC-55821', 32), (2, 'FT-7731', 25), (3, '41', 52), (0, '2026/131', 12),
            (1, 'BC-56010', 2), (None, '', 18), (2, 'FT-7802', 6), (0, '2026/140', 3), (3, '47', 20)]
    for fname, (si, number, days) in zip(names, plan):
        path = target / fname
        if si is None:
            scanned_pdf(path)
        else:
            sup = SUPPLIERS[si]
            lines = [(d, rng.randint(1, 3) if si != 3 else 1, p) for d, p in rng.sample(sup[3], k=min(len(sup[3]), rng.randint(1, 3)))]
            invoice_pdf(path, sup, number, NOW - timedelta(days=days + 1), lines, broken_total=(fname == 'download.pdf'))
        stamp(path, days)

    plain_pdf(target / 'Manuale stampante HP.pdf', 'Printer manual', 'Setup guide. ' * 40)
    plain_pdf(target / 'biglietto treno Roma-Milano.pdf', 'Trenitalia - e-ticket (demo)', 'Roma Termini -> Milano Centrale\nCoach 5, seat 12A')
    plain_pdf(target / 'CV_Mario_Rossi.pdf', 'Curriculum vitae (demo)', 'Experience, education, skills. ' * 20)
    for p, d in ((target / 'Manuale stampante HP.pdf', 80), (target / 'biglietto treno Roma-Milano.pdf', 9), (target / 'CV_Mario_Rossi.pdf', 120)):
        stamp(p, d)

    # Photos and screenshots
    for i in range(14):
        touch(target / f'IMG_{20261001 + i * 2}_{rng.randint(100000, 999999)}.jpg', rng.randint(40_000, 90_000), rng.randint(1, 90))
    for i in range(6):
        touch(target / f'Screenshot {2026}-{rng.randint(8, 11):02}-{rng.randint(1, 28):02} at {rng.randint(9, 20)}.{rng.randint(10, 59)}.png', rng.randint(20_000, 60_000), rng.randint(1, 100))
    touch(target / 'logo definitivo FINALE.png', 18_000, 40)
    touch(target / 'logo definitivo FINALE v2.svg', 6_000, 38)
    # Documents, sheets, slides
    for n, d in (('preventivo cliente.docx', 30), ('note riunione.txt', 4), ('Contratto affitto.docx', 200), ('lista spesa.txt', 1), ('Relazione Q3.odt', 50)):
        touch(target / n, rng.randint(8_000, 40_000), d)
    for n, d in (('vendite_ottobre.xlsx', 25), ('inventario.csv', 7), ('budget 2027.xlsx', 3)):
        touch(target / n, rng.randint(9_000, 30_000), d)
    touch(target / 'Presentazione progetto.pptx', 300_000, 60)
    # Media, archives, installers, code, unknown
    for n, s, d in (('podcast episodio 12.mp3', 400_000, 15), ('vocale whatsapp.ogg', 30_000, 2), ('video compleanno.mp4', 900_000, 70),
                    ('setup_editor_v2.exe', 500_000, 95), ('chrome_installer.deb', 450_000, 110), ('script_backup.sh', 1_200, 33),
                    ('export.json', 4_000, 12), ('pagina.html', 3_000, 64), ('font_pack.ttf', 70_000, 140), ('dati.bak', 15_000, 300)):
        touch(target / n, s, d)
    with zipfile.ZipFile(target / 'foto vacanze.zip', 'w') as z:
        z.writestr('readme.txt', 'Holiday photos (demo).')
    stamp(target / 'foto vacanze.zip', 75)
    with zipfile.ZipFile(target / 'progetto_sito.zip', 'w') as z:
        z.writestr('index.html', '<h1>Demo</h1>')
    stamp(target / 'progetto_sito.zip', 45)

    # Duplicates: the same downloads saved twice or three times.
    for src, copies in (('IMG_20261001_' , 2), ('vendite_ottobre.xlsx', 1), ('Presentazione progetto.pptx', 1), ('fattura_ottobre.pdf', 1)):
        orig = next(p for p in sorted(target.iterdir()) if p.name.startswith(src))
        for k in range(1, copies + 1):
            dup = target / f'{orig.stem} ({k}){orig.suffix}'
            shutil.copy2(orig, dup)
            stamp(dup, rng.randint(0, 5))

    files = list(target.iterdir())
    print(f'Created {len(files)} files in {target}')


if __name__ == '__main__':
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / 'demo' / 'Downloads')
