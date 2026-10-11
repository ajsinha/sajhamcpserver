"""
SAJHA MCP Server — the local sanctions index: files under ``sanctions.data_dir`` (default
``data/sanctions``, git-ignored), and the in-memory name index screening uses.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Files (each written to a temporary name and renamed, so a reader never sees half a file):

* ``<list>.json.gz``: ``{list, publication_date, refreshed_at, source_url, entries: {id: entry}}``
* ``status.json``: per list ``{publication_date, last_refresh, last_attempt, last_error,
  entry_count, name_count, bytes, source_published}``
* ``changes.jsonl``: one line per refresh that changed a list: ``{list, refreshed_at,
  publication_date, previous_publication_date, initial, added, changed, removed}``, each a list of
  ``{entry_id, name}``

No database tables. Each process loads a list when first screened and reloads it when its file
changes, so a refresh by the CLI, a workflow or another worker is picked up on the next call.
"""

from __future__ import annotations

import gzip
import json
import os
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sajha.sanctions import match

DEFAULT_DIR = 'data/sanctions'


def data_dir() -> str:
    try:
        from sajha.core.config import _get
        d = _get('sanctions.data_dir', DEFAULT_DIR) or DEFAULT_DIR
    except Exception:
        d = DEFAULT_DIR
    return d


def _path(name: str, base: Optional[str] = None) -> str:
    return os.path.join(base or data_dir(), name)


def _write_atomic(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = f'{path}.tmp-{os.getpid()}-{threading.get_ident()}'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


def write_list(list_id: str, doc: Dict[str, Any], base: Optional[str] = None) -> None:
    raw = json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    _write_atomic(_path(f'{list_id}.json.gz', base), gzip.compress(raw, compresslevel=6))


def read_list(list_id: str, base: Optional[str] = None) -> Optional[Dict[str, Any]]:
    p = _path(f'{list_id}.json.gz', base)
    if not os.path.exists(p):
        return None
    with gzip.open(p, 'rb') as f:
        return json.loads(f.read().decode('utf-8'))


def read_status(base: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    p = _path('status.json', base)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_status(status: Dict[str, Dict[str, Any]], base: Optional[str] = None) -> None:
    _write_atomic(_path('status.json', base), json.dumps(status, indent=1, sort_keys=True).encode('utf-8'))


def append_change(record: Dict[str, Any], base: Optional[str] = None) -> None:
    p = _path('changes.jsonl', base)
    os.makedirs(os.path.dirname(p) or '.', exist_ok=True)
    with open(p, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n')


def read_changes(base: Optional[str] = None) -> List[Dict[str, Any]]:
    p = _path('changes.jsonl', base)
    if not os.path.exists(p):
        return []
    out = []
    with open(p, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    return out


# ── the in-memory name index ────────────────────────────────────────────

#: a word found in more names than this is not used to find candidates when the query has a rarer one
COMMON_WORD = 1500


@dataclass
class NameRecord:
    entry_id: str
    name: str
    primary: bool
    words: List[str]


@dataclass
class ListIndex:
    list_id: str
    mtime: float
    doc: Dict[str, Any]
    names: List[NameRecord] = field(default_factory=list)
    by_word: Dict[str, List[int]] = field(default_factory=lambda: defaultdict(list))
    by_sound: Dict[str, List[int]] = field(default_factory=lambda: defaultdict(list))

    @property
    def entries(self) -> Dict[str, Dict[str, Any]]:
        return self.doc.get('entries') or {}

    def build(self) -> 'ListIndex':
        for eid, e in self.entries.items():
            org = e.get('type') != 'individual'
            for i, nm in enumerate([e.get('name') or ''] + [a.get('name') or '' for a in e.get('aliases') or []]):
                words = match.tokens(nm, organisation=org)
                if not words or not any(w.isascii() for w in words):
                    continue                    # names in scripts with no transliteration here
                idx = len(self.names)
                self.names.append(NameRecord(eid, nm, i == 0, words))
                for w in set(words):
                    self.by_word[w].append(idx)
                for k in match.phonetic_keys(words):
                    self.by_sound[k].append(idx)
        return self

    def candidates(self, words: List[str]) -> List[int]:
        long_words = [w for w in set(words) if len(w) > 2] or list(set(words))
        posting = [self.by_word.get(w, []) for w in long_words] + \
                  [self.by_sound.get(k, []) for k in match.phonetic_keys(long_words)]
        posting = [p for p in posting if p]
        rare = [p for p in posting if len(p) <= COMMON_WORD]
        use = rare or posting
        out = set()
        for p in use:
            out.update(p)
        return sorted(out)


class _Cache:
    def __init__(self):
        self._lock = threading.Lock()
        self._lists: Dict[Tuple[str, str], ListIndex] = {}

    def get(self, list_id: str) -> Optional[ListIndex]:
        base = data_dir()
        p = _path(f'{list_id}.json.gz', base)
        try:
            mtime = os.path.getmtime(p)
        except OSError:
            return None
        key = (base, list_id)
        cur = self._lists.get(key)
        if cur is not None and cur.mtime == mtime:
            return cur
        with self._lock:
            cur = self._lists.get(key)
            if cur is not None and cur.mtime == mtime:
                return cur
            doc = read_list(list_id, base)
            if doc is None:
                return None
            idx = ListIndex(list_id, mtime, doc).build()
            self._lists[key] = idx
            return idx

    def clear(self) -> None:
        with self._lock:
            self._lists.clear()


CACHE = _Cache()
