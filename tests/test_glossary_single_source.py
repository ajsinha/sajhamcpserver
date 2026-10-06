"""
One glossary: GLOSSARY.md, rendered at /glossary and looked up by every page's
"About this page" panel.

There used to be a hand-written help glossary page and a "Page Glossary" block in 25
templates, and they disagreed with GLOSSARY.md and with the code: passwords "hashed with
SHA-256" (bcrypt), roles "admin, user, readonly" (the seeded roles are admin, user,
viewer, developer), monitoring "via WebSocket" (it polls). Now a definition exists in
exactly one place, and these tests keep it there.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

import glob
import os
import re

import pytest

from sajha.web.glossary import GLOSSARY_PATH, load_glossary, lookup
from sajha.web.page_help import PAGE_HELP

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(REPO, 'sajha', 'web', 'templates')


def _rows():
    return [l for l in GLOSSARY_PATH.read_text(encoding='utf-8').splitlines() if l.startswith('| **')]


def test_loader_reads_every_row():
    assert sum(len(s['terms']) for s in load_glossary()) == len(_rows()) > 100


def test_every_section_is_numbered_and_has_terms():
    sections = load_glossary()
    assert len(sections) >= 10
    for s in sections:
        assert s['terms'], f"section {s['title']!r} has no terms"
        assert re.match(r'^\d+-', s['id']), s['id']       # GitHub-compatible anchor


def test_term_anchors_are_unique():
    ids = [t['id'] for s in load_glossary() for t in s['terms']]
    ids += [s['id'] for s in load_glossary()]
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f'two glossary entries share an anchor: {dupes}'


@pytest.mark.parametrize('endpoint', sorted(PAGE_HELP))
def test_every_page_help_term_is_in_the_glossary(endpoint):
    missing = [n for n in PAGE_HELP[endpoint]['terms'] if lookup(n) is None]
    assert not missing, f'{endpoint}: add these terms to GLOSSARY.md first: {missing}'


def test_every_page_help_entry_is_complete():
    for ep, e in PAGE_HELP.items():
        assert set(e) == {'what', 'terms', 'guide'}, ep
        assert e['what'] and e['terms'] and e['guide'].endswith('.md'), ep


def test_no_template_keeps_its_own_definitions():
    offenders = []
    for path in glob.glob(os.path.join(TEMPLATES, '**', '*.html'), recursive=True):
        text = open(path, encoding='utf-8').read()
        if ('block page_glossary' in text or 'Page Glossary' in text or 'pageGlossary' in text
                or 'Glossary.md' in text):
            offenders.append(os.path.relpath(path, TEMPLATES))
    assert not offenders, f'templates with hand-written definitions: {offenders}'
    assert not os.path.exists(os.path.join(TEMPLATES, 'help', 'help_glossary.html'))


def test_the_glossary_page_renders_every_term(web):
    c, _ = web
    c.cookies.clear()
    body = c.get('/glossary').text
    assert body.count('class="gl-term"') == len(_rows())
    # the definition the templates used to get wrong
    assert 'bcrypt' in lookup('Password hash')['html'] and lookup('Password hash')['html'] in body


def test_the_old_address_redirects(web):
    c, _ = web
    c.cookies.clear()
    r = c.get('/help/glossary', follow_redirects=False)
    assert r.status_code == 301 and r.headers['location'] == '/glossary'


def test_page_help_shows_the_glossary_definition(web):
    c, admin = web
    c.cookies.clear()
    body = c.get('/admin/users/create', cookies=admin).text
    row = lookup('Password hash')
    assert row['html'] in body and 'href="/glossary#password-hash"' in body
