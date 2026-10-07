"""
SAJHA MCP Server — Data Connectors: governed, read-only enterprise data stores as tools.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

  model.py     the connection record (validation; secret references only)
  store.py     records at config/connectors/<id>.json (storage backend)
  settings.py  connectors.* keys
  sqltext.py   SQL tokenizer (comments, strings, :name parameters)
  guard.py     the statement guard for caller SQL (sqlglot, or a conservative scanner)
  drivers/     one SQL driver per kind (optional packages)
  vector.py    pgvector, Qdrant, Elasticsearch / OpenSearch
  pool.py      idle-connection pool
  catalog.py   schema catalog cache
  masking.py   column masking
  engine.py    list / describe / query / view, limits, audit, metrics
  tools.py     ConnectorTool, the implementation of every generated tool
  service.py   save, test, sync tools, delete

Design: docs/architecture/Data Connectors.md.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def init_connectors(registry) -> None:
    """Start-up: regenerate every connection's tools (``connectors.sync_on_startup``)."""
    from sajha.connectors import service, settings, store
    ids = store.ids()
    if not ids:
        return
    if not settings.sync_on_startup():
        logger.info(f'  Data connectors: {len(ids)} connection(s); tool sync at start-up is off')
        return
    out = service.sync_all(registry)
    n = sum(len(r.get('tools') or []) for r in out.get('connections') or [])
    logger.info(f'  Data connectors: {len(ids)} connection(s), {n} tool(s)')
    for cid, err in (out.get('errors') or {}).items():
        logger.warning(f'  Data connector {cid}: {err}')


def shutdown_connectors() -> None:
    from sajha.connectors import pool
    pool.clear()
