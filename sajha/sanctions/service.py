"""
SAJHA MCP Server — what the sanctions tools do: screen a name, show an entry, list changes and
report each list's status, all from the local index (nothing leaves the machine).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Guide: docs/tools/public-data/Sanctions Tool Reference Guide.md.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sajha.sanctions import match, parse, sources, store

MAX_MATCHES = 50
MAX_CHANGES = 1000
TYPES = ('individual', 'entity', 'vessel', 'aircraft')


def _age_hours(stamp: Optional[str]) -> Optional[float]:
    if not stamp:
        return None
    try:
        t = datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return round((datetime.now(timezone.utc) - t).total_seconds() / 3600.0, 1)


def _lists(names: Optional[List[str]]) -> List[str]:
    if not names:
        return list(sources.ENABLED)
    out = []
    for n in names:
        k = sources.check_list(n)
        if k not in out:
            out.append(k)
    return out


def _dob_compatible(query: str, listed: str) -> bool:
    """Two dates (YYYY, YYYY-MM or YYYY-MM-DD) agree at the precision both have."""
    q, l = query.split('-'), listed.split('-')
    n = min(len(q), len(l))
    return q[:n] == l[:n]


def _index_info(list_id: str, status: Dict[str, Any]) -> Dict[str, Any]:
    st = status.get(list_id) or {}
    return {'list': list_id, 'publication_date': st.get('publication_date'), 'last_refresh': st.get('last_refresh'),
            'age_hours': _age_hours(st.get('last_refresh')), 'entry_count': st.get('entry_count')}


def screen(name: str, type: Optional[str] = None, date_of_birth: Optional[str] = None,
           country: Optional[str] = None, lists: Optional[List[str]] = None, threshold: float = 85) -> Dict[str, Any]:
    if not str(name or '').strip():
        raise ValueError('name is required')
    if type and type not in TYPES:
        raise ValueError(f'type must be one of {", ".join(TYPES)}')
    dob = None
    if date_of_birth:
        dob = parse.norm_date(date_of_birth)
        if not dob or not re.fullmatch(r'\d{4}(-\d{2}(-\d{2})?)?', str(date_of_birth).strip()):
            raise ValueError('date_of_birth must be YYYY-MM-DD, YYYY-MM or YYYY')
    cc = None
    if country:
        cc = parse.country_code(country)
        if not cc:
            raise ValueError(f'unknown country {country!r}: use an ISO 3166 code (GB, IRN) or a country name')
    wanted = _lists(lists)
    threshold = float(threshold)
    q_person = match.tokens(name)
    q_org = match.tokens(name, organisation=True)
    status = store.read_status()
    searched, missing, hits = [], [], []
    for list_id in wanted:
        idx = store.CACHE.get(list_id)
        if idx is None:
            missing.append(list_id)
            continue
        searched.append(_index_info(list_id, status))
        best: Dict[str, Dict[str, Any]] = {}
        entries = idx.entries
        for i in set(idx.candidates(q_person)) | set(idx.candidates(q_org)):
            rec = idx.names[i]
            e = entries.get(rec.entry_id)
            if e is None or (type and e.get('type') != type):
                continue
            q = q_person if e.get('type') == 'individual' else q_org
            sc, sound = match.score(q, rec.words)
            if sc < threshold:
                continue
            cur = best.get(rec.entry_id)
            if cur is None or sc > cur['score'] or (sc == cur['score'] and rec.primary):
                best[rec.entry_id] = {'score': sc, 'phonetic_match': sound, 'matched_alias': rec.name,
                                      'matched_primary_name': rec.primary}
        for eid, b in best.items():
            e = entries[eid]
            dob_match = None
            if dob and e.get('dates_of_birth'):
                dob_match = any(_dob_compatible(dob, d) for d in e['dates_of_birth'])
                if not dob_match:
                    continue
            country_match = (cc in e['countries']) if (cc and e.get('countries')) else None
            hits.append({'list': list_id, 'entry_id': eid, 'name': e.get('name'), **b, 'type': e.get('type'),
                         'programmes': e.get('programmes') or [], 'dates_of_birth': e.get('dates_of_birth') or [],
                         'countries': e.get('countries') or [], 'reference': e.get('reference'),
                         'dob_match': dob_match, 'country_match': country_match})
    if not searched:
        raise ValueError('the sanctions index is empty for ' + ', '.join(wanted) +
                         ': an administrator runs the refresh (python -m sajha.sanctions refresh, the sanctions_refresh '
                         'workflow or the sanctions_refresh tool)')
    hits.sort(key=lambda h: (-h['score'], h['country_match'] is not True, h['list'], h['entry_id']))
    return {'query': {'name': name, 'normalised': ' '.join(q_person), 'type': type, 'date_of_birth': dob,
                      'country': cc, 'threshold': threshold},
            'matches': hits[:MAX_MATCHES], 'match_count': len(hits), 'truncated': len(hits) > MAX_MATCHES,
            'lists_searched': searched, 'lists_missing': missing,
            'notice': sources.NOT_A_DETERMINATION,
            'source': [sources.LISTS[s['list']].source for s in searched]}


def entry(list: str, entry_id: str) -> Dict[str, Any]:
    list_id = sources.check_list(list)
    idx = store.CACHE.get(list_id)
    if idx is None:
        raise ValueError(f'list {list_id} has not been downloaded yet: an administrator runs the refresh')
    e = idx.entries.get(str(entry_id).strip())
    if e is None:
        raise ValueError(f'no entry {entry_id!r} in {list_id} (published {idx.doc.get("publication_date")})')
    return {'entry': e, 'index': _index_info(list_id, store.read_status()),
            'notice': sources.NOT_A_DETERMINATION, 'source': sources.LISTS[list_id].source}


def changes(since: str, list: Optional[str] = None) -> Dict[str, Any]:
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(since or '').strip()):
        raise ValueError('since must be a date YYYY-MM-DD')
    list_id = sources.check_list(list) if list else None
    refreshes, out = [], {'added': [], 'changed': [], 'removed': []}
    for r in store.read_changes():
        if (list_id and r.get('list') != list_id) or str(r.get('refreshed_at') or '')[:10] < since:
            continue
        refreshes.append({'list': r.get('list'), 'refreshed_at': r.get('refreshed_at'),
                          'publication_date': r.get('publication_date'),
                          'previous_publication_date': r.get('previous_publication_date'),
                          'initial': bool(r.get('initial')),
                          **{f'{k}_count': len(r.get(k) or []) for k in out}})
        for k in out:
            for item in r.get(k) or []:
                out[k].append({'list': r.get('list'), 'refreshed_at': r.get('refreshed_at'), **item})
    truncated = any(len(v) > MAX_CHANGES for v in out.values())
    lists_named = sorted({r['list'] for r in refreshes if r.get('list') in sources.LISTS})
    return {'since': since, 'list': list_id, 'refreshes': refreshes,
            **{k: v[-MAX_CHANGES:] for k, v in out.items()}, 'truncated': truncated,
            'notice': sources.NOT_A_DETERMINATION, 'source': [sources.LISTS[x].source for x in lists_named]}


def lists_status() -> Dict[str, Any]:
    status = store.read_status()
    rows = []
    for list_id, src in sources.LISTS.items():
        st = status.get(list_id) or {}
        row = {'list': list_id, 'title': src.title, 'enabled': src.enabled,
               'loaded': src.enabled and st.get('entry_count') is not None,
               'publication_date': st.get('publication_date'), 'last_refresh': st.get('last_refresh'),
               'age_hours': _age_hours(st.get('last_refresh')), 'last_attempt': st.get('last_attempt'),
               'last_error': st.get('last_error'), 'entry_count': st.get('entry_count'),
               'name_count': st.get('name_count'), 'source': src.source}
        if not src.enabled:
            row['disabled_reason'] = src.disabled_reason
        rows.append(row)
    return {'lists': rows, 'notice': sources.NOT_A_DETERMINATION}
