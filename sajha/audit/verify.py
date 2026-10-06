"""
SAJHA MCP Server — verify the audit hash chains.

For every chain in ``audit_chain`` (or one): each record's hash recomputes from its
canonical JSON, each ``prev`` is the previous record's hash, ``seq`` runs from 0 without a
gap and record 0 is ``chain.open``, the query columns agree with the canonical record, and
every anchor (``audit_anchors`` and the chain's own ``audit.anchor`` records) carries a valid
RS256 signature over a head hash that matches the record at its ``seq``.
Design: docs/architecture/Policy and Audit.md, section 7.4.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sajha.audit.chain import GENESIS, audit_anchors, audit_chain, canonical, digest, parse_ts, row_for, \
    verify_signature


def public_keys(extra_file: Optional[str] = None) -> Dict[str, Any]:
    """``{kid: public key}``: the server's current key, plus a PEM or JWKS file."""
    keys: Dict[str, Any] = {}
    try:
        from sajha.auth.oauth.keys import get_signing_key
        from cryptography.hazmat.primitives import serialization
        sk = get_signing_key()
        keys[sk.kid] = serialization.load_pem_public_key(sk.public_pem)
    except Exception:
        pass
    if extra_file:
        keys.update(load_key_file(extra_file))
    return keys


def load_key_file(path: str) -> Dict[str, Any]:
    import base64
    from pathlib import Path
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    data = Path(path).read_bytes()
    text = data.decode('utf-8', 'replace').strip()
    if text.startswith('{'):
        out = {}
        for k in json.loads(text).get('keys', []):
            if k.get('kty') != 'RSA':
                continue
            def b(v):
                return int.from_bytes(base64.urlsafe_b64decode(v + '=' * (-len(v) % 4)), 'big')
            out[k.get('kid', '')] = rsa.RSAPublicNumbers(b(k['e']), b(k['n'])).public_key()
        return out
    try:
        key = serialization.load_pem_public_key(data)
    except ValueError:
        key = serialization.load_pem_private_key(data, password=None).public_key()
    return {'*': key}


def _anchor_from_record(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    d = rec.get('details') or {}
    if not isinstance(d, dict) or 'payload' not in d:
        return None
    return {'seq': d.get('anchored_seq'), 'hash': d.get('anchored_hash'), 'payload_json': d.get('payload'),
            'signature': d.get('signature'), 'kid': d.get('kid'), 'where': f'record {rec.get("seq")}'}


def verify_rows(chain_id: str, rows: List[Dict[str, Any]], anchors: List[Dict[str, Any]],
                keys: Dict[str, Any]) -> Dict[str, Any]:
    """Verify one chain from its rows (ordered by seq) and anchor rows."""
    problems: List[str] = []
    warnings: List[str] = []
    by_seq: Dict[int, str] = {}
    prev = GENESIS
    expected = 0
    closed = False
    last_ts = None
    chain_anchors = []
    for row in rows:
        seq = int(row['seq'])
        text = row['record_json']
        if seq != expected:
            problems.append(f'seq {expected}..{seq - 1} missing (deleted or never written)' if seq > expected
                            else f'seq {seq} duplicated or out of order')
        try:
            rec = json.loads(text)
        except ValueError:
            problems.append(f'seq {seq}: record_json is not JSON')
            expected, prev = seq + 1, row['hash']
            continue
        if digest(text) != row['hash']:
            problems.append(f'seq {seq}: hash does not match the record (record edited)')
        if canonical(rec) != text:
            problems.append(f'seq {seq}: record_json is not in canonical form')
        if rec.get('prev') != prev or row['prev_hash'] != rec.get('prev'):
            problems.append(f'seq {seq}: does not link to the previous record (prev hash mismatch)')
        if rec.get('seq') != seq or rec.get('chain') != chain_id:
            problems.append(f'seq {seq}: chain/seq columns disagree with the record')
        if seq == 0 and rec.get('event') != 'chain.open':
            problems.append('seq 0 is not chain.open')
        try:
            want = row_for(rec, row['hash'])
            for col in ('event', 'actor', 'resource', 'outcome'):
                if (want[col] or None) != (row.get(col) or None):
                    problems.append(f'seq {seq}: column {col} was changed ({row.get(col)!r} vs record {want[col]!r})')
            ts = row.get('ts')
            if ts is not None and abs((_aware(ts) - want['ts']).total_seconds()) > 0.001:
                problems.append(f'seq {seq}: column ts was changed')
        except Exception as e:
            problems.append(f'seq {seq}: malformed record ({e})')
        if rec.get('event') == 'chain.close':
            closed = True
        if rec.get('event') == 'audit.anchor':
            a = _anchor_from_record(rec)
            if a:
                chain_anchors.append(a)
        by_seq[seq] = row['hash']
        last_ts = rec.get('ts')
        prev = row['hash']
        expected = seq + 1
        if len(problems) > 50:
            problems.append('... (stopped after 50 problems)')
            break
    last_seq = expected - 1
    anchored = -1
    seen = set()
    all_anchors = [dict(a, where='audit_anchors') for a in anchors] + chain_anchors
    good_anchors = 0
    for a in all_anchors:
        key = (a.get('seq'), a.get('hash'), a.get('signature'))
        dup = key in seen
        seen.add(key)
        try:
            payload = json.loads(a['payload_json'])
        except (ValueError, TypeError):
            problems.append(f'anchor ({a["where"]}): payload is not JSON')
            continue
        if payload.get('seq') != a.get('seq') or payload.get('hash') != a.get('hash') \
                or payload.get('chain') != chain_id:
            problems.append(f'anchor at seq {a.get("seq")} ({a["where"]}): fields disagree with the signed payload')
            continue
        pk = keys.get(a.get('kid') or '') or keys.get('*')
        if pk is None:
            if not dup:
                warnings.append(f'anchor at seq {a.get("seq")}: signed by key {a.get("kid")!r}, which this '
                                'verifier does not have (rotated? pass --public-key)')
        elif not verify_signature(pk, a['payload_json'].encode('utf-8'), a.get('signature') or ''):
            problems.append(f'anchor at seq {a.get("seq")} ({a["where"]}): signature is not valid')
            continue
        else:
            good_anchors += 0 if dup else 1
        s = a.get('seq')
        if s is None:
            continue
        if s > last_seq:
            problems.append(f'anchor at seq {s} ({a["where"]}): the chain ends at {last_seq} (records truncated)')
        elif by_seq.get(s) != a.get('hash'):
            problems.append(f'anchor at seq {s} ({a["where"]}): the record there has a different hash '
                            '(chain rewritten)')
        anchored = max(anchored, s)
    unanchored = 0
    for row in rows:
        if int(row['seq']) > anchored and row.get('event') != 'audit.anchor':
            unanchored += 1
    if unanchored:
        warnings.append(f'{unanchored} record(s) after the last anchor are not yet anchored')
    if not closed:
        warnings.append('no chain.close: the process is running, or stopped without a clean shutdown')
    return {'chain_id': chain_id, 'ok': not problems, 'records': len(rows), 'last_seq': last_seq,
            'last_ts': last_ts, 'anchors': good_anchors, 'last_anchored_seq': anchored, 'unanchored': unanchored,
            'closed': closed, 'problems': problems, 'warnings': warnings}


def _aware(ts):
    from datetime import timezone
    if isinstance(ts, str):
        from datetime import datetime
        ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def chain_ids(engine) -> List[str]:
    from sqlalchemy import select
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(select(audit_chain.c.chain_id).distinct()).fetchall()]


def verify(engine, chain_id: Optional[str] = None, public_key_file: Optional[str] = None,
           keys: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Verify every chain (or one). ``ok`` is True when no chain has a problem."""
    from sqlalchemy import inspect, select
    if not inspect(engine).has_table('audit_chain'):
        return {'ok': True, 'chains': [], 'note': 'no audit_chain table: nothing recorded yet'}
    keys = keys if keys is not None else public_keys(public_key_file)
    ids = [chain_id] if chain_id else chain_ids(engine)
    out = []
    with engine.connect() as conn:
        for cid in ids:
            rows = [dict(r._mapping) for r in conn.execute(
                select(audit_chain).where(audit_chain.c.chain_id == cid).order_by(audit_chain.c.seq))]
            anchors = [dict(r._mapping) for r in conn.execute(
                select(audit_anchors).where(audit_anchors.c.chain_id == cid).order_by(audit_anchors.c.seq))]
            out.append(verify_rows(cid, rows, anchors, keys))
    out.sort(key=lambda c: c.get('last_ts') or '', reverse=True)
    return {'ok': all(c['ok'] for c in out), 'chains': out,
            'records': sum(c['records'] for c in out), 'keys': sorted(k for k in keys if k != '*')}
