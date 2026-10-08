"""
Console pages under a strict Content-Security-Policy (roadmap X6).

* No template carries an inline event handler attribute (onclick=, onchange=, ...): the CSP
  refuses them. Handlers are data-on* attributes run by sajha/web/static/js/csp-actions.js.
* Every data-on* handler is a program in csp-actions.js's small language (checked here with the
  same grammar), and every function it calls is declared by a page script or a static file.
* Every inline <script> element carries the response's nonce.
* Every page that renders a document loads csp-actions.js.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / 'sajha' / 'web'
TEMPLATES = sorted((WEB / 'templates').rglob('*.html'))
STATIC_JS = sorted((WEB / 'static' / 'js').glob('*.js'))

_HANDLER = re.compile(r'''\son[a-z]+\s*=\s*\\?["']''', re.I)
_DATA_ON = re.compile(r'data-on([a-z]+)="([^"]*)"')


def _tokens(src):
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if c in '();,.':
            out.append(('p', c))
            i += 1
            continue
        if c in '\'"':
            j, s = i + 1, ''
            while j < n and src[j] != c:
                if src[j] == '\\' and j + 1 < n:
                    s += src[j + 1]
                    j += 2
                else:
                    s += src[j]
                    j += 1
            if j >= n:
                raise ValueError('unterminated string')
            out.append(('s', s))
            i = j + 1
            continue
        m = re.match(r'-?\d+(\.\d+)?', src[i:]) or None
        if m:
            out.append(('n', m.group(0)))
            i += len(m.group(0))
            continue
        m = re.match(r'[A-Za-z_$][\w$]*', src[i:])
        if m:
            out.append(('i', m.group(0)))
            i += len(m.group(0))
            continue
        raise ValueError(f'unexpected character {c!r}')
    return out


def parse(src):
    """The grammar of csp-actions.js; returns the names called. Raises ValueError."""
    toks, pos, called = _tokens(src), [0], []

    def peek(v=None):
        t = toks[pos[0]] if pos[0] < len(toks) else None
        return t if t and (v is None or t[1] == v) else None

    def take(v=None):
        t = peek(v)
        if t is None:
            raise ValueError(f'expected {v or "a value"} in {src!r}')
        pos[0] += 1
        return t

    def argument():
        t = take()
        if t[0] in ('s', 'n') or t[1] in ('true', 'false', 'null', 'undefined'):
            return
        if t[1] in ('this', 'event'):
            if peek('.'):
                take('.')
                if not re.fullmatch(r'[A-Za-z_]\w*', take()[1]):
                    raise ValueError('bad property')
            return
        raise ValueError(f'unknown name {t[1]!r} in {src!r}')

    def call(name):
        called.append(name)
        take('(')
        if not peek(')'):
            argument()
            while peek(','):
                take(',')
                argument()
        take(')')

    while pos[0] < len(toks):
        if peek(';'):
            take(';')
            continue
        t = take()
        if t == ('i', 'return'):
            v = take()
            if v[0] == 'i' and peek('('):
                call(v[1])
            else:
                pos[0] -= 1
                argument()
        elif t[0] == 'i' and peek('('):
            call(t[1])
        else:
            raise ValueError(f'expected a call in {src!r}')
        if pos[0] < len(toks):
            take(';')
    return called


def _sample(value: str) -> str:
    """Handlers built in script: replace runtime pieces with a sample literal."""
    v = re.sub(r'\{\{.*?\}\}', '1', value)
    v = re.sub(r'\$\{[^}]*\}', '1', v)
    v = re.sub(r"\\'\s*\+\s*[^+]+?\s*\+\s*\\'", "'x'", v)     # \'' + t.name + '\'
    v = re.sub(r"'\s*\+\s*[^+']+?\s*\+\s*'", "x", v)           # '+t.task_id+'
    return v.replace("\\'", "'")


def test_no_inline_event_handlers_in_templates():
    bad = []
    for f in TEMPLATES:
        for n, line in enumerate(f.read_text(encoding='utf-8').splitlines(), 1):
            if _HANDLER.search(line):
                bad.append(f'{f.relative_to(WEB)}:{n}: {line.strip()[:100]}')
    assert not bad, 'inline event handlers (the CSP refuses them; use data-on*):\n' + '\n'.join(bad)


def test_no_inline_event_handlers_in_static_js():
    bad = [f'{f.name}:{n}' for f in STATIC_JS
           for n, line in enumerate(f.read_text(encoding='utf-8').splitlines(), 1)
           if _HANDLER.search(line) or re.search(r'''setAttribute\(\s*['"]on''', line)]
    assert not bad, bad


def test_every_handler_parses_and_calls_a_page_function():
    sources = {f: f.read_text(encoding='utf-8') for f in TEMPLATES + STATIC_JS}
    problems, seen = [], 0
    for f in TEMPLATES:
        for event, value in _DATA_ON.findall(sources[f]):
            seen += 1
            try:
                names = parse(_sample(value))
            except ValueError as e:
                problems.append(f'{f.name}: data-on{event}="{value}": {e}')
                continue
            for name in names:
                if name == 'confirm':
                    continue
                decl = re.compile(rf'(^|[^\w.])(async\s+)?function\s+{re.escape(name)}\s*\(|window\.{re.escape(name)}\s*=')
                if not any(decl.search(s) for s in sources.values()):
                    problems.append(f'{f.name}: {name}() is not declared as a global function')
    assert seen > 100
    assert not problems, '\n'.join(problems)


def test_grammar_refuses_script():
    # eval('1') parses, and is refused when it runs: built-in functions are never called
    for src in ('this.ownerDocument.defaultView.eval(1)', "location.href='x'",
                "a=1", "foo(bar)", "foo(1)+1", "(function(){})()"):
        with pytest.raises(ValueError):
            parse(src)
    assert parse("return confirm('Sure?')") == ['confirm']
    assert parse("changePage(3); return false;") == ['changePage']
    assert parse("return addPeer(event, 'n', this)") == ['addPeer']


def test_inline_scripts_carry_the_nonce():
    bad = []
    for f in TEMPLATES:
        for m in re.finditer(r'<script\b([^>]*)>', f.read_text(encoding='utf-8')):
            attrs = m.group(1)
            if 'application/json' in attrs:        # data, never run: CSP does not apply
                continue
            if 'src=' not in attrs and 'nonce="{{ csp_nonce() }}"' not in attrs:
                bad.append(f'{f.relative_to(WEB)}: <script{attrs}>')
    assert not bad, bad


def test_documents_load_csp_actions():
    for f in TEMPLATES:
        s = f.read_text(encoding='utf-8')
        if '</head>' in s:
            assert 'js/csp-actions.js' in s, f'{f.relative_to(WEB)} does not load csp-actions.js'
