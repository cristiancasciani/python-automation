"""Sort the files of a folder into category folders and set duplicates aside."""
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .i18n import all_folder_names, folder_name
from .journal import JOURNAL_DIR, Op, unique_path

CATEGORIES = {
    'Images': {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.bmp', '.svg', '.tif', '.tiff', '.raw'},
    'Documents': {'.pdf', '.doc', '.docx', '.odt', '.txt', '.rtf', '.md', '.pages', '.epub'},
    'Spreadsheets': {'.xls', '.xlsx', '.ods', '.csv', '.numbers'},
    'Presentations': {'.ppt', '.pptx', '.odp', '.key'},
    'Archives': {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz'},
    'Audio': {'.mp3', '.wav', '.flac', '.m4a', '.ogg', '.aac'},
    'Video': {'.mp4', '.mov', '.mkv', '.avi', '.webm'},
    'Code': {'.py', '.js', '.html', '.css', '.json', '.sh', '.ts', '.sql', '.xml', '.yml', '.yaml'},
    'Installers': {'.exe', '.msi', '.dmg', '.pkg', '.deb', '.rpm', '.appimage', '.apk'},
}
INVOICES = 'Invoices'
DUPLICATES = 'Duplicates'
OTHER = 'Other'
MANAGED = all_folder_names() | {JOURNAL_DIR}


def category_of(path: Path) -> str:
    ext = path.suffix.lower()
    for cat, exts in CATEGORIES.items():
        if ext in exts:
            return cat
    return OTHER


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Plan:
    root: Path
    moves: list[Op] = field(default_factory=list)
    categories: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    duplicates: list[tuple[str, str]] = field(default_factory=list)  # (duplicate, original kept)
    duplicate_bytes: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return len(self.moves)


def plan_organize(root: Path, by_date: bool = False, is_invoice=None) -> Plan:
    """Work out where every loose file in `root` should go. Nothing is touched.

    by_date: put files in a YYYY-MM subfolder (from the modification date).
    is_invoice: optional callable(Path) -> bool; matching PDFs go to Invoices/.
    """
    root = root.expanduser().resolve()
    plan = Plan(root)
    files = sorted(p for p in root.iterdir() if p.is_file() and not p.name.startswith('.'))
    plan.skipped = sum(1 for p in root.iterdir() if p.is_dir() and p.name not in MANAGED)

    # Duplicates: same size first (cheap), then same SHA-256. Keep the oldest copy.
    by_size = defaultdict(list)
    for p in files:
        by_size[p.stat().st_size].append(p)
    dupes: dict[Path, Path] = {}
    for group in by_size.values():
        if len(group) < 2:
            continue
        by_hash = defaultdict(list)
        for p in group:
            by_hash[sha256(p)].append(p)
        for same in by_hash.values():
            same.sort(key=lambda p: (p.stat().st_mtime, len(p.name)))
            for d in same[1:]:
                dupes[d] = same[0]

    taken: set[Path] = set()
    for p in files:
        if p in dupes:
            cat = DUPLICATES
            plan.duplicates.append((p.name, dupes[p].name))
            plan.duplicate_bytes += p.stat().st_size
        elif p.suffix.lower() == '.pdf' and is_invoice and is_invoice(p):
            cat = INVOICES
        else:
            cat = category_of(p)
        cat = folder_name(cat)
        folder = root / cat
        if by_date and cat not in (folder_name(DUPLICATES), folder_name(INVOICES)):
            folder = folder / datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m')
        dst = unique_path(folder / p.name, taken)
        taken.add(dst)
        plan.moves.append(Op(str(p), str(dst), 'move'))
        plan.categories[cat] += 1
    return plan
