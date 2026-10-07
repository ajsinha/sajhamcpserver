"""
SAJHA MCP Studio — who made a tool (Roadmap X2).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Every tool a Studio creator deploys records its creator in the config's metadata
(``metadata.created_by``, the user id) and which creator made it (``metadata.studio_creator``).
A non-admin may change or delete only tools that name them as creator; a tool with no
recorded creator (shipped tools, tools made before this was recorded) is the administrators'.
Composites keep their creator in the database row (``composite_tools.created_by``) and API
imports in the import record (``created_by``). Docs: docs/security/Security Model.md §5.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def creator_of(config: Optional[Dict[str, Any]]) -> str:
    """The user id a tool config records as its creator ('' when none)."""
    md = (config or {}).get('metadata') if isinstance(config, dict) else None
    return str((md or {}).get('created_by') or '') if isinstance(md, dict) else ''


def stamp(config: Dict[str, Any], user_id: str, creator: str = '') -> Dict[str, Any]:
    """Record the creator in a tool config (in place; returns it). An existing creator is kept."""
    md = config.get('metadata')
    if not isinstance(md, dict):
        md = config['metadata'] = {}
    if user_id and not md.get('created_by'):
        md['created_by'] = str(user_id)
    if creator and not md.get('studio_creator'):
        md['studio_creator'] = creator
    return config


def stamp_file(tool_name: str, user_id: str, creator: str = '') -> bool:
    """Record the creator in ``config/tools/<tool_name>.json`` (through the storage backend)."""
    from sajha.core.storage import get_storage, write_tool_config
    rel = f'config/tools/{tool_name}.json'
    try:
        config = json.loads(get_storage().read_text(rel))
    except Exception as e:
        logger.warning(f'Studio: cannot read {rel} to record its creator: {e}')
        return False
    if not isinstance(config, dict):
        return False
    before = json.dumps(config, sort_keys=True)
    stamp(config, user_id, creator)
    if json.dumps(config, sort_keys=True) != before:
        write_tool_config(rel, json.dumps(config, indent=2))
    return True


def refusal(auth: Any, created_by: str, what: str) -> Optional[str]:
    """The message for a non-admin changing something someone else made, or None when allowed."""
    from sajha.auth import is_owner
    if is_owner(auth, created_by):
        return None
    if not created_by:
        return f'"{what}" records no creator; only an administrator may change or delete it'
    return f'"{what}" was created by someone else; only its creator or an administrator may change or delete it'
