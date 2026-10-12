# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Console translation framework (sajha/web/i18n.py; docs/architecture/Architecture.md §10,
"Languages"). SAJHA ships English only: these tests check that the template catalog
(sajha.pot) is current, that wrapped strings render in English, that a language with no
catalog falls back to English, that there is no language picker, and, with a fake catalog in
a temporary folder, that the framework would pick a language up if one were added.
"""

import re
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from sajha.web import i18n  # noqa: E402

#: Templates whose visible text is fully wrapped for translation. A template added here must
#: have no literal English outside {{ _() }} / {% trans %} (product names excepted).
TRANSLATED_TEMPLATES = [
    'common/base.html', 'common/_nav.html', 'common/_page_help.html', 'common/_theme_menu.html',
    'common/error.html', 'common/_notices_banner.html', 'common/_notices_badge.html',
    'help/_help_footer.html', 'auth/login.html', 'auth/change_password.html',
    'dashboard/dashboard.html', 'dashboard/_system_status.html', 'tools/tools_domains.html',
    'tools/tools_list.html', 'help/index.html', 'help/guides.html', 'help/glossary.html',
    # the SAJHA Net management pages (design §17.1)
    'admin/sajhanet_reviews.html', 'admin/sajhanet_users.html', 'admin/sajhanet_blocks.html',
    'admin/sajhanet_keys.html', 'admin/sajhanet_snapshots.html', 'admin/sajhanet_activity.html',
    'admin/sajhanet_certificates.html', 'admin/sajhanet_settings.html', 'admin/sajhanet_sponsored.html',
    'admin/sajhanet_changes.html', 'admin/_sajhanet_change_dialog.html', 'admin/_sajhanet_subnav.html',
    'admin/_sajhanet_netsel.html', 'admin/_sajhanet_changes_table.html', 'net/_instance_tabs.html',
    'net/_instance_admin.html',
]
#: Words that stay English in every language: product, protocol and transport names.
UNTRANSLATED = {'SAJHA', 'MCP Server', 'SAJHA MCP Server', 'SAJHA MCP Server v', 'MCP Server v', 'HTTP', 'SSE',
                'WebSocket', 'Ask SAJHA', 'MCP Studio', 'Python Playground'}


class _Req:
    def __init__(self, accept=None, cookies=None):
        self.cookies = cookies or {}
        self.headers = {'accept-language': accept} if accept else {}
        self.state = SimpleNamespace()


def _write_mo(path: Path, messages: dict) -> None:
    """A minimal GNU .mo file (what msgfmt / Babel write) for ``messages`` {msgid: msgstr}."""
    entries = {'': 'Content-Type: text/plain; charset=UTF-8\n', **messages}
    keys = sorted(entries)
    ids = [k.encode('utf-8') for k in keys]
    strs = [entries[k].encode('utf-8') for k in keys]
    n = len(keys)
    start = 7 * 4 + 16 * n
    offsets, blob = [], b''
    for b in ids:
        offsets.append((len(b), start + len(blob)))
        blob += b + b'\0'
    toffsets = []
    for b in strs:
        toffsets.append((len(b), start + len(blob)))
        blob += b + b'\0'
    out = struct.pack('<7I', 0x950412de, 0, n, 7 * 4, 7 * 4 + 8 * n, 0, 0)
    out += b''.join(struct.pack('<2I', *o) for o in offsets)
    out += b''.join(struct.pack('<2I', *o) for o in toffsets)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out + blob)


@pytest.fixture
def fake_catalog(tmp_path, monkeypatch):
    """A temporary locale folder with one compiled catalog, ``xx`` (never shipped)."""
    _write_mo(tmp_path / 'xx' / 'LC_MESSAGES' / 'sajha.mo',
              {'Dashboard': 'XX-Dashboard', 'Sign in to continue': 'XX-Sign-in-to-continue'})
    monkeypatch.setattr(i18n, 'LOCALE_DIR', str(tmp_path))
    i18n.reset_cache()
    yield tmp_path
    monkeypatch.undo()
    i18n.reset_cache()


# ── English only ─────────────────────────────────────────────────────────────

def test_english_only_ships():
    i18n.reset_cache()
    assert i18n.available_languages() == ('en',)
    locale = ROOT / 'sajha' / 'web' / 'locale'
    assert (locale / 'sajha.pot').is_file()
    assert not [d for d in locale.iterdir() if d.is_dir()], 'no language catalog is shipped (owner decision)'


def test_accept_language_parsing_orders_by_quality():
    assert i18n.parse_accept_language('de;q=0.5, fr-CA, en;q=0.8, *;q=0.1, es;q=0') == ['fr-CA', 'en', 'de']
    assert i18n.parse_accept_language('') == []


def test_a_language_with_no_catalog_falls_back_to_english(monkeypatch):
    i18n.reset_cache()
    assert i18n.select_language(_Req(accept='fr-FR, fr;q=0.9, de')) == 'en'
    assert i18n.select_language(_Req(cookies={'sajha_lang': 'fr'})) == 'en'
    assert i18n.select_language(None) == 'en'
    monkeypatch.setenv('SAJHA_CONSOLE_DEFAULT_LANGUAGE', 'fr')
    assert i18n.select_language(_Req()) == 'en'
    assert i18n.translations('fr').gettext('Dashboard') == 'Dashboard'
    assert i18n.translations('en').ngettext('%(num)d tool', '%(num)d tools', 2) == '%(num)d tools'
    assert i18n.js_catalog_src('fr') is None and i18n.js_catalog_src('en') is None


# ── Rendering in English, no picker ─────────────────────────────────────────

def test_wrapped_strings_render_in_english(web):
    c, admin = web
    login = c.get('/login', headers={'Accept-Language': 'fr-FR,fr;q=0.9'}).text
    assert 'lang="en"' in login and 'Sign in to continue' in login
    html = c.get('/dashboard', cookies=admin, headers={'Accept-Language': 'fr'}).text
    assert 'lang="en"' in html
    for en in ('Dashboard', 'Log out', 'About this page'):
        assert en in html, en
    assert 'js/i18n.js' in html and '/static/i18n/' not in html          # _t() is English; no catalog
    page = c.get('/no-such-page-xyz', cookies=admin)
    assert page.status_code == 404 and 'Page Not Found' in page.text


def test_there_is_no_language_picker(web):
    c, admin = web
    for html in (c.get('/login').text, c.get('/dashboard', cookies=admin).text):
        assert '/account/language' not in html and 'language-toggle' not in html
    assert c.post('/account/language', data={'lang': 'fr'}, follow_redirects=False).status_code in (404, 405)
    tpl = ROOT / 'sajha' / 'web' / 'templates' / 'common'
    assert not (tpl / '_language_items.html').exists() and not (tpl / '_language_menu.html').exists()


# ── The framework, proven with a temporary catalog ──────────────────────────

def test_a_compiled_catalog_would_be_picked_up(fake_catalog, monkeypatch):
    assert i18n.available_languages() == ('en', 'xx')
    assert i18n.select_language(_Req(accept='de, xx-YY;q=0.9')) == 'xx'
    assert i18n.select_language(_Req(accept='de')) == 'en'
    monkeypatch.setenv('SAJHA_CONSOLE_DEFAULT_LANGUAGE', 'xx')
    assert i18n.select_language(_Req()) == 'xx'
    xx = i18n.translations('xx')
    assert xx.gettext('Dashboard') == 'XX-Dashboard'
    assert xx.gettext('A string nobody translated') == 'A string nobody translated'


def test_a_compiled_catalog_translates_the_templates(fake_catalog):
    from jinja2 import DictLoader, Environment
    env = Environment(loader=DictLoader({'t.html': (
        '<html lang="{{ console_lang() }}">{{ _("Dashboard") }}|{{ _("Log out") }}|'
        '{% trans n=2 %}{{ n }} items{% endtrans %}</html>')}), autoescape=True)
    i18n.install(env)
    xx = env.get_template('t.html').render(request=_Req(accept='xx'))
    assert xx == '<html lang="xx">XX-Dashboard|Log out|2 items</html>'
    en = env.get_template('t.html').render(request=_Req(accept='fr'))
    assert en == '<html lang="en">Dashboard|Log out|2 items</html>'


# ── The template catalog is current ─────────────────────────────────────────

def _scripts():
    sys.path.insert(0, str(ROOT / 'scripts'))
    import importlib
    return importlib.import_module('i18n')


def test_pot_is_current():
    """sajha.pot matches the wrapped strings of the templates, page scripts, page help and help
    catalog (after wrapping a string, run ``python scripts/i18n.py extract``), so a language can
    be started from it at any time (``scripts/i18n.py init <lang>``)."""
    pytest.importorskip('babel')
    tool = _scripts()
    built = {m.id for m in tool.build_catalog() if m.id}
    shipped = {m.id for m in tool._read(tool.POT) if m.id}
    assert built == shipped, ('run python scripts/i18n.py extract; new: '
                              f'{sorted(map(str, built - shipped))[:5]} gone: {sorted(map(str, shipped - built))[:5]}')
    assert tool.languages() == []


# ── No unwrapped English in the translated templates ────────────────────────

_STRIP = [re.compile(p, re.S) for p in (
    r'\{#.*?#\}', r'<!--.*?-->', r'<script\b.*?</script>', r'<style\b.*?</style>',
    r'\{%-?\s*trans\b.*?endtrans\s*-?%\}',
    # code, samples and user input stay as they are in every language
    r'<(code|pre|kbd|samp|textarea)\b.*?</\1>')]
_JINJA = re.compile(r'\{\{.*?\}\}|\{%.*?%\}', re.S)
_TEXT = re.compile(r'>([^<>]*)<')
_ATTR = re.compile(r'\b(?:title|placeholder|aria-label|alt|data-confirm|data-label)="([^"]*)"')
_WORD = re.compile(r'[A-Za-z]{2,}')
#: Vendor, product and format names: a fragment made only of these (and of acronyms,
#: identifiers, paths and numbers) is not prose and is left as it is.
NAME_WORDS = {
    'SAJHA', 'GitHub', 'Google', 'Atlassian', 'Jira', 'Confluence', 'SharePoint', 'LiveLink',
    'Power', 'PowerBI', 'PostgreSQL', 'SQLite', 'Redis', 'DuckDB', 'Docker', 'Kubernetes', 'Helm',
    'Python', 'JavaScript', 'TypeScript', 'OpenAPI', 'GraphQL', 'OAuth', 'OpenAI', 'Anthropic',
    'Ollama', 'Claude', 'Gemini', 'Azure', 'Bedrock', 'Pyodide', 'WebSocket', 'Prometheus',
    'Grafana', 'OpenTelemetry', 'Splunk', 'Slack', 'Swagger', 'Markdown', 'Jinja', 'Babel',
    'Bearer', 'Mermaid', 'Vega', 'Chart', 'Excel', 'Wikipedia', 'Wikidata', 'Yahoo', 'Finance',
    'Mistral', 'Cohere', 'Groq', 'HuggingFace', 'LangChain', 'Qdrant', 'Pinecone', 'Chroma',
    'Weaviate', 'Milvus', 'MySQL', 'Oracle', 'Snowflake', 'BigQuery', 'ClickHouse', 'MongoDB',
    'Elasticsearch', 'OpenSearch', 'Kafka', 'QuantLib', 'Linux', 'macOS', 'Windows', 'Chrome',
    'Firefox', 'Safari', 'Node', 'npx', 'uvx', 'stdio', 'Streamable',
}


def _is_name(chunk: str) -> bool:
    """A word that stays as it is: a name, an acronym, an identifier, a path or a number."""
    w = chunk.strip('.,;:!?()[]"\'«»“”‘’·—–-')
    return (not w or w in NAME_WORDS or bool(re.fullmatch(r'[A-Z0-9]{2,6}s?', w))
            or bool(re.search(r'[_./:=@{}\[\]<>#$\\]|\d', w)) or not _WORD.search(w))


def is_prose(text: str) -> bool:
    """True when ``text`` has a word to translate (not only names, acronyms and identifiers)."""
    text = re.sub(r'&#?\w+;', ' ', text).strip()
    return bool(text) and text not in UNTRANSLATED and not all(_is_name(c) for c in text.split())


def unwrapped(source: str) -> list:
    """Literal English left outside {{ _() }} / {% trans %} in a template's markup."""
    for pat in _STRIP:
        source = pat.sub(' ', source)
    source = _JINJA.sub('\x00', source)
    found = []
    for text in _TEXT.findall(source) + _ATTR.findall(source):
        bits = [re.sub(r'&#?\w+;', '', b).strip(' \n\t·—:,.()+') for b in text.split('\x00')]
        for b in bits:
            if b and _WORD.search(b) and is_prose(b):
                found.append(b)
    return found


def test_unwrapped_detector_finds_hard_coded_english():
    assert unwrapped('<p>Hello world</p>') == ['Hello world']
    assert unwrapped('<p>{{ _("Hello world") }}</p><b title="{{ _(\'x\') }}">{{ n }}</b>') == []
    assert unwrapped('<button aria-label="Close">x</button>') == ['Close']
    assert unwrapped('<p>{% trans %}Hi <a href="/">there</a>{% endtrans %}</p>') == []


@pytest.mark.parametrize('name', TRANSLATED_TEMPLATES)
def test_translated_templates_have_no_unwrapped_english(name):
    path = ROOT / 'sajha' / 'web' / 'templates' / name
    left = unwrapped(path.read_text(encoding='utf-8'))
    assert not left, f'{name}: wrap these in {{{{ _() }}}}: {left[:8]}'


def test_nav_menu_labels_are_wrapped():
    """The menu is data (tuples of strings): every label and description goes through _()."""
    src = (ROOT / 'sajha/web/templates/common/_nav.html').read_text(encoding='utf-8')
    menu = src.split('<nav class="navbar')[0]
    bare = re.findall(r"'[\w-]+', '([A-Z][^']+)', '([^']+)'\)", menu)
    assert not bare, f'unwrapped menu items: {bare[:5]}'
