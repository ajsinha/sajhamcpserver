"""
SAJHA MCP Server — the sanctions refresh job: download the official lists, parse them into the
local index, and record what changed.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Every download goes through the outbound fetch guard and HTTP proxy (``sajha/core/outbound.py``).
The EU list is downloaded only when its RSS feed shows a new publication. For each list the job
compares the new entries with the stored ones (by entry id, and a hash of the entry for changes),
appends the added, changed and removed entries to ``changes.jsonl`` and updates ``status.json``.
A list that fails to download or parse keeps its previous index; the error is recorded in its
status. One refresh at a time per data directory (a lock file); a second one is refused.

Run by the shipped workflow ``sanctions_refresh`` (config/workflows/sanctions_refresh.yaml) through
the ``sanctions_refresh`` tool, or by hand: ``python -m sajha.sanctions refresh``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from sajha.sanctions import parse, sources, store

logger = logging.getLogger(__name__)

MAX_BYTES = 256 * 1024 * 1024
TIMEOUT = 180.0
USER_AGENT = 'SAJHA-MCP-Server sanctions refresh'

#: list id -> parser
PARSERS: Dict[str, Callable[..., Any]] = {
    'ofac_sdn': parse.parse_ofac,
    'ofac_consolidated': parse.parse_ofac,
    'eu': parse.parse_eu,
    'uk': parse.parse_uk,
}


class RefreshBusy(RuntimeError):
    """Another refresh holds the lock."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _fetch(url: str) -> bytes:
    from sajha.core import outbound
    r = outbound.request('GET', url, headers={'User-Agent': USER_AGENT}, timeout=TIMEOUT, max_bytes=MAX_BYTES)
    r.raise_for_status()
    return r.content


def eu_feed(fetch: Callable[[str], bytes]) -> Tuple[str, Optional[str]]:
    """(XML v1.1 URL, publication time) from the EU RSS feed; the known URL when the feed has none."""
    from defusedxml import ElementTree as DET
    root = DET.fromstring(fetch(sources.EU_RSS))
    for item in root.iter('item'):
        enc = item.find('enclosure')
        url = enc.get('url') if enc is not None else (item.findtext('link') or '')
        if 'xmlFullSanctionsList_1_1' in (url or ''):
            pub = item.findtext('pubDate') or ''
            try:
                pub = parsedate_to_datetime(pub).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            except (TypeError, ValueError):
                pub = pub or None
            return url, pub
    return sources.EU_XML, None


def _hash(entry: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()[:16]


def diff(old: Dict[str, Dict[str, Any]], new: Dict[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, str]]]:
    """Entries added, changed and removed between two versions of a list ({entry_id, name} each)."""
    def brief(e):
        return {'entry_id': e['entry_id'], 'name': e.get('name') or ''}
    added = [brief(new[k]) for k in sorted(new.keys() - old.keys())]
    removed = [brief(old[k]) for k in sorted(old.keys() - new.keys())]
    changed = [brief(new[k]) for k in sorted(new.keys() & old.keys()) if _hash(new[k]) != _hash(old[k])]
    return {'added': added, 'changed': changed, 'removed': removed}


@contextlib.contextmanager
def _lock(base: str) -> Iterator[None]:
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, '.refresh.lock')
    f = open(path, 'a+')
    try:
        try:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:                     # not POSIX: no cross-process lock
            pass
        except OSError:
            raise RefreshBusy('a sanctions refresh is already running')
        yield
    finally:
        f.close()


def _names(entries: Dict[str, Dict[str, Any]]) -> int:
    return sum(1 + len(e.get('aliases') or []) for e in entries.values())


def refresh_list(list_id: str, *, force: bool = False, fetch: Optional[Callable[[str], bytes]] = None,
                 base: Optional[str] = None) -> Dict[str, Any]:
    """Refresh one list (the caller holds the lock). Returns its outcome; never raises for a
    download or parse failure (the outcome says ``error``)."""
    list_id = sources.check_list(list_id)
    src = sources.LISTS[list_id]
    fetch = fetch or _fetch
    base = base or store.data_dir()
    status = store.read_status(base)
    st = dict(status.get(list_id) or {})
    t0 = time.time()
    st['last_attempt'] = _now()
    out: Dict[str, Any] = {'list': list_id, 'status': 'error'}
    try:
        url, source_published = src.url, None
        if list_id == 'eu':
            url, source_published = eu_feed(fetch)
            if (not force and source_published and source_published == st.get('source_published')
                    and store.read_list(list_id, base) is not None):
                st['last_refresh'], st['last_error'] = _now(), None
                status[list_id] = st
                store.write_status(status, base)
                return {'list': list_id, 'status': 'unchanged', 'publication_date': st.get('publication_date'),
                        'entries': st.get('entry_count'), 'seconds': round(time.time() - t0, 1)}
        content = fetch(url)
        published, entries = PARSERS[list_id](content, list_id)
        if not entries:
            raise ValueError('the downloaded file has no entries')
        old_doc = store.read_list(list_id, base)
        old = (old_doc or {}).get('entries') or {}
        d = diff(old, entries)
        now = _now()
        store.write_list(list_id, {'list': list_id, 'publication_date': published, 'refreshed_at': now,
                                   'source_url': re.sub(r'token=[^&]+', 'token=…', url), 'entries': entries}, base)
        if old_doc is None or any(d.values()):
            store.append_change({'list': list_id, 'refreshed_at': now, 'publication_date': published,
                                 'previous_publication_date': (old_doc or {}).get('publication_date'),
                                 'initial': old_doc is None,
                                 **({'added': [], 'changed': [], 'removed': []} if old_doc is None else d)}, base)
        st.update({'publication_date': published, 'last_refresh': now, 'last_error': None,
                   'entry_count': len(entries), 'name_count': _names(entries), 'bytes': len(content),
                   'source_published': source_published})
        out = {'list': list_id, 'status': 'initial' if old_doc is None else 'updated', 'publication_date': published,
               'entries': len(entries), 'names': st['name_count'], 'bytes': len(content),
               'added': len(d['added']) if old_doc else 0, 'changed': len(d['changed']) if old_doc else 0,
               'removed': len(d['removed']) if old_doc else 0}
    except Exception as e:
        logger.warning(f'sanctions refresh of {list_id} failed: {e}')
        st['last_error'] = f'{e.__class__.__name__}: {e}'[:500]
        out['error'] = st['last_error']
    status = store.read_status(base)
    status[list_id] = st
    store.write_status(status, base)
    out['seconds'] = round(time.time() - t0, 1)
    return out


def refresh(lists: Optional[Iterable[str]] = None, *, force: bool = False,
            fetch: Optional[Callable[[str], bytes]] = None, base: Optional[str] = None) -> Dict[str, Any]:
    """Refresh the named lists (default: every enabled list). Raises RefreshBusy when another
    refresh is running, ValueError for an unknown or disabled list."""
    wanted = [sources.check_list(x) for x in (lists or sources.ENABLED)]
    base = base or store.data_dir()
    started = _now()
    with _lock(base):
        results = [refresh_list(x, force=force, fetch=fetch, base=base) for x in wanted]
    store.CACHE.clear()
    return {'started_at': started, 'finished_at': _now(), 'data_dir': base, 'lists': results,
            'ok': all(r['status'] != 'error' for r in results)}
