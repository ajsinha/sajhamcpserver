"""
SAJHA MCP Server — the audit command line.

    python -m sajha.audit verify [--chain ID] [--public-key FILE] [--db-url URL] [--json]
    python -m sajha.audit chains [--db-url URL]
    python -m sajha.audit show [--limit N] [--event GLOB] [--format json|cef|ocsf] [--db-url URL]

``verify`` exits 0 when every chain is intact, 1 when a chain is broken or was tampered
with, 2 when it cannot check (no database). The database is SAJHA's (``db.*`` settings)
unless ``--db-url`` names another. Design: docs/architecture/Policy and Audit.md, section 7.4.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional


def _engine(url: Optional[str]):
    from sajha.core.config import get_settings
    from sajha.db.engine import create_db_engine
    return create_db_engine(get_settings(), url) if url else create_db_engine(get_settings())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m sajha.audit', description='Verify and read the SAJHA audit chain.')
    sub = p.add_subparsers(dest='cmd', required=True)
    v = sub.add_parser('verify', help='check every chain for tampering')
    v.add_argument('--chain', help='verify one chain id only')
    v.add_argument('--public-key', help='a PEM or JWKS file with keys that signed older anchors')
    v.add_argument('--db-url', help='SQLAlchemy URL of the database (default: SAJHA\'s)')
    v.add_argument('--json', action='store_true', help='print the full report as JSON')
    c = sub.add_parser('chains', help='list the chains')
    c.add_argument('--db-url')
    s = sub.add_parser('show', help='print recent records, merged across chains')
    s.add_argument('--limit', type=int, default=20)
    s.add_argument('--event', help='event name or glob (policy.*)')
    s.add_argument('--format', choices=('json', 'cef', 'ocsf'), default='json')
    s.add_argument('--db-url')
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        engine = _engine(args.db_url)
    except Exception as e:
        print(f'cannot open the database: {e}', file=sys.stderr)
        return 2
    if args.cmd == 'verify':
        from sajha.audit.verify import verify
        try:
            report = verify(engine, chain_id=args.chain, public_key_file=args.public_key)
        except Exception as e:
            print(f'cannot verify: {e}', file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            if not report['chains']:
                print(report.get('note') or 'no audit chains')
            for c in report['chains']:
                state = 'OK      ' if c['ok'] else 'BROKEN  '
                print(f"{state}{c['chain_id']}  records={c['records']} anchors={c['anchors']} "
                      f"last_anchored_seq={c['last_anchored_seq']} {'closed' if c['closed'] else 'open'}")
                for pr in c['problems']:
                    print(f'    problem: {pr}')
                for w in c['warnings']:
                    print(f'    warning: {w}')
            print(f"{'INTACT' if report['ok'] else 'TAMPERED OR BROKEN'}: {len(report['chains'])} chain(s), "
                  f"{report.get('records', 0)} record(s)")
        return 0 if report['ok'] else 1
    if args.cmd == 'chains':
        from sajha.audit.verify import verify
        report = verify(engine, keys={})
        for c in report['chains']:
            print(f"{c['chain_id']}  records={c['records']} last={c['last_ts']} "
                  f"{'closed' if c['closed'] else 'open'}")
        return 0
    if args.cmd == 'show':
        from sajha.audit.chain import recent
        from sajha.audit.formats import render
        for rec in reversed(recent(engine, limit=args.limit, event=args.event)):
            print(render(rec, args.format))
        return 0
    return 2


if __name__ == '__main__':
    sys.exit(main())
