# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Where a shipped tool's config file is: config/tools/<name>.json or config/tools/<folder>/<name>.json
(tool folders, one level; sajha/tools/tool_files.py). Tests read shipped configs through these helpers
so they keep working when a tool moves between folders."""

import json
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'config' / 'tools'


def tool_file(name: str, root: Path = TOOLS) -> Path:
    """The config file of ``name`` (the root path when there is none yet)."""
    found = [root / f'{name}.json'] + sorted(root.glob(f'*/{name}.json'))
    return next((f for f in found if f.exists()), found[0])


def tool_files(pattern: str = '*.json', root: Path = TOOLS) -> List[Path]:
    """Every config file matching ``pattern`` in the root and the folders."""
    return sorted(root.glob(pattern)) + sorted(root.glob(f'*/{pattern}'))


def read_tool(name: str) -> dict:
    return json.loads(tool_file(name).read_text(encoding='utf-8'))
