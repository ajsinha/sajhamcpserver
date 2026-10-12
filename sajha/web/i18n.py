# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Console languages: gettext catalogs for the web console's templates and page help.

The console's own words (menus, buttons, headings, the "About this page" line) are wrapped in
the templates with ``{{ _('...') }}`` / ``{% trans %}`` (Jinja's ``jinja2.ext.i18n``) and looked
up here in ``sajha/web/locale/<lang>/LC_MESSAGES/sajha.mo``. The glossary, the guides, tool
names and descriptions, data and API responses stay English; a string with no translation
falls back to English.

SAJHA ships English only (no catalog under ``sajha/web/locale/`` but the template
``sajha.pot``), so every request resolves to English. The framework stays so a language can be
added later: with a compiled catalog in ``sajha/web/locale/<lang>/LC_MESSAGES/sajha.mo``, the
language of a request is the browser's ``Accept-Language``, then ``console.default_language``
(default ``en``). Only languages with a compiled catalog (plus English) can be chosen; there is
no language picker.

Page scripts (``sajha/web/static/js/`` and the inline scripts of the templates) translate with
``_t('...')`` (``static/js/i18n.js``) from ``window.SAJHA_I18N``, which
``sajha/web/static/i18n/<lang>.js`` sets: the page-script messages of the catalog, written by
``scripts/i18n.py compile``. ``base.html`` loads it as an ordinary same-origin script (no inline
script, so the Content-Security-Policy is unchanged). Help-catalog card titles and summaries
(``sajha/web/help_catalog.py``) are translated where the templates show them, with ``tr()``.

A compiled catalog is picked up without a restart: the ``.mo`` file's modification time is checked
at most once every few seconds (``RELOAD_SECONDS``), and a changed file is loaded again.

Extracting, updating and compiling the catalogs: ``python scripts/i18n.py extract|update|compile|check``
(needs Babel). The running server needs only the stdlib ``gettext`` and the committed ``.mo`` files.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

from __future__ import annotations

import gettext as _gettext
import os
import re
import time
from functools import lru_cache
from typing import Callable, List, Optional

LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'locale')
DOMAIN = 'sajha'
DEFAULT = 'en'
#: The page-script catalogs ``scripts/i18n.py compile`` writes (``<lang>.js``).
JS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'i18n')
#: How often (seconds) the compiled catalogs are checked for a change on disk.
RELOAD_SECONDS = 3.0

_TAG = re.compile(r'^[a-z]{2,3}(?:[_-][A-Za-z0-9]{2,8})?$')


def _norm(tag: str) -> str:
    return (tag or '').strip().replace('-', '_').lower()


def _mo(lang: str) -> str:
    return os.path.join(LOCALE_DIR, lang, 'LC_MESSAGES', DOMAIN + '.mo')


_stamp = {'at': 0.0, 'key': None}


def _disk_key() -> tuple:
    """(language, .mo mtime, folder) for every compiled catalog, re-read at most every
    RELOAD_SECONDS."""
    now = time.monotonic()
    if _stamp['key'] is None or now - _stamp['at'] >= RELOAD_SECONDS:
        key = []
        try:
            for name in sorted(os.listdir(LOCALE_DIR)):
                try:
                    key.append((_norm(name), os.stat(_mo(name)).st_mtime_ns, name))
                except OSError:
                    continue
        except OSError:
            pass
        _stamp['key'], _stamp['at'] = tuple(key), now
    return _stamp['key']


def available_languages() -> tuple:
    """English plus every language with a compiled catalog under ``sajha/web/locale/``."""
    return _available(_disk_key())


@lru_cache(maxsize=4)
def _available(key: tuple) -> tuple:
    found = [lang for lang, _mtime, folder in key if _TAG.match(folder) and lang != DEFAULT]
    return tuple([DEFAULT] + found)


def _match(tag: str) -> Optional[str]:
    """``tag`` (``fr-CA``, ``fr``) to an available language: exact, then its primary subtag."""
    tag = _norm(tag)
    if not tag:
        return None
    avail = available_languages()
    if tag in avail:
        return tag
    primary = tag.split('_')[0]
    return primary if primary in avail else None


def parse_accept_language(header: str) -> List[str]:
    """The tags of an ``Accept-Language`` header, best first (q=0 dropped)."""
    out = []
    for i, part in enumerate((header or '').split(',')):
        bits = part.strip().split(';')
        tag = bits[0].strip()
        if not tag or tag == '*':
            continue
        q = 1.0
        for b in bits[1:]:
            b = b.strip()
            if b.startswith('q='):
                try:
                    q = float(b[2:])
                except ValueError:
                    q = 0.0
        if q > 0:
            out.append((-q, i, tag))
    return [t for _, _, t in sorted(out)]


def default_language() -> str:
    """``console.default_language`` if it has a catalog, else English."""
    from sajha.core.config import _get
    return _match(str(_get('console.default_language', DEFAULT) or DEFAULT)) or DEFAULT


def select_language(request) -> str:
    """The console language for ``request``: ``Accept-Language``, then
    ``console.default_language``, among the compiled catalogs (English when there are none).
    Cached on ``request.state``."""
    if request is None:
        return default_language()
    state = getattr(request, 'state', None)
    cached = getattr(state, 'sajha_lang', None) if state is not None else None
    if cached:
        return cached
    lang = None
    try:
        for tag in parse_accept_language(request.headers.get('accept-language', '')):
            lang = _match(tag)
            if lang:
                break
    except Exception:
        lang = None
    lang = lang or default_language()
    if state is not None:
        try:
            state.sajha_lang = lang
        except Exception:
            pass
    return lang


def translations(lang: str) -> _gettext.NullTranslations:
    """The catalog for ``lang``; English (and anything missing) is the identity. A catalog
    recompiled on disk is loaded again (its mtime is part of the cache key)."""
    if not lang or lang == DEFAULT:
        return _NULL
    hit = next((k for k in _disk_key() if k[0] == lang), None)
    return _load(hit[2], hit[1]) if hit else _NULL


_NULL = _gettext.NullTranslations()


@lru_cache(maxsize=32)
def _load(folder: str, _mtime) -> _gettext.NullTranslations:
    try:
        with open(_mo(folder), 'rb') as fh:
            return _gettext.GNUTranslations(fh)
    except OSError:
        return _NULL


def gettext_for(request) -> Callable[[str], str]:
    return translations(select_language(request)).gettext


def reset_cache() -> None:
    """Forget the catalogs and the language list now, without waiting for RELOAD_SECONDS (tests)."""
    _stamp['key'] = None
    _available.cache_clear()
    _load.cache_clear()


def js_catalog_src(lang: str) -> Optional[str]:
    """The URL of ``lang``'s page-script catalog (``static/i18n/<lang>.js``, versioned by its
    mtime so a recompiled catalog is fetched again), or None for English or a missing file."""
    if not lang or lang == DEFAULT:
        return None
    try:
        mtime = int(os.stat(os.path.join(JS_DIR, lang + '.js')).st_mtime)
    except OSError:
        return None
    return f'/static/i18n/{lang}.js?v={mtime}'


def N_(message: str) -> str:
    """Marks a string for extraction without translating it (``scripts/i18n.py``)."""
    return message


#: Strings routes pass to templates (shown through ``tr()``), so the extractor finds them.
ROUTE_MESSAGES = (
    N_('Page Not Found'), N_('The requested page does not exist'),
    N_('Access Forbidden'), N_("You don't have permission to access this resource"),
    N_('Internal Server Error'), N_('An unexpected error occurred'),
    N_('Not Found'), N_('Prompt Not Found'), N_('Tool Not Found'),
    # sign-in and password (sajha/routes/auth_routes.py)
    N_('Invalid credentials'),
    N_('Too many failed sign-ins for this account. Try again later.'),
    N_('Too many failed sign-in attempts from your address. Wait a few minutes and retry.'),
    N_('Only a signed-in user can change a password (not an API key).'),
    N_('The current password is wrong.'), N_('The new passwords do not match.'),
    N_('The new password must differ from the current one.'),
    # system notice severities (sajha/notices), shown capitalised in the banner
    N_('Info'), N_('Warning'), N_('Error'), N_('Critical'),
    # help catalog: the group of cards no group names (sajha/web/help_catalog.py, grouped())
    N_('More'),
)


# ── Jinja ─────────────────────────────────────────────────────────────────────

def install(env) -> None:
    """Add ``jinja2.ext.i18n`` to ``env`` with request-aware gettext callables, the
    ``console_lang()``, ``tr()`` and ``js_catalog()`` globals."""
    from jinja2 import pass_context
    env.add_extension('jinja2.ext.i18n')
    env.policies['ext.i18n.trimmed'] = True

    def _lang(ctx) -> str:
        return select_language(ctx.get('request'))

    @pass_context
    def _gettext(ctx, message):
        return translations(_lang(ctx)).gettext(message)

    @pass_context
    def _ngettext(ctx, singular, plural, n):
        return translations(_lang(ctx)).ngettext(singular, plural, n)

    @pass_context
    def _pgettext(ctx, context, message):
        return translations(_lang(ctx)).pgettext(context, message)

    @pass_context
    def _npgettext(ctx, context, singular, plural, n):
        return translations(_lang(ctx)).npgettext(context, singular, plural, n)

    env.install_gettext_callables(_gettext, _ngettext, newstyle=True,
                                  pgettext=_pgettext, npgettext=_npgettext)

    @pass_context
    def console_lang(ctx) -> str:
        """The page's language as a BCP 47 tag, for ``<html lang>``."""
        return _lang(ctx).replace('_', '-')

    @pass_context
    def tr(ctx, message) -> str:
        """Translate a string that is not a literal (an error title a route passes): no
        ``%`` formatting and not marked safe, so the template escapes it as usual."""
        return translations(_lang(ctx)).gettext(str(message)) if message else ''

    @pass_context
    def js_catalog(ctx) -> Optional[str]:
        """The page-script catalog's URL for this page's language (None for English)."""
        return js_catalog_src(_lang(ctx))

    env.globals['console_lang'] = console_lang
    env.globals['tr'] = tr
    env.globals['js_catalog'] = js_catalog
