"""
Every tool fetches through the outbound fetch guard (sajha/core/outbound.py).

Scans the tool implementations (sajha/tools/impl/, and sajha/ir/ behind the investor_relations tools)
for direct network use: urllib's urlopen or openers, requests, httpx, aiohttp, urllib3, http.client,
raw sockets, and SDKs that open their own connections. Each hit must be either routed through
``outbound`` or listed in ALLOWED below with the reason it cannot be; a listed entry that no longer
matches anything fails too, so the list stays true. Docs: docs/security/Security Model.md
("Outbound fetches by tools").

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNED = [ROOT / 'sajha' / 'tools' / 'impl', ROOT / 'sajha' / 'ir']
SKIP_FILES = {'sajha/ir/demo.py'}        # a command-line demo, never loaded by a tool

PATTERNS = {
    'urlopen': re.compile(r'(?<!outbound\.)\burlopen\s*\('),
    'opener': re.compile(r'\bbuild_opener\s*\(|\bOpenerDirector\b'),
    'requests': re.compile(r'^\s*(import requests\b|from requests\b)', re.M),
    'httpx': re.compile(r'^\s*(import httpx\b|from httpx\b)', re.M),
    'aiohttp': re.compile(r'^\s*(import aiohttp\b|from aiohttp\b)', re.M),
    'urllib3': re.compile(r'^\s*(import urllib3\b|from urllib3\b)', re.M),
    'http.client': re.compile(r'\bhttp\.client\.(HTTPConnection|HTTPSConnection)\b|^\s*from http\.client import .*HTTPS?Connection', re.M),
    'socket': re.compile(r'\bsocket\.(create_connection|socket)\s*\('),
    'yfinance': re.compile(r'^\s*(import yfinance\b|from yfinance\b)', re.M),
    'openbb': re.compile(r'^\s*(import openbb\b|from openbb\b)', re.M),
    'playwright': re.compile(r'^\s*(import playwright\b|from playwright\b)', re.M),
}

#: (file, pattern) -> why it is not routed through the guard. Keep each reason true.
ALLOWED = {
    # yfinance opens its own curl_cffi session (Yahoo's cookie and crumb); it cannot be pointed at the
    # guard or tools.outbound.proxy. Known limit: Security Model, Yahoo Finance guide.
    ('sajha/tools/impl/yfinance_tools.py', 'yfinance'): 'yfinance SDK (curl_cffi), host fixed to Yahoo',
    ('sajha/tools/impl/yahoo_finance_tool.py', 'yfinance'): 'yfinance SDK (curl_cffi), host fixed to Yahoo',
    # OpenBB's provider extensions fetch with their own aiohttp/requests clients. Known limit:
    # Security Model, OpenBB guide.
    ('sajha/tools/impl/openbb_tools.py', 'openbb'): 'OpenBB Platform SDK, provider hosts fixed by OpenBB',
    # Headless Chromium for render_js: every request it makes is intercepted by a context route and
    # fetched through the guard (sajha/tools/impl/webcrawler_render.py); the browser has no network.
    ('sajha/tools/impl/webcrawler_render.py', 'playwright'): 'browser requests are routed through the guard',
}


def _hits():
    out = {}
    for base in SCANNED:
        for path in sorted(base.rglob('*.py')):
            rel = path.relative_to(ROOT).as_posix()
            if rel in SKIP_FILES or '__pycache__' in rel:
                continue
            text = path.read_text(encoding='utf-8')
            code = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))
            for name, rx in PATTERNS.items():
                if rx.search(code):
                    out[(rel, name)] = True
    return out


def test_no_tool_fetches_around_the_outbound_guard():
    hits = _hits()
    unlisted = sorted(k for k in hits if k not in ALLOWED)
    assert not unlisted, ('direct network use outside sajha.core.outbound (route it through '
                          'outbound.request / outbound.urlopen / outbound.requests_compat, or add it to '
                          f'ALLOWED with the reason): {unlisted}')


def test_allowlist_entries_still_match():
    hits = _hits()
    stale = sorted(k for k in ALLOWED if k not in hits)
    assert not stale, f'ALLOWED entries that no longer match anything (remove them): {stale}'


def test_the_scan_sees_a_direct_fetch(tmp_path):
    """The patterns catch the usual forms (a regression guard for the scanner itself)."""
    samples = {
        'urlopen': 'with urllib.request.urlopen(req, timeout=5) as r:\n    pass\n',
        'opener': 'o = urllib.request.build_opener()\n',
        'requests': 'import requests\n',
        'httpx': 'import httpx\n',
        'socket': 's = socket.create_connection(("h", 80))\n',
    }
    for name, text in samples.items():
        assert PATTERNS[name].search(text), name
    assert not PATTERNS['urlopen'].search('with outbound.urlopen(req, timeout=5) as r:\n')
