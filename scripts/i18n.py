#!/usr/bin/env python3
# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Console translations: extract, update, compile and check the gettext catalogs of the web console.

    python scripts/i18n.py extract          # templates, page scripts, page help, help catalog -> sajha/web/locale/sajha.pot
    python scripts/i18n.py init fr          # start a language: sajha/web/locale/fr/LC_MESSAGES/sajha.po
    python scripts/i18n.py update           # merge the .pot into every language's .po
    python scripts/i18n.py compile          # every .po -> .mo, and static/i18n/<lang>.js for page scripts
    python scripts/i18n.py check [--strict] # per language: translated / total; --strict fails on gaps

What is extracted: ``_()``, ``gettext()``, ``ngettext()`` and ``{% trans %}`` in
``sajha/web/templates/**.html`` (Jinja's i18n extension, trimmed); ``_t()`` and ``_nt()`` in the
page scripts (``sajha/web/static/js/*.js`` and the inline ``<script>`` blocks of the templates),
marked "page script" in the catalog; the "what" line of every entry in ``sajha/web/page_help.py``
(``PAGE_HELP``); the category names, blurbs, group titles and card titles, summaries and badges
of ``sajha/web/help_catalog.py`` (``CATALOG``); ``N_()`` in ``sajha/web/i18n.py`` (strings routes
pass to templates). ``compile`` writes each ``.mo`` and, from the page-script messages,
``sajha/web/static/i18n/<lang>.js`` (``window.SAJHA_I18N``, read by ``static/js/i18n.js``).
Needs Babel (a development tool; the server itself reads the ``.mo`` files with the stdlib
``gettext``). SAJHA ships English only: ``sajha.pot`` is kept current, and no language catalog
is committed; ``init`` starts one when a language is wanted. Guide: docs/architecture/Architecture.md §10, "Translating the console".

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TEMPLATES = os.path.join(ROOT, 'sajha', 'web', 'templates')
STATIC_JS = os.path.join(ROOT, 'sajha', 'web', 'static', 'js')
JS_CATALOGS = os.path.join(ROOT, 'sajha', 'web', 'static', 'i18n')
LOCALE = os.path.join(ROOT, 'sajha', 'web', 'locale')
POT = os.path.join(LOCALE, 'sajha.pot')
JINJA_OPTIONS = {'extensions': 'jinja2.ext.i18n', 'trimmed': 'true', 'newstyle_gettext': 'true'}
KEYWORDS = {'_': None, 'gettext': None, 'ngettext': (1, 2), 'pgettext': ((1, 'c'), 2),
            'npgettext': ((1, 'c'), 2, 3), 'N_': None}
#: The marker on page-script messages in the catalog (compile puts these in <lang>.js).
JS_COMMENT = 'page script'
#: An inline script of a template (not a src= script and not a JSON data block).
INLINE_SCRIPT = re.compile(r'<script\b(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>(.*?)</script>', re.S)


def _babel():
    try:
        import babel  # noqa: F401
    except ImportError:
        sys.exit('scripts/i18n.py needs Babel (pip install Babel); the server does not.')


def _rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace(os.sep, '/')


def template_messages():
    """(message or (singular, plural), file, line, context) from every template."""
    from babel.messages.extract import extract
    for base, _dirs, files in os.walk(TEMPLATES):
        for name in sorted(files):
            if not name.endswith('.html'):
                continue
            path = os.path.join(base, name)
            with open(path, 'rb') as fh:
                for lineno, message, _comments, context in extract(
                        'jinja2.ext:babel_extract', fh, keywords=KEYWORDS, options=JINJA_OPTIONS):
                    yield message, _rel(path), lineno, context


def _templates():
    for base, _dirs, files in os.walk(TEMPLATES):
        for name in sorted(files):
            if name.endswith('.html'):
                yield os.path.join(base, name)


def js_sources():
    """(path, source, first line) of every page script: static/js/*.js and the templates'
    inline scripts."""
    for name in sorted(os.listdir(STATIC_JS)):
        if name.endswith('.js') and name != 'i18n.js':     # i18n.js defines _t(); its comments name it
            path = os.path.join(STATIC_JS, name)
            with open(path, encoding='utf-8') as fh:
                yield path, fh.read(), 1
    for path in sorted(_templates()):
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
        for m in INLINE_SCRIPT.finditer(text):
            yield path, m.group(1), text.count('\n', 0, m.start(1)) + 1


#: A single- or double-quoted JS string literal (its text in group 1 or 2).
_JS_STR = r"'((?:[^'\\\n]|\\.)*)'" + '|' + r'"((?:[^"\\\n]|\\.)*)"'
JS_CALL = re.compile(r'(?<![\w$.])_t\(\s*(?:' + _JS_STR + r')')
JS_NCALL = re.compile(r'(?<![\w$.])_nt\(\s*(?:' + _JS_STR + r')\s*,\s*(?:' + _JS_STR + r')')


def _js_unescape(text: str) -> str:
    return re.sub(r'\\(.)', lambda m: {'n': '\n', 't': '\t'}.get(m.group(1), m.group(1)), text)


def js_messages():
    """(message, file, line, context) for every _t('...') / _nt('...', '...') in the page scripts.
    The message must be a quoted string literal (not a template literal or an expression)."""
    for path, source, first in js_sources():
        for m in JS_CALL.finditer(source):
            text = m.group(1) if m.group(1) is not None else m.group(2)
            yield _js_unescape(text), _rel(path), first + source.count('\n', 0, m.start()), None
        for m in JS_NCALL.finditer(source):
            one = m.group(1) if m.group(1) is not None else m.group(2)
            many = m.group(3) if m.group(3) is not None else m.group(4)
            yield (_js_unescape(one), _js_unescape(many)), _rel(path), first + source.count('\n', 0, m.start()), None


def help_catalog_messages():
    """Category names, blurbs and group titles, and each card's title, summary and badge."""
    from sajha.web.help_catalog import CATALOG
    for cat in CATALOG:
        where = f'help catalog: {cat["id"]}'
        for text in [cat.get('name'), cat.get('blurb')] + [g[0] for g in cat.get('groups') or []]:
            if text:
                yield text, where
        for t in cat['topics']:
            for text in (t.get('title'), t.get('summary'), t.get('badge')):
                if text:
                    yield text, where


def python_messages(path: str):
    from babel.messages.extract import extract
    with open(path, 'rb') as fh:
        for lineno, message, _comments, context in extract('python', fh, keywords={'N_': None}):
            yield message, _rel(path), lineno, context


def page_help_messages():
    from sajha.web.page_help import PAGE_HELP
    for key, entry in PAGE_HELP.items():
        if entry.get('what'):
            yield entry['what'], 'sajha/web/page_help.py', 0, None, f'page help: {key}'


def build_catalog():
    from babel.messages.catalog import Catalog
    cat = Catalog(project='SAJHA MCP Server console', copyright_holder='Ashutosh Sinha',
                  msgid_bugs_address='ajsinha@gmail.com', charset='utf-8')
    for message, path, lineno, context in template_messages():
        cat.add(message, locations=[(path, lineno)], context=context)
    for message, path, lineno, context in python_messages(os.path.join(ROOT, 'sajha', 'web', 'i18n.py')):
        if message:
            cat.add(message, locations=[(path, lineno)], context=context)
    for message, path, lineno, context, comment in page_help_messages():
        _note(cat, message, comment, path, lineno, context)
    for message, where in help_catalog_messages():
        _note(cat, message, where, 'sajha/web/help_catalog.py', 0, None)
    for message, path, lineno, context in js_messages():
        existing = cat.get(message, context=context)
        if existing is None:
            cat.add(message, locations=[(path, lineno)], context=context, auto_comments=[JS_COMMENT])
        else:
            existing.locations.append((path, lineno))
            if JS_COMMENT not in existing.auto_comments:
                existing.auto_comments.append(JS_COMMENT)
    return cat


def _note(cat, message, comment, path, lineno, context):
    existing = cat.get(message, context=context)
    if existing is not None:
        if comment not in existing.auto_comments:
            existing.auto_comments.append(comment)
    else:
        cat.add(message, locations=[(path, lineno)], context=context, auto_comments=[comment])


def languages():
    if not os.path.isdir(LOCALE):
        return []
    return sorted(d for d in os.listdir(LOCALE)
                  if os.path.isfile(os.path.join(LOCALE, d, 'LC_MESSAGES', 'sajha.po')))


def _po(lang: str) -> str:
    return os.path.join(LOCALE, lang, 'LC_MESSAGES', 'sajha.po')


def cmd_extract(_a) -> int:
    from babel.messages.pofile import write_po
    cat = build_catalog()
    os.makedirs(LOCALE, exist_ok=True)
    with open(POT, 'wb') as fh:
        write_po(fh, cat, width=100, sort_output=False, omit_header=False, include_lineno=True)
    print(f'{_rel(POT)}: {len(cat)} messages')
    return 0


def _read(path: str, locale=None):
    from babel.messages.pofile import read_po
    with open(path, 'rb') as fh:
        return read_po(fh, locale=locale)


def _write(path: str, cat) -> None:
    from babel.messages.pofile import write_po
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        write_po(fh, cat, width=100, include_lineno=True)


def cmd_init(a) -> int:
    template = _read(POT)
    from babel.messages.catalog import Catalog
    cat = Catalog(locale=a.lang, project=template.project, charset='utf-8')
    cat.update(template)
    _write(_po(a.lang), cat)
    print(f'{_rel(_po(a.lang))}: started from {len(template)} messages')
    return 0


def cmd_update(_a) -> int:
    template = _read(POT)
    for lang in languages():
        cat = _read(_po(lang), locale=lang)
        cat.update(template, no_fuzzy_matching=True)
        _write(_po(lang), cat)
        print(f'{_rel(_po(lang))}: updated')
    return 0


def cmd_compile(_a) -> int:
    from babel.messages.mofile import write_mo
    js_ids = {(m.id if isinstance(m.id, str) else m.id[0]) for m in _read(POT)
              if m.id and JS_COMMENT in m.auto_comments}
    for lang in languages():
        os.makedirs(JS_CATALOGS, exist_ok=True)
        cat = _read(_po(lang), locale=lang)
        mo = os.path.join(LOCALE, lang, 'LC_MESSAGES', 'sajha.mo')
        with open(mo, 'wb') as fh:
            write_mo(fh, cat, use_fuzzy=False)
        print(f'{_rel(mo)}: compiled')
        js = js_catalog(cat, lang, js_ids)
        with open(os.path.join(JS_CATALOGS, lang + '.js'), 'w', encoding='utf-8') as fh:
            fh.write(js)
        print(f'{_rel(os.path.join(JS_CATALOGS, lang + ".js"))}: written')
    return 0


def js_messages_of(cat, js_ids) -> dict:
    """{msgid: translation, or [forms] for a plural} of the page-script messages translated."""
    out = {}
    for m in cat:
        if not m.id or m.fuzzy:
            continue
        key = m.id if isinstance(m.id, str) else m.id[0]
        if key not in js_ids:
            continue
        if isinstance(m.string, (list, tuple)):
            if all(m.string):
                out[key] = list(m.string)
        elif m.string:
            out[key] = m.string
    return out


def js_catalog(cat, lang: str, js_ids) -> str:
    """static/i18n/<lang>.js: window.SAJHA_I18N = {lang, plural, messages}."""
    plural = re.sub(r'[^n0-9 <>=!&|%?:()]', '', str(cat.plural_expr or '(n != 1)'))
    body = json.dumps(js_messages_of(cat, js_ids), ensure_ascii=False, sort_keys=True, indent=0)
    return (f'/* Generated by scripts/i18n.py compile from sajha/web/locale/{lang}/LC_MESSAGES/sajha.po:'
            ' do not edit. */\n'
            f'window.SAJHA_I18N = {{"lang": {json.dumps(lang)}, '
            f'"plural": function (n) {{ return Number({plural}); }},\n"messages": {body}}};\n')


def coverage(lang: str):
    """(translated, total, [untranslated msgids]) of a language against the .pot."""
    template = _read(POT)
    cat = _read(_po(lang), locale=lang)
    missing = []
    total = 0
    for msg in template:
        if not msg.id:
            continue
        total += 1
        got = cat.get(msg.id, context=msg.context)
        ok = got is not None and not got.fuzzy and (
            all(got.string) if isinstance(got.string, (list, tuple)) else bool(got.string))
        if not ok:
            missing.append(msg.id)
    return total - len(missing), total, missing


def cmd_check(a) -> int:
    bad = 0
    if not languages():
        print('no language catalogs: the console is English only')
    for lang in languages():
        done, total, missing = coverage(lang)
        print(f'{lang}: {done}/{total} translated')
        for m in missing[:20]:
            print(f'  missing: {m if isinstance(m, str) else m[0]}')
        bad += len(missing)
    return 1 if (a.strict and bad) else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('extract')
    p = sub.add_parser('init')
    p.add_argument('lang')
    sub.add_parser('update')
    sub.add_parser('compile')
    p = sub.add_parser('check')
    p.add_argument('--strict', action='store_true')
    a = ap.parse_args(argv)
    _babel()
    return {'extract': cmd_extract, 'init': cmd_init, 'update': cmd_update,
            'compile': cmd_compile, 'check': cmd_check}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
