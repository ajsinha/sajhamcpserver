"""
SAJHA MCP Server — shipped workflows: definitions in ``config/workflows/`` installed at start-up.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A workflow lives in the database and runs as its owner (docs/architecture/Workflows.md). A shipped
definition (``*.yaml``, ``*.yml`` or ``*.json`` under ``config/workflows``) is saved at start-up
when no workflow of that name exists, owned by the seeded administrator ``admin``, and only when
that user exists. An existing
workflow of the same name is never changed, so an administrator's edits and an enabled flag set
to off are kept. A deleted shipped workflow comes back at the next start; disable it instead.
"""

from __future__ import annotations

import glob
import logging
import os
from typing import List

logger = logging.getLogger(__name__)


SHIPPED_DIR = 'config/workflows'
SHIPPED_OWNER = 'admin'


def _owner_exists(owner: str) -> bool:
    try:
        from sajha.workflows import identity
        identity.resolve(owner)
        return True
    except Exception:
        return False


def install_shipped(svc, directory: str = '', owner: str = '') -> List[str]:
    """Save each shipped definition that has no workflow yet; returns the names installed."""
    directory = directory or SHIPPED_DIR
    owner = owner or SHIPPED_OWNER
    files = sorted(f for ext in ('*.yaml', '*.yml', '*.json') for f in glob.glob(os.path.join(directory, ext)))
    if not files:
        return []
    if not _owner_exists(owner):
        logger.info(f'  Workflows: shipped definitions not installed (owner {owner!r} not found)')
        return []
    installed = []
    for path in files:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                defn = svc.validate(f.read())
            if svc.store.get_workflow(defn['name']) is not None:
                continue
            svc.save(defn, user_id=owner, is_admin=True)
            installed.append(defn['name'])
        except Exception as e:
            logger.warning(f'  Workflows: shipped definition {os.path.basename(path)} not installed: {e}')
    if installed:
        logger.info(f'  Workflows: installed shipped {", ".join(installed)} (owner {owner})')
    return installed
