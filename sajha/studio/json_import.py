"""
SAJHA MCP Server — Studio > Import JSON: a tool from a pasted or uploaded tool config.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

The config is an ordinary tool config (the JSON a file in config/tools holds). It may carry an
optional top-level ``"folder"``: the tool folder to file it under. That key is a filing instruction,
not part of the tool, so it is removed before the config is saved. The folder offered by default is
that key, else ``metadata.category`` made into a folder name when it is a valid one, else none (the
root). The name must be new everywhere (root and every folder). Administrators only: a config names
the Python class that implements the tool. Guide: docs/studio/MCP Studio User Guide.md.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple


class ImportError_(ValueError):
    """A config that cannot be imported."""


def parse(data: Dict[str, Any]) -> Dict[str, Any]:
    """The config of a request: ``{"config": {...}}`` or ``{"text": "<json>"}``."""
    cfg = data.get('config')
    if cfg is None and isinstance(data.get('text'), str):
        try:
            cfg = json.loads(data['text'])
        except json.JSONDecodeError as e:
            raise ImportError_(f'not valid JSON: {e.msg} (line {e.lineno}, column {e.colno})')
    if not isinstance(cfg, dict):
        raise ImportError_('a tool config is a JSON object')
    return cfg


def suggested_folder(cfg: Dict[str, Any]) -> str:
    """The folder offered for a config: its "folder" key, else its metadata.category when that makes a
    valid folder name, else '' (the root)."""
    from sajha.tools.tool_files import clean_folder, folder_problem, slug_folder
    given = cfg.get('folder')
    if isinstance(given, str) and clean_folder(given) and folder_problem(clean_folder(given)) is None:
        return clean_folder(given)
    md = cfg.get('metadata') if isinstance(cfg.get('metadata'), dict) else {}
    folder = slug_folder(md.get('category'))
    return folder if folder and folder_problem(folder) is None else ''


def check(cfg: Dict[str, Any], folder: Optional[str]) -> Tuple[Dict[str, Any], str, List[str]]:
    """(the config to save, the folder, the problems) for a config and a chosen folder (None: suggested)."""
    from sajha.tools.naming import reserved_name_problem
    from sajha.tools.tool_files import clean_folder, folder_problem, name_taken
    errors: List[str] = []
    target = suggested_folder(cfg) if folder is None else clean_folder(folder)
    why = folder_problem(target)
    if why:
        errors.append(why)
    out = {k: v for k, v in cfg.items() if k != 'folder'}
    name = out.get('name')
    if not isinstance(name, str) or not name.strip():
        errors.append('the config has no "name"')
        name = ''
    else:
        why = reserved_name_problem(name)
        if why:
            errors.append(why)
        where = name_taken(name)
        if where:
            errors.append(f'a tool named {name} exists already ({where}); a tool name may exist in one place only')
    if not out.get('implementation'):
        errors.append('the config has no "implementation" (the class that runs the tool)')
    if not isinstance(out.get('description', ''), str):
        errors.append('"description" must be text')
    return out, target, errors


def preview(data: Dict[str, Any]) -> Dict[str, Any]:
    cfg = parse(data)
    folder = data.get('folder') if isinstance(data.get('folder'), str) else None
    out, target, errors = check(cfg, folder)
    from sajha.tools.tool_files import get_index
    return {'config': out, 'folder': target, 'suggested_folder': suggested_folder(cfg),
            'path': get_index().new_path(out.get('name') or '<name>', target), 'errors': errors,
            'folders': get_index().refresh().folders()}
