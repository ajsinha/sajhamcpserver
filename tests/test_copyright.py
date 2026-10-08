# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
SAJHA is proprietary software owned by Ashutosh Sinha (owner decision): no open-source licence.
Every tracked source file carries the copyright notice near its top, the repository and the
client SDK carry the proprietary LICENSE, and the console footer states ownership.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTICE = 'Ashutosh Sinha'


def _tracked(*patterns):
    out = subprocess.run(['git', 'ls-files', *patterns], cwd=ROOT, capture_output=True, text=True).stdout
    return [p for p in out.splitlines() if p and not p.startswith(('docs/archive/', 'data/', 'logs/'))]


def test_every_source_file_carries_the_notice():
    missing = []
    for rel in _tracked('*.py', '*.js', '*.html', '*.css', '*.sh'):
        path = ROOT / rel
        if not path.exists():
            continue
        if NOTICE not in path.read_text(encoding='utf-8', errors='replace')[:1500]:
            missing.append(rel)
    assert not missing, f'files without the copyright notice: {missing[:20]}'


def test_proprietary_licence_files():
    for rel in ('LICENSE', 'clientsdk/LICENSE'):
        text = (ROOT / rel).read_text(encoding='utf-8')
        assert 'Ashutosh Sinha' in text and 'All rights reserved' in text and 'not open source' in text


def test_console_footer_states_ownership():
    base = (ROOT / 'sajha/web/templates/common/base.html').read_text(encoding='utf-8')
    assert 'All rights reserved' in base and 'Proprietary' in base and 'app_author_email' in base
