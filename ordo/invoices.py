"""Read supplier invoices (text PDFs, Italian or English) and extract the key fields."""
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pypdf import PdfReader

from .i18n import money, t

KEYWORDS = re.compile(r'\b(fattura|invoice|ricevuta fiscale)\b', re.I)
MONTHS = {m: i for i, m in enumerate(
    ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november',
     'december'], 1)}
MONTHS.update({m: i for i, m in enumerate(
    ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto', 'settembre', 'ottobre',
     'novembre', 'dicembre'], 1)})

AMOUNT = r'(?:€|EUR)?\s*(-?\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{2})|-?\d+(?:[.,]\d{2})?)\s*(?:€|EUR)?'
PATTERNS = {
    # Same line only, and the number must contain a digit ("INVOICE\nInvoice No: X" must not give "Invoice").
    'number': [r'(?:fattura|invoice)[ \t]*(?:n(?:umero|o|r)?\.?|#|number)?[ \t]*[:.]?[ \t]*((?=[A-Z/\-_.]*\d)[A-Z0-9][A-Z0-9/\-_.]{0,20})'],
    'date': [r'(?:data(?: fattura| documento)?|date(?: of issue)?|issued(?: on)?|invoice date)\s*[:.]?\s*([0-9]{1,2}[/.\-][0-9]{1,2}[/.\-][0-9]{2,4}|[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})'],
    'vat_id': [r'(?:p\.?\s?iva|partita iva|vat(?: no\.?| number| id)?)\s*[:.]?\s*((?:IT|GB|DE|FR|ES)?\s?[0-9]{8,12})'],
    'net': [r'(?:imponibile|totale imponibile|subtotal|net amount|net total)\s*[:.]?\s*' + AMOUNT],
    'vat': [r'(?:iva|vat)\s*(?:\(?\s*\d{1,2}(?:[.,]\d)?\s*%\s*\)?)?\s*[:.]?\s*' + AMOUNT],
    'total': [r'(?:totale(?: documento| fattura| da pagare)?|total(?: due| amount| to pay)?|amount due|importo totale)\s*[:.]?\s*' + AMOUNT],
}


@dataclass
class Invoice:
    file: str
    supplier: str = ''
    number: str = ''
    date: str = ''        # ISO yyyy-mm-dd
    vat_id: str = ''
    net: Decimal | None = None
    vat: Decimal | None = None
    total: Decimal | None = None
    status: str = 'ok'    # ok | check | unreadable
    notes: list[str] = field(default_factory=list)

    def as_row(self) -> dict:
        d = asdict(self)
        for k in ('net', 'vat', 'total'):
            d[k] = float(d[k]) if d[k] is not None else None
        d['notes'] = '; '.join(self.notes)
        return d


def parse_amount(text: str) -> Decimal | None:
    s = text.replace(' ', '').replace(' ', '')
    if re.search(r',\d{2}$', s):          # 1.234,56 (Italian)
        s = s.replace('.', '').replace(',', '.')
    else:                                  # 1,234.56 (English)
        s = s.replace(',', '')
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_date(text: str) -> str:
    text = text.strip()
    for fmt in ('%d/%m/%Y', '%d/%m/%y', '%d.%m.%Y', '%d-%m-%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    m = re.match(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', text)
    if m and m.group(2).lower() in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
    return ''


def pdf_text(path: Path) -> str:
    try:
        return '\n'.join((page.extract_text() or '') for page in PdfReader(path).pages)
    except Exception:  # corrupted or encrypted file
        return ''


NAME_HINT = re.compile(r'(?i)(fattur|invoice|ricevut|parcella|scan)')


def is_invoice(path: Path) -> bool:
    """Text PDFs: look for invoice words. Scans without text: guess from the file name."""
    text = pdf_text(path)
    if len(text.strip()) < 20:
        return bool(NAME_HINT.search(path.stem))
    return bool(KEYWORDS.search(text[:3000]))


def first(patterns: list[str], text: str) -> str:
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(1).strip()
    return ''


def parse_invoice(path: Path) -> Invoice:
    inv = Invoice(file=path.name)
    text = pdf_text(path)
    if len(text.strip()) < 20:
        inv.status = 'unreadable'
        inv.notes.append(t('note.no_text'))
        return inv
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # Supplier: the first line that is not the document title.
    inv.supplier = next((l for l in lines if not KEYWORDS.fullmatch(l.split()[0]) and not re.match(r'(?i)(fattura|invoice)\b', l)), '')
    inv.number = first(PATTERNS['number'], text)
    inv.date = parse_date(first(PATTERNS['date'], text))
    inv.vat_id = first(PATTERNS['vat_id'], text).replace(' ', '')
    # Amounts: take the last match of each (totals sit at the bottom).
    for key in ('net', 'vat', 'total'):
        found = [m.group(1) for p in PATTERNS[key] for m in re.finditer(p, text, re.I)]
        if key == 'vat':  # skip "P.IVA 0123..." lines: VAT amount must have decimals
            found = [f for f in found if re.search(r'[.,]\d{2}$', f)]
        setattr(inv, key, parse_amount(found[-1]) if found else None)

    for key, label in (('number', 'number'), ('date', 'date'), ('total', 'total')):
        if not getattr(inv, key):
            inv.notes.append(t(f'note.missing.{label}'))
    if inv.net is not None and inv.vat is not None and inv.total is not None:
        if abs(inv.net + inv.vat - inv.total) > Decimal('0.02'):
            inv.notes.append(t('note.mismatch', sum=money(inv.net + inv.vat), total=money(inv.total)))
    elif inv.total is not None and inv.net is None:
        inv.notes.append(t('note.no_net'))
    if inv.notes:
        inv.status = 'check'
    return inv


def read_folder(folder: Path) -> list[Invoice]:
    pdfs = sorted(p for p in folder.iterdir() if p.suffix.lower() == '.pdf') if folder.is_dir() else []
    return [parse_invoice(p) for p in pdfs]
