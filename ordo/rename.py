"""Bulk rename with a pattern, previewed before anything changes.

Pattern fields:
  {name}   original name without extension     {ext}    extension without the dot
  {n}      counter (format it: {n:03} -> 001)  {date}   modification date, YYYY-MM-DD
  {parent} name of the containing folder
"""
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .journal import Op


class PatternError(ValueError):
    pass


def slug(text: str) -> str:
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    return re.sub(r'[^A-Za-z0-9]+', '-', text).strip('-').lower()


@dataclass
class RenamePlan:
    ops: list[Op] = field(default_factory=list)
    unchanged: int = 0
    conflicts: list[str] = field(default_factory=list)


def plan_rename(files: list[Path], pattern: str = '{name}', start: int = 1, lower: bool = False, clean: bool = False,
                find: str | None = None, replace: str = '', sort: str = 'name') -> RenamePlan:
    """Compute new names for `files`. Raises PatternError on a bad pattern or regex."""
    try:
        rx = re.compile(find) if find else None
    except re.error as e:
        raise PatternError(f'Invalid regular expression: {e}') from e

    key = {'name': lambda p: p.name.lower(), 'date': lambda p: p.stat().st_mtime, 'size': lambda p: p.stat().st_size}[sort]
    files = sorted(files, key=key)
    plan = RenamePlan()
    targets: dict[Path, Path] = {}
    for i, p in enumerate(files, start):
        fields = {'name': p.stem, 'ext': p.suffix[1:], 'n': i, 'parent': p.parent.name,
                  'date': datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d')}
        try:
            stem = pattern.format(**fields)
        except (KeyError, IndexError, ValueError) as e:
            raise PatternError(f'Invalid pattern field: {e}') from e
        if rx:
            stem = rx.sub(replace, stem)
        if clean:
            stem = slug(stem)
        if lower:
            stem = stem.lower()
        if not stem.strip():
            raise PatternError('The pattern produces an empty name.')
        new = p.with_name(stem + (p.suffix.lower() if lower or clean else p.suffix))
        if new == p:
            plan.unchanged += 1
            continue
        targets[p] = new

    # A target may only be taken by a file that is itself being renamed away.
    sources = set(targets)
    seen: set[Path] = set()
    for src, dst in targets.items():
        if dst in seen or (dst.exists() and dst not in sources and dst != src):
            plan.conflicts.append(f'{src.name} -> {dst.name}')
            continue
        seen.add(dst)
        plan.ops.append(Op(str(src), str(dst), 'rename'))
    return plan


def order_for_apply(ops: list[Op]) -> list[Op]:
    """Renames that chain (a->b while b->c) are done through a temporary name."""
    srcs = {o.src for o in ops}
    if not any(o.dst in srcs for o in ops):
        return ops
    first, second = [], []
    for k, o in enumerate(ops):
        tmp = str(Path(o.src).with_name(f'.ordo-tmp-{k}{Path(o.src).suffix}'))
        first.append(Op(o.src, tmp, 'rename'))
        second.append(Op(tmp, o.dst, 'rename'))
    return first + second
