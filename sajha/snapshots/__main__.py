"""
SAJHA MCP Server — the snapshot command line.

    python -m sajha.snapshots list    [--dir DIR]
    python -m sajha.snapshots verify  [--dir DIR] [--public-key FILE] [--json]
    python -m sajha.snapshots diff    A B [--dir DIR] [--json]       (names, paths, latest, previous)
    python -m sajha.snapshots show    NAME [--dir DIR]
    python -m sajha.snapshots restore NAME [--dir DIR] [--db-url URL] [--no-keys] [--dry-run] [--yes]
                                      [--allow-unverified]

``verify`` exits 0 when every snapshot's hash, signature and chain link hold, 1 when one does
not, 2 when it cannot check. ``restore`` re-creates the roles, users and persistent API key
records a snapshot holds and the database lacks (nothing existing is changed); it verifies the
snapshot first and asks for the snapshot's name as confirmation unless ``--yes`` is given.
The directory is ``snapshots.dir`` unless ``--dir`` names another.
Guide: docs/architecture/Policy and Audit.md (Snapshots).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

EXIT_OK, EXIT_PROBLEM, EXIT_CANNOT = 0, 1, 2


def _store(args):
    from sajha.snapshots import SnapshotSettings
    from sajha.snapshots.core import SnapshotStore
    s = SnapshotSettings.from_config()
    return SnapshotStore(args.dir or s.dir, s.keep, s.compress)


def cmd_list(args) -> int:
    from sajha.snapshots.core import iter_sections
    store = _store(args)
    names = store.names()
    if not names:
        print(f'no snapshots in {store.dir}')
        return EXIT_OK
    for n in names:
        try:
            env = store.load(n)
            b = env['snapshot']
            counts = ', '.join(f'{k} {v}' for k, v in iter_sections(b))
            print(f'{n}  seq {b["seq"]}  {b["created"]}  {counts}  sha256 {env["sha256"][:16]}')
        except Exception as e:
            print(f'{n}  unreadable: {e}')
    return EXIT_OK


def cmd_verify(args) -> int:
    from sajha.snapshots.core import load_public_keys
    store = _store(args)
    try:
        keys = load_public_keys(args.public_key)
    except Exception as e:
        print(f'cannot load keys: {e}', file=sys.stderr)
        return EXIT_CANNOT
    report = store.verify(keys)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for s in report['snapshots']:
            print(f'{"ok  " if s["ok"] else "FAIL"} {s["name"]}' + ''.join(f'\n     {p}' for p in s['problems']))
        for n in report['notes']:
            print(f'note: {n}')
        print(f'{report["count"]} snapshot(s) in {report["dir"]}: '
              + ('chain intact' if report['ok'] else f'{len(report["problems"])} problem(s)'))
    return EXIT_OK if report['ok'] else EXIT_PROBLEM


def cmd_diff(args) -> int:
    from sajha.snapshots.core import diff, diff_lines
    store = _store(args)
    a, b = store.resolve(args.a), store.resolve(args.b)
    d = diff(store.load(a), store.load(b))
    if args.json:
        print(json.dumps(d, indent=2, default=str))
    else:
        lines = diff_lines(d)
        print(f'{a} -> {b}')
        print('\n'.join(lines) if lines else 'no differences')
    return EXIT_OK


def cmd_show(args) -> int:
    store = _store(args)
    print(json.dumps(store.load(store.resolve(args.name)), indent=2, sort_keys=True))
    return EXIT_OK


def _session(url: Optional[str]):
    from sqlalchemy.orm import sessionmaker
    from sajha.core.config import get_settings
    from sajha.db.engine import create_db_engine
    engine = create_db_engine(get_settings(), url) if url else create_db_engine(get_settings())
    return sessionmaker(bind=engine)()


def cmd_restore(args) -> int:
    from sajha.snapshots import _audit
    from sajha.snapshots.core import load_public_keys, restore
    store = _store(args)
    name = store.resolve(args.name)
    report = store.verify(load_public_keys(args.public_key))
    entry = next(s for s in report['snapshots'] if s['name'] == name)
    if not entry['ok'] and not args.allow_unverified:
        print(f'{name} does not verify: ' + '; '.join(entry['problems']) +
              '\n(--allow-unverified restores from it anyway)', file=sys.stderr)
        return EXIT_PROBLEM
    env = store.load(name)
    db = _session(args.db_url)
    try:
        plan = restore(db, env, keys=not args.no_keys, dry_run=True)
        for k, v in plan.items():
            print(f'{k}: {", ".join(v) if v else "-"}')
        if args.dry_run or not (plan['roles_created'] or plan['users_created'] or plan['keys_created']):
            print('nothing changed' + (' (dry run)' if args.dry_run else ''))
            return EXIT_OK
        if not args.yes:
            typed = input(f'Type the snapshot name to restore from it ({name}): ').strip()
            if typed != name:
                print('not confirmed; nothing changed', file=sys.stderr)
                return EXIT_PROBLEM
        done = restore(db, env, keys=not args.no_keys)
    finally:
        db.close()
    _audit('snapshot.restored', 'success', name, actor='cli',
           details={k: v for k, v in done.items() if v})
    print(f'restored from {name}. Restored users have no usable password: an administrator sets one '
          '(POST /api/admin/users/{uid}/password); they must change it at next sign-in.')
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m sajha.snapshots',
                                description='List, verify, compare and restore from SAJHA snapshots.')
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--dir', help='snapshot directory (default: snapshots.dir)')
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('list', parents=[common], help='the snapshots, oldest first')
    s.set_defaults(func=cmd_list)
    s = sub.add_parser('verify', parents=[common], help='check hashes, signatures and the chain')
    s.add_argument('--public-key', help='a PEM or JWKS file with the key that signed older snapshots')
    s.add_argument('--json', action='store_true')
    s.set_defaults(func=cmd_verify)
    s = sub.add_parser('diff', parents=[common], help='what changed between two snapshots')
    s.add_argument('a')
    s.add_argument('b')
    s.add_argument('--json', action='store_true')
    s.set_defaults(func=cmd_diff)
    s = sub.add_parser('show', parents=[common], help='print one snapshot')
    s.add_argument('name')
    s.set_defaults(func=cmd_show)
    s = sub.add_parser('restore', parents=[common],
                       help='re-create missing roles, users and persistent key records from a snapshot')
    s.add_argument('name')
    s.add_argument('--db-url', help="SQLAlchemy URL of the database (default: SAJHA's)")
    s.add_argument('--public-key', help='a PEM or JWKS file with the key that signed the snapshot')
    s.add_argument('--no-keys', action='store_true', help='users and roles only')
    s.add_argument('--dry-run', action='store_true', help='show what would be created; change nothing')
    s.add_argument('--yes', action='store_true', help='do not ask for confirmation')
    s.add_argument('--allow-unverified', action='store_true', help='restore from a snapshot that does not verify')
    s.set_defaults(func=cmd_restore)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, OSError) as e:
        print(f'error: {e}', file=sys.stderr)
        return EXIT_CANNOT


if __name__ == '__main__':
    sys.exit(main())
