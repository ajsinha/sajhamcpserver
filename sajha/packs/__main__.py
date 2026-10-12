"""
SAJHA MCP Server — provider packs from the command line.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

    python -m sajha.packs list
    python -m sajha.packs show <id>
    python -m sajha.packs plan <id> [--client-id ID] [--client-secret-ref env:NAME] [--tenant T] [--json]
    python -m sajha.packs install <id> --hash <review hash> --approve [same inputs as plan] [--as USER]
    python -m sajha.packs uninstall <id> [--as USER]

Runs against the storage backend and configuration of the working directory, like
``python -m sajha.quality``: tool configs and the provider preset are written there and a running
server picks them up (the tool registry and the provider registry both notice changed files). The
install gate is the same as the admin API's; a policy rule that answers ``require_approval`` needs the
shared state store (``state.backend: redis`` or ``database``) so the Approvals page sees the request.
Exit status: 0 done, 1 refused or failed, 2 bad usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional


class _User:
    """The acting administrator, for the policy engine and the audit record."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.roles = ['admin']
        self.auth_type = 'cli'
        self.is_admin = True


def _ensure_db() -> None:
    """Open SAJHA's database when this process has not (the audit record and a database state store
    need it), as ``python -m sajha.quality`` does. Best effort."""
    try:
        from sajha.db import engine
        if engine._engine is None:
            from sajha.core.config import get_settings
            engine.init_db(get_settings())
    except Exception as e:
        print(f'database not available: {e}', file=sys.stderr)


def _inputs(a) -> Dict[str, Any]:
    return {k: v for k, v in (('client_id', a.client_id), ('client_secret_ref', a.client_secret_ref),
                              ('tenant', a.tenant), ('redirect_uri', a.redirect_uri)) if v}


def _print_plan(p: Dict[str, Any]) -> None:
    pk, pr, api = p['pack'], p['provider'], p['api']
    print(f"{pk['title']} {pk['version']} ({pk['id']}) - spec licence {p['licence']}, source {pk['source'].get('url')}")
    print(f"provider {pr['id']}: {pr.get('title', '')} configured={pr.get('configured')} "
          f"api_hosts={','.join(pr.get('api_hosts') or [])}")
    if pr.get('redirect_uri'):
        print(f"  register this redirect URI with the service: {pr['redirect_uri']}")
    print(f"tools ({api['prefix']} -> {api['base_url']}, folder {api['folder']}):")
    for o in api['operations']:
        ann = ','.join(k for k, v in (o['annotations'] or {}).items() if v is True)
        print(f"  {o['status']:9} {o['name']:48} {o['key']}  [{ann}]")
    for w in p['warnings']:
        print(f'warning: {w}')
    for e in p['errors']:
        print(f'error: {e}')
    pol = (p.get('policy') or {}).get('deploy') or {}
    if pol:
        print(f"policy: studio.deploy pack:{pk['id']} -> {pol.get('effect')}")
    print(f"review hash: {p['hash']}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog='python -m sajha.packs', description='Provider packs')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list', help='every pack and whether it is installed')
    s = sub.add_parser('show', help="a pack's manifest summary and licence")
    s.add_argument('id')
    for name in ('plan', 'install'):
        s = sub.add_parser(name)
        s.add_argument('id')
        s.add_argument('--client-id', default='')
        s.add_argument('--client-secret-ref', default='', help='env:NAME, file:/path or db:table/key')
        s.add_argument('--tenant', default='')
        s.add_argument('--redirect-uri', default='')
        s.add_argument('--as', dest='user', default='cli')
        s.add_argument('--json', action='store_true')
        if name == 'install':
            s.add_argument('--hash', required=True, help='the review hash printed by plan')
            s.add_argument('--approve', action='store_true', help='you reviewed the plan and approve it')
    s = sub.add_parser('uninstall')
    s.add_argument('id')
    s.add_argument('--as', dest='user', default='cli')
    a = ap.parse_args(argv)

    from sajha.packs import service
    from sajha.packs.manifest import PackError
    try:
        if a.cmd == 'list':
            cat = service.catalog()
            for p in cat['packs']:
                state = f"installed {p['installed']['version']}" if p['installed'] else 'not installed'
                print(f"{p['id']:12} {p['version']:8} {state:20} {p['title']} ({p['source'].get('licence')})")
            for name, why in cat['problems'].items():
                print(f'problem: {why}')
            return 0
        if a.cmd == 'show':
            print(json.dumps(service.show(a.id), indent=2, default=str))
            return 0
        user = _User(getattr(a, 'user', 'cli') or 'cli')
        if a.cmd in ('install', 'uninstall'):
            _ensure_db()
        if a.cmd == 'plan':
            p = service.plan(a.id, _inputs(a), None, user)
            print(json.dumps(p, indent=2, default=str)) if a.json else _print_plan(p)
            return 1 if p['errors'] else 0
        if a.cmd == 'install':
            r = service.install(a.id, _inputs(a), a.hash, a.approve, None, user)
            print(json.dumps(r, indent=2, default=str)) if a.json else print(r['message'])
            return 0
        if a.cmd == 'uninstall':
            print(service.uninstall(a.id, None, user)['message'])
            return 0
    except PackError as e:
        print(f'refused: {e}', file=sys.stderr)
        if e.extra.get('approval_id'):
            print(f"approval request: {e.extra['approval_id']}", file=sys.stderr)
        return 1
    return 2


if __name__ == '__main__':
    from sajha.core.paths import apply_tmp_dir_or_exit
    apply_tmp_dir_or_exit()                  # app.tmp_dir for this command's temp files
    sys.exit(main())
