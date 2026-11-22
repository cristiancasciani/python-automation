import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from ordo import journal
from ordo.cli import main
from ordo.invoices import parse_amount, parse_date
from ordo.organize import plan_organize
from ordo.pipeline import run
from ordo.rename import PatternError, order_for_apply, plan_rename

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope='session')
def demo_template(tmp_path_factory):
    target = tmp_path_factory.mktemp('tpl') / 'Downloads'
    subprocess.run([sys.executable, str(ROOT / 'scripts' / 'make_demo.py'), str(target)], check=True, capture_output=True)
    return target


@pytest.fixture()
def demo(demo_template, tmp_path):
    import shutil
    dst = tmp_path / 'Downloads'
    shutil.copytree(demo_template, dst)
    return dst


def snapshot(folder: Path) -> set[str]:
    return {str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file() and '.ordo' not in p.parts}


@pytest.mark.parametrize('text,expected', [('1.234,56', '1234.56'), ('1,234.56', '1234.56'), ('89.00', '89.00'),
                                           ('976,00', '976.00'), ('12', '12')])
def test_parse_amount(text, expected):
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize('text,expected', [('14/10/2026', '2026-10-14'), ('2026-09-30', '2026-09-30'),
                                           ('3 November 2026', '2026-11-03'), ('02.11.2026', '2026-11-02'), ('nope', '')])
def test_parse_date(text, expected):
    assert parse_date(text) == expected


def test_dry_run_changes_nothing(demo):
    before = snapshot(demo)
    res, files = run(demo, apply=False)
    assert res.plan.total == len(before)
    assert snapshot(demo) - {str(f.relative_to(demo)) for f in files} == before


def test_run_apply_and_undo(demo):
    before = snapshot(demo)
    res, files = run(demo, apply=True, report=False)
    assert (demo / 'Invoices').is_dir() and (demo / 'Duplicates').is_dir()
    assert len(res.plan.duplicates) == 5
    assert not any(p.is_file() for p in demo.iterdir())  # no loose files left
    n, _ = journal.undo(demo)
    assert n == res.plan.total + len(res.renames)
    assert snapshot(demo) == before


def test_invoices_extracted(demo):
    res, _ = run(demo, apply=False, report=False)
    by_number = {i.number: i for i in res.invoices}
    assert by_number['BC-55821'].supplier == 'Bright Cloud Ltd'
    assert by_number['FT-7731'].vat_id == 'IT09876543210'
    assert by_number['2026/140'].status == 'check'  # totals do not add up on purpose
    assert sum(i.status == 'unreadable' for i in res.invoices) == 1
    assert all(i.net + i.vat == i.total for i in res.invoices if i.status == 'ok')


def test_duplicates_keep_oldest(tmp_path):
    a, b = tmp_path / 'a.txt', tmp_path / 'a (1).txt'
    a.write_text('same')
    b.write_text('same')
    import os
    os.utime(a, (1_000, 1_000))
    plan = plan_organize(tmp_path)
    assert plan.duplicates == [('a (1).txt', 'a.txt')]


def test_rename_pattern_and_chain(tmp_path):
    for n in ('b.txt', 'c.txt', 'a.txt'):
        (tmp_path / n).write_text(n)
    files = sorted(tmp_path.iterdir())
    plan = plan_rename(files, 'file_{n:02}')
    assert [Path(o.dst).name for o in plan.ops] == ['file_01.txt', 'file_02.txt', 'file_03.txt']
    # Swap-like chain: a->b, b->c, c->d must not overwrite anything.
    plan = plan_rename(files, '{name}', find='^a$|^b$|^c$', replace='X')
    assert plan.conflicts  # three files cannot all become X.txt
    with pytest.raises(PatternError):
        plan_rename(files, '{nope}')


def test_rename_chain_uses_temp_names(tmp_path):
    """a->b while b->c: applying naively would overwrite b."""
    from ordo.journal import Op
    (tmp_path / 'a.txt').write_text('A')
    (tmp_path / 'b.txt').write_text('B')
    ops = [Op(str(tmp_path / 'a.txt'), str(tmp_path / 'b.txt'), 'rename'),
           Op(str(tmp_path / 'b.txt'), str(tmp_path / 'c.txt'), 'rename')]
    journal.apply(order_for_apply(ops), tmp_path, 'rename')
    assert (tmp_path / 'b.txt').read_text() == 'A' and (tmp_path / 'c.txt').read_text() == 'B'
    journal.undo(tmp_path)
    assert (tmp_path / 'a.txt').read_text() == 'A' and (tmp_path / 'b.txt').read_text() == 'B'


def test_cli_preview_and_apply(demo, capsys):
    assert main(['organize', str(demo)]) == 0
    out = capsys.readouterr().out
    assert 'Preview only' in out and 'Invoices' not in snapshot(demo)
    assert main(['run', str(demo), '--apply']) == 0
    assert (demo / 'Invoices').is_dir()
    assert main(['undo', str(demo)]) == 0
    assert main(['rename', str(demo), '-p', '{bad']) == 2


def test_italian_texts(demo, capsys):
    assert main(['--lang', 'it', 'run', str(demo)]) == 0
    out = capsys.readouterr().out
    assert 'Solo anteprima' in out and 'Totale fatturato' in out and 'Da controllare' in out
    report = next((demo / 'Report Ordo').glob('*.html')).read_text()
    assert 'lang="it"' in report and 'Fatture lette' in report and 'Imponibile + IVA' in report
    assert main(['--lang', 'it', 'run', str(demo), '--apply']) == 0
    assert (demo / 'Fatture').is_dir() and (demo / 'Immagini').is_dir() and not (demo / 'Invoices').exists()
    assert main(['undo', str(demo)]) == 0
