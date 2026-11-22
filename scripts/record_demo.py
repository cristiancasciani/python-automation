"""Build the static showcase in docs/: an animated terminal replaying a real run + the sample reports, in IT and EN.

    python scripts/record_demo.py

For each language it creates a demo folder in a temporary home, runs `ordo --lang XX run ~/Downloads --apply`
with a recording console, and writes docs/index.html, docs/report-XX.html and docs/report-XX.xlsx.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / 'docs'
SPINNER = re.compile(r'(Scanning files|Reading invoices|Moving and renaming|Writing the report|'
                     r'Analizzo i file|Leggo le fatture|Sposto e rinomino|Scrivo il report)…')


def record(lang: str) -> list[str]:
    home = Path(tempfile.mkdtemp(prefix='ordo-home-'))
    os.environ['HOME'] = str(home)  # paths print as ~/Downloads
    folder = home / 'Downloads'
    subprocess.run([sys.executable, str(ROOT / 'scripts' / 'make_demo.py'), str(folder)], check=True, capture_output=True)

    from rich.console import Console

    import ordo.cli as cli
    cli.console = Console(record=True, width=92, force_terminal=True, color_system='truecolor', highlight=False)
    cli.main(['--lang', lang, 'run', str(folder), '--apply'])
    html = cli.console.export_html(inline_styles=True, code_format='{code}')
    # Local file links make no sense on the web: point them to the published copies.
    html = re.sub(r'<a href="[^"]*\.html">', f'<a href="report-{lang}.html">', html)
    html = re.sub(r'<a href="[^"]*\.xlsx">', f'<a href="report-{lang}.xlsx">', html)
    lines = [l for l in html.split('\n') if not SPINNER.search(l)]

    from ordo.i18n import folder_name
    reports = sorted((folder / folder_name('Reports')).glob('*'))
    shutil.copy(next(p for p in reports if p.suffix == '.html'), DOCS / f'report-{lang}.html')
    shutil.copy(next(p for p in reports if p.suffix == '.xlsx'), DOCS / f'report-{lang}.xlsx')
    shutil.rmtree(home)
    return lines


def main():
    DOCS.mkdir(exist_ok=True)
    for old in ('report.html', 'report.xlsx'):
        (DOCS / old).unlink(missing_ok=True)
    lines = {lang: record(lang) for lang in ('it', 'en')}
    page = (ROOT / 'scripts' / 'showcase.html').read_text()
    page = page.replace('/*LINES*/{}', json.dumps(lines))
    (DOCS / 'index.html').write_text(page, encoding='utf-8')
    print(f'Wrote {DOCS}/index.html and the IT/EN reports')


if __name__ == '__main__':
    main()
