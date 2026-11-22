"""Every change is written to a journal so the last run can be undone."""
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

JOURNAL_DIR = '.ordo'


@dataclass
class Op:
    src: str
    dst: str
    action: str  # 'move' or 'rename'


def unique_path(path: Path, taken: set[Path] | None = None) -> Path:
    """'file.pdf' -> 'file (1).pdf' if the name is already used on disk or in this plan."""
    taken = taken or set()
    if not path.exists() and path not in taken:
        return path
    i = 1
    while True:
        cand = path.with_name(f'{path.stem} ({i}){path.suffix}')
        if not cand.exists() and cand not in taken:
            return cand
        i += 1


def apply(ops: list[Op], root: Path, label: str) -> Path | None:
    """Carry out the operations and save the journal. Returns the journal path."""
    if not ops:
        return None
    done: list[Op] = []
    try:
        for op in ops:
            src, dst = Path(op.src), Path(op.dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                raise FileExistsError(dst)
            shutil.move(src, dst)
            done.append(op)
    finally:
        jdir = root / JOURNAL_DIR
        jdir.mkdir(exist_ok=True)
        jpath = jdir / f'{datetime.now():%Y%m%d-%H%M%S-%f}-{label}.json'
        jpath.write_text(json.dumps({'label': label, 'created': datetime.now().isoformat(timespec='seconds'),
                                     'ops': [asdict(o) for o in done]}, indent=1))
    return jpath


def latest(root: Path) -> Path | None:
    jdir = root / JOURNAL_DIR
    files = sorted(jdir.glob('*.json')) if jdir.is_dir() else []
    return files[-1] if files else None


def undo(root: Path) -> tuple[int, Path | None]:
    """Reverse the most recent journal. Returns (files restored, journal used)."""
    jpath = latest(root)
    if not jpath:
        return 0, None
    data = json.loads(jpath.read_text())
    restored = 0
    for op in reversed(data['ops']):
        src, dst = Path(op['src']), Path(op['dst'])
        if dst.exists() and not src.exists():
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(dst, src)
            restored += 1
    # Remove folders the run created and left empty.
    for op in data['ops']:
        parent = Path(op['dst']).parent
        while parent != root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    jpath.unlink()
    return restored, jpath
