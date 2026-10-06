"""
SAJHA Intelligence Layer — secret references.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

``api_key_ref`` (and any other ``*_ref`` value) points at a secret instead of holding it:

    env:NAME                     an environment variable
    file:/path/to/file           the file's contents, stripped
    db:llm_providers/<type>      the api_key column of the existing llm_providers table

The store never logs a resolved value; ``redact()`` masks anything that looks like one.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

_KEYLIKE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|sja_[A-Za-z0-9_\-]{8,}|AIza[0-9A-Za-z_\-]{20,}|"
                      r"(?i:bearer)\s+[A-Za-z0-9._\-]{12,})")


class SecretStore:
    def __init__(self, db_lookup: Optional[Callable[[str, str], Optional[str]]] = None,
                 environ: Optional[Dict[str, str]] = None):
        self._db_lookup = db_lookup          # (table, key) -> secret
        self._environ = environ

    @property
    def environ(self):
        return os.environ if self._environ is None else self._environ

    def resolve(self, ref: Optional[str]) -> Optional[str]:
        if not ref:
            return None
        scheme, _, rest = ref.partition(":")
        scheme = scheme.lower()
        if scheme == "env":
            return self.environ.get(rest) or None
        if scheme == "file":
            p = Path(rest).expanduser()
            try:
                return p.read_text(encoding="utf-8").strip() or None
            except OSError as e:
                logger.warning(f"secret ref file:{p} unreadable: {e.__class__.__name__}")
                return None
        if scheme == "db":
            table, _, key = rest.partition("/")
            if self._db_lookup is None:
                return None
            try:
                return self._db_lookup(table, key) or None
            except Exception as e:
                logger.warning(f"secret ref db:{table}/{key} lookup failed: {e.__class__.__name__}")
                return None
        raise ValueError(f"unknown secret reference scheme in {ref!r} (use env:, file: or db:)")

    @staticmethod
    def redact(text: str) -> str:
        return _KEYLIKE.sub("********", text or "")


def db_secret_lookup(table: str, key: str) -> Optional[str]:
    """Default db: resolver — the api_key of llm_providers where provider_type = key."""
    if table != "llm_providers":
        return None
    from sajha.db.engine import get_db_session
    from sajha.db.dao import LLMProviderDAO
    db = get_db_session()
    try:
        rec = LLMProviderDAO(db).get_by_type(key)
        return rec.api_key if rec else None
    finally:
        db.close()
