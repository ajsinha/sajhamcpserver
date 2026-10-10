"""
SAJHA MCP Server — tool folders from the command line.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

    python -m sajha.tools folders                         the folders, and root files grouped by prefix
    python -m sajha.tools move '<name-or-glob>' --to <folder> [--dry-run]

Moves go through the configured storage backend (config/application.yml ``storage.*``): a rename
on local disk, write-then-delete on an object store. A move never copies: a tool name may exist in
one place only, and two files with one name load neither. On a local git checkout the equivalent
``git mv`` commands are printed so the move can be recorded as one. Guide: docs/clients/Command Line.md.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from collections import defaultdict
from typing import List, Optional

#: The folder suggested for a root file's name prefix (text before the first "_") when the prefix
#: alone is not the provider's name. Anything else is suggested its prefix.
SUGGESTED = {
    'av': 'alphavantage', 'bdf': 'banque_de_france', 'boc': 'bank_of_canada', 'boj': 'bank_of_japan',
    'cg': 'coingecko', 'check': 'webcrawler', 'connected': 'connected_accounts', 'crawl': 'webcrawler',
    'customer': 'olap', 'extract': 'webcrawler', 'fed': 'federal_reserve', 'get': 'webcrawler',
    'github': 'connected_accounts', 'ir': 'investor_relations', 'ms365': 'connected_accounts',
    'pboc': 'peoples_bank_of_china', 'rbi': 'reserve_bank_of_india', 'sec': 'edgar',
    'slack': 'connected_accounts', 'un': 'united_nations', 'wb': 'worldbank', 'wiki': 'wikipedia',
    'yf': 'yahoo',
}


def _init_storage() -> None:
    try:
        from sajha.core.properties_configurator import PropertiesConfigurator
        from sajha.core.storage import init_storage
        init_storage(PropertiesConfigurator(yaml_file=os.environ.get('SAJHA_CONFIG_FILE', 'config/application.yml')))
    except Exception as e:
        print(f'storage: using the local filesystem ({e})', file=sys.stderr)


def suggest(name: str) -> str:
    from sajha.tools.tool_files import slug_folder
    prefix = name.split('_', 1)[0]
    return SUGGESTED.get(prefix) or slug_folder(prefix) or ''


def cmd_folders(out=sys.stdout) -> int:
    from sajha.tools.tool_files import get_index
    idx = get_index().refresh()
    counts = defaultdict(int)
    root: List[str] = []
    for rel, name, folder in idx.entries():
        if folder:
            counts[folder] += 1
        else:
            root.append(name)
    print(f'Tools directory: {idx.prefix}', file=out)
    print('Folders:' if counts else 'Folders: none', file=out)
    for folder in sorted(counts):
        print(f'  {folder:<28} {counts[folder]} tool(s)', file=out)
    groups = defaultdict(list)
    for name in root:
        groups[name.split('_', 1)[0]].append(name)
    print(f'Root: {len(root)} tool(s)', file=out)
    for prefix in sorted(groups):
        names = groups[prefix]
        print(f'  {prefix + "_*":<28} {len(names)} tool(s), suggested folder: {suggest(names[0]) or "(none)"}', file=out)
    for name, rels in sorted(idx.duplicates().items()):
        print(f'DUPLICATE {name}: {", ".join(rels)} (neither loads)', file=out)
    for rel in idx.too_deep():
        print(f'IGNORED (nested too deep): {rel}', file=out)
    return 0


def _git_checkout(path: str) -> bool:
    try:
        r = subprocess.run(['git', 'rev-parse', '--is-inside-work-tree'], cwd=path, capture_output=True,
                           text=True, timeout=10)
        return r.returncode == 0 and r.stdout.strip() == 'true'
    except Exception:
        return False


def cmd_move(pattern: str, folder: str, dry_run: bool, out=sys.stdout) -> int:
    from sajha.core.storage import LocalStorageBackend, get_storage
    from sajha.tools.tool_files import files_matching, move
    names = sorted({n for n, _ in files_matching(pattern)})
    if not names:
        print(f'no tool matches {pattern!r}', file=sys.stderr)
        return 1
    try:
        plan = move(names, folder, dry_run=dry_run)
    except ValueError as e:
        print(f'refused: {e}', file=sys.stderr)
        return 1
    st = get_storage()
    git = isinstance(st, LocalStorageBackend) and _git_checkout(str(st.base_dir))
    for name, old, new in plan:
        print(f'{"would move" if dry_run else "moved"} {name}: {old} -> {new}', file=out)
    if not plan:
        print('nothing to move', file=out)
    if git and plan:
        if dry_run:
            print('# the equivalent git commands (a move, never a copy):', file=out)
            for _, old, new in plan:
                print(f'git mv {old} {new}', file=out)
        else:
            print('# the files are moved; git records each as a rename once both paths are staged:', file=out)
            for _, old, new in plan:
                print(f'git add -A -- {old} {new}', file=out)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog='python -m sajha.tools', description='Tool folders: list and move tool configs.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('folders', help='list the folders, and root files grouped by prefix with a suggested folder')
    mv = sub.add_parser('move', help='move tools (a name or a glob) into a folder ("" for the root)')
    mv.add_argument('pattern', help='a tool name or a glob, e.g. "fmp_*"')
    mv.add_argument('--to', required=True, dest='folder', help='the folder ("" moves back to the root)')
    mv.add_argument('--dry-run', action='store_true', help='print what would move, move nothing')
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    _init_storage()
    if args.cmd == 'folders':
        return cmd_folders()
    return cmd_move(args.pattern, args.folder, args.dry_run)


if __name__ == '__main__':
    sys.exit(main())
