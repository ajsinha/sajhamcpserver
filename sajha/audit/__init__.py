"""
SAJHA MCP Server — the tamper-evident audit: hash-chained records, signed anchors,
verification and SIEM export.

:func:`record` is the one way to write an audit record (``AuditLogger.log`` calls it; so
do the policy engine and approvals). The process's :class:`~sajha.audit.chain.ChainWriter`
hashes it into this process's chain and stores it; the :class:`~sajha.audit.sinks.ExportManager`
streams it to the configured SIEM sinks. ``python -m sajha.audit verify`` checks the
chains. Design: docs/architecture/Policy and Audit.md, sections 7 and 8.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_writer = None
_exporter = None
_lock = threading.Lock()


def get_exporter():
    global _exporter
    if _exporter is None:
        with _lock:
            if _exporter is None:
                from sajha.audit.sinks import ExportManager
                try:
                    _exporter = ExportManager.from_config()
                except Exception as e:
                    logger.error(f'Audit export unavailable: {e}')
                    _exporter = ExportManager()
    return _exporter


def get_writer():
    """This process's chain writer (created on first use)."""
    global _writer
    if _writer is None:
        with _lock:
            if _writer is None:
                from sajha.audit.chain import ChainWriter
                _writer = ChainWriter(on_record=lambda rec: get_exporter().dispatch(rec))
    return _writer


def set_writer(writer, exporter=None) -> None:
    """Replace the writer (and exporter) of this process (tests, embedding)."""
    global _writer, _exporter
    _writer = writer
    if exporter is not None or writer is None:
        _exporter = exporter


def record(event: str, actor: Optional[Dict[str, Any]] = None, resource: Optional[Dict[str, Any]] = None,
           outcome: Optional[str] = None, details: Any = None) -> Optional[Dict[str, Any]]:
    """Append one audit record; never raises (audit must not break the call it records)."""
    try:
        return get_writer().append(event, actor=actor, resource=resource, outcome=outcome, details=details)
    except Exception as e:
        logger.error(f'audit record {event} failed: {e}', exc_info=True)
        return None


def init_audit() -> None:
    """Start-up: open this process's chain and start the sinks."""
    try:
        get_exporter()
        get_writer().append('server.start', actor={'user': 'system'})
    except Exception as e:
        logger.warning(f'Audit chain: {e}')


def shutdown_audit(timeout: float = 5.0) -> None:
    """Close the chain (chain.close + a final anchor) and drain the sinks."""
    global _writer, _exporter
    w, ex = _writer, _exporter
    try:
        if w is not None:
            w.close()
    except Exception as e:
        logger.debug(f'audit chain close: {e}')
    try:
        if ex is not None:
            ex.stop(timeout)
    except Exception as e:
        logger.debug(f'audit export stop: {e}')
    _writer = _exporter = None


def status() -> Dict[str, Any]:
    out: Dict[str, Any] = {'writer': _writer.status() if _writer is not None else None}
    out['export'] = get_exporter().status()
    return out
