"""
SAJHA MCP Server — schema helper for operators and DBAs.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

    python -m sajha.db check                          tables/columns SAJHA uses that the configured
                                                      database lacks (exit 3 when something is missing)
    python -m sajha.db sql [--dialect D] [--seed]     print the schema file (or the seed file) for psql -f

There are no migrations, and this tool changes nothing: the operator runs
db/scripts/postgresql/schema.sql (then seed.sql) with psql.  It reads the database from
config/application.yml and SAJHA_DB_* like the server does (``SAJHA_CONFIG_FILE`` picks
another file; ``--url`` overrides).  ``sajha db ...`` in the client CLI runs this module
from a server checkout.  Guide: docs/getting-started/Database Setup.md
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_MISSING = 0, 1, 2, 3


def _settings():
    from sajha.core.config import get_settings
    return get_settings()


def _root(args):
    from sajha.db import schema
    return schema.scripts_root(args.scripts_dir or _settings().db_scripts_dir)


def cmd_check(args) -> int:
    from sajha.db import schema
    from sajha.db.engine import create_db_engine
    engine = create_db_engine(_settings(), url=args.url or None)
    print(f'database:  {engine.url.render_as_string(hide_password=True)}')
    miss = schema.missing(engine)
    if not miss:
        print(f'Schema is complete: every table and column SAJHA uses is present '
              f'({len(schema.tables())} tables).')
        return EXIT_OK
    print(schema.not_ready_message(engine, miss, _root(args)))
    return EXIT_MISSING


def cmd_sql(args) -> int:
    from sajha.db import schema
    dialect = args.dialect or ('postgresql' if _settings().db_type == 'postgresql' else 'sqlite')
    f = (schema.seed_file if args.seed else schema.schema_file)(dialect, _root(args))
    sys.stdout.write(f.read_text(encoding='utf-8'))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m sajha.db',
                                description='SAJHA database schema helper (docs/getting-started/Database Setup.md). '
                                            'It never changes the database.')
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--scripts-dir', help='schema file root (default: db.scripts_dir, db/scripts)')
    sub = p.add_subparsers(dest='command', required=True)

    s = sub.add_parser('check', parents=[common],
                       help='list tables and columns the configured database lacks (exit 3 when any)')
    s.add_argument('--url', help='SQLAlchemy database URL (default: db.* from the configuration)')
    s.set_defaults(func=cmd_check)

    s = sub.add_parser('sql', parents=[common], help='print the schema file for review and psql -f (no database access)')
    s.add_argument('--dialect', choices=('postgresql', 'sqlite'), help='default: db.type')
    s.add_argument('--seed', action='store_true', help='print seed.sql (default roles and admin) instead')
    s.set_defaults(func=cmd_sql)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(message)s')
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ImportError, FileNotFoundError, ValueError) as e:
        print(f'error: {e}', file=sys.stderr)
        return EXIT_ERROR


if __name__ == '__main__':
    sys.exit(main())
