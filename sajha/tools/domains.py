"""
SAJHA MCP Server — tool domains: which domain a tool belongs to, and the readable label of a domain.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A tool's domain (GLOSSARY: Tool domain) is its tool folder, a proxied MCP server tool's prefix, or the
folder a remote SAJHA Net host publishes; a local tool at the root of the tools directory is "Unfiled".
Which domains exist is never listed here: it is whatever the registry serves. This module only holds
the one mapping of folder name to display label (a folder it does not know is title-cased) and the
grouping the Tools page, the Domains page, the landing page and the help pages share.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

#: The key the console uses for "Unfiled" (root) tools; ``?domain=unfiled`` on /tools selects it.
UNFILED_KEY = '__unfiled__'
UNFILED_LABEL = 'Unfiled'

#: Display labels for folder names whose title case reads badly. Only labels: a domain shows up because
#: the registry has tools in it, not because it is named here.
_LABELS: Dict[str, str] = {
    'alphavantage': 'Alpha Vantage',
    'calc': 'Calculators',
    'coingecko': 'CoinGecko',
    'duckdb': 'DuckDB',
    'ecb': 'ECB',
    'edgar': 'SEC EDGAR',
    'fbi': 'FBI',
    'fmp': 'Financial Modeling Prep',
    'fred': 'FRED',
    'imf': 'IMF',
    'llm': 'LLM Tools',
    'msdoc': 'Microsoft Office Documents',
    'olap': 'OLAP',
    'openbb': 'OpenBB',
    'qlrisk': 'QLRisk',
    'sajha': 'SAJHA',
    'sharepoint': 'SharePoint',
    'sqlselect': 'SQL Select',
    'webcrawler': 'Web Crawler',
    'worldbank': 'World Bank',
    'yahoo': 'Yahoo Finance',
}
_SMALL = {'of', 'and', 'the', 'de', 'for', 'in', 'on'}


def domain_label(domain: str) -> str:
    """The readable label of a domain key (a folder name, a proxied server's prefix, or UNFILED_KEY)."""
    if domain == UNFILED_KEY:
        return UNFILED_LABEL
    if domain in _LABELS:
        return _LABELS[domain]
    words = [w for w in str(domain or '').replace('-', '_').split('_') if w]
    return ' '.join(w if i and w in _SMALL else w[:1].upper() + w[1:] for i, w in enumerate(words)) or '—'


def tool_domain(registry, tool: dict) -> dict:
    """The Tools page's grouping of one tool: ``folder`` (its tool folder; '' at the root; None without a
    config file), ``domain`` (the folder; a proxied MCP server tool's prefix; a remote SAJHA Net tool's
    published folder, when its host sends one) and ``unfiled`` (a local tool with no domain: the root)."""
    name = str(tool.get('name') or '')
    net = ((tool.get('_meta') or {}).get('io.sajha/net') or {})
    if net.get('locality') == 'remote':
        folder = net.get('folder') if isinstance(net.get('folder'), str) else ''
        return {'folder': folder or None, 'domain': folder, 'unfiled': False}
    tool_folder = getattr(registry, 'tool_folder', None)
    folder = tool_folder(name) if callable(tool_folder) else None
    if folder:
        return {'folder': folder, 'domain': folder, 'unfiled': False}
    if folder is None and '__' in name:            # a proxied (federated or external) MCP server's tool
        return {'folder': None, 'domain': name.split('__', 1)[0], 'unfiled': False}
    return {'folder': folder, 'domain': '', 'unfiled': True}


def domain_key(d: dict) -> str:
    """The key of a tool_domain() result: its domain, UNFILED_KEY at the root ('' : no domain)."""
    return UNFILED_KEY if d.get('unfiled') else (d.get('domain') or '')


def key_of_name(registry, name: str, tool=None) -> str:
    """The domain key of a registered tool by name (its MCP form is built only when the name alone
    cannot tell, i.e. it has no config file)."""
    d = tool_domain(registry, {'name': name})
    if d.get('folder') is None and tool is not None:
        try:
            d = tool_domain(registry, tool.to_mcp_format())
        except Exception:
            pass
    return domain_key(d)


def query_key(value: Optional[str]) -> str:
    """The domain key a ``?domain=`` value selects ('unfiled', any case, is the root)."""
    v = str(value or '').strip()
    return UNFILED_KEY if v.lower() in ('unfiled', UNFILED_KEY) else v


def summarize(registry, tools: List[dict], visible: Optional[Callable[[str], bool]] = None) -> List[dict]:
    """One entry per domain of ``tools`` (MCP-format dicts) that ``visible`` lets through: key, label,
    count, folder (the tool folder, None for proxied or remote domains), kind and the /tools link;
    biggest first."""
    out: Dict[str, dict] = {}
    for t in tools:
        name = str(t.get('name') or '')
        if visible is not None and not visible(name):
            continue
        d = tool_domain(registry, t)
        key = domain_key(d)
        if not key:
            continue
        e = out.setdefault(key, {
            'key': key, 'label': domain_label(key), 'count': 0,
            'folder': '' if key == UNFILED_KEY else d.get('folder'),
            'kind': 'unfiled' if key == UNFILED_KEY else ('folder' if d.get('folder') else 'proxied'),
            'href': '/tools?domain=' + ('unfiled' if key == UNFILED_KEY else key)})
        e['count'] += 1
    return sorted(out.values(), key=lambda e: (-e['count'], e['label'].lower()))
