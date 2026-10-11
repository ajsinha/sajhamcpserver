"""
SAJHA MCP Server — the sanctions command line.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

    python -m sajha.sanctions refresh [--list ofac_sdn --list eu ...] [--force]
    python -m sajha.sanctions status

``refresh`` downloads the official lists into the local index (sanctions.data_dir) and prints
the outcome as JSON; it exits 1 when a list failed. ``--force`` downloads the EU list even when
its feed shows no new publication.
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog='python -m sajha.sanctions', description='SAJHA sanctions lists')
    sub = p.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('refresh', help='download the official lists into the local index')
    r.add_argument('--list', action='append', dest='lists', help='one list (repeatable); default every enabled list')
    r.add_argument('--force', action='store_true', help='download even when the EU feed shows no new publication')
    sub.add_parser('status', help="each list's publication date, last refresh and entry count")
    args = p.parse_args(argv)
    from sajha.sanctions import refresh, service
    if args.cmd == 'status':
        print(json.dumps(service.lists_status(), indent=2))
        return 0
    try:
        out = refresh.refresh(args.lists, force=args.force)
    except (ValueError, refresh.RefreshBusy) as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0 if out['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
