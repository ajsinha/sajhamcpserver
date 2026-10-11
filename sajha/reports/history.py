"""
SAJHA MCP Server — report runs: the stored report data, rendered files and run history.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A run lives in the storage backend under ``reports.output_dir`` (default ``data/reports``,
git-ignored)::

    <output_dir>/<report>/<run_id>/run.json        the report data (sajha/reports/__init__.py)
    <output_dir>/<report>/<run_id>/report.<ext>    each rendered format (md, html, pdf, xlsx, pptx, docx)

A run id is ``<report>-<UTC yyyymmddThhmmssmmm>-<6 hex>`` (milliseconds): it sorts by time and names its report,
so a run is found without an index. Runs older than ``reports.history_days`` are pruned when the
same report runs again.

**Who sees a run.** Its data was fetched with the runner's access, so only the runner and
administrators may read, render or compare it (:func:`may_see`).
"""

from __future__ import annotations

import json
import logging
import posixpath
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sajha.reports import settings

logger = logging.getLogger(__name__)

EXT = {'markdown': 'md', 'html': 'html', 'pdf': 'pdf', 'xlsx': 'xlsx', 'pptx': 'pptx', 'docx': 'docx'}
RUN_ID_RE = re.compile(r'^([a-z][a-z0-9_]{0,47})-(\d{8}T\d{9})-([0-9a-f]{6})$')


def _storage():
    from sajha.reports.files import backend   # absolute dirs: plain pathlib
    return backend()


def new_run_id(report: str, when: Optional[datetime] = None) -> str:
    when = when or datetime.now(timezone.utc)
    return f'{report}-{when.strftime("%Y%m%dT%H%M%S")}{when.microsecond // 1000:03d}-{secrets.token_hex(3)}'


def report_of(run_id: str) -> Optional[str]:
    m = RUN_ID_RE.match(run_id or '')
    return m.group(1) if m else None


def run_dir(run_id: str) -> str:
    report = report_of(run_id)
    if not report:
        raise ValueError(f'not a run id: {run_id!r}')
    return f'{settings.output_dir()}/{report}/{run_id}'


def file_path(run_id: str, fmt: str) -> str:
    return f'{run_dir(run_id)}/report.{EXT[fmt]}'


def save(data: Dict[str, Any]) -> str:
    path = f'{run_dir(data["run_id"])}/run.json'
    st = _storage()
    st.write_json_atomic(path, data) if hasattr(st, 'write_json_atomic') else st.write_json(path, data)
    return path


def write_file(run_id: str, fmt: str, content: Any) -> str:
    path = file_path(run_id, fmt)
    st = _storage()
    if isinstance(content, str):
        st.write_text(path, content)
    else:
        st.write_bytes(path, bytes(content))
    return path


def load(run_id: str) -> Optional[Dict[str, Any]]:
    """The report data of a run (None when there is no such run)."""
    try:
        path = f'{run_dir(run_id)}/run.json'
    except ValueError:
        return None
    st = _storage()
    try:
        if not st.exists(path):
            return None
        return st.read_json(path)
    except Exception as e:
        logger.warning(f'reports: cannot read {path}: {e}')
        return None


def file_bytes(run_id: str, fmt: str) -> Optional[bytes]:
    """A rendered file of a run (None when it was not rendered)."""
    try:
        path = file_path(run_id, fmt)
    except (ValueError, KeyError):
        return None
    st = _storage()
    return st.read_bytes(path) if st.exists(path) else None


def run_ids(report: str) -> List[str]:
    """Every stored run id of ``report``, newest first."""
    base = f'{settings.output_dir()}/{report}'
    try:
        files = _storage().list_files(base, 'run.json')
    except Exception:
        return []
    ids = set()
    for f in files:
        rid = posixpath.basename(posixpath.dirname(f.replace('\\', '/')))
        if report_of(rid) == report:
            ids.add(rid)
    return sorted(ids, reverse=True)


def may_see(run: Dict[str, Any], caller) -> bool:
    if caller is None:
        return False
    if getattr(caller, 'is_admin', False):
        return True
    runner = (run.get('runner') or {}).get('user_id')
    return bool(runner) and runner == getattr(caller, 'user_id', None)


def summary(run: Dict[str, Any]) -> Dict[str, Any]:
    return {'run_id': run.get('run_id'), 'report': run.get('report'), 'status': run.get('status'),
            'started_at': run.get('started_at'), 'finished_at': run.get('finished_at'),
            'runner': (run.get('runner') or {}).get('user_id'), 'parameters': run.get('parameters'),
            'classification': run.get('classification'), 'formats': sorted((run.get('files') or {}).keys()),
            'deliveries': run.get('deliveries') or [], 'warnings': len(run.get('warnings') or [])}


def runs(report: str, caller=None, since: Optional[str] = None, until: Optional[str] = None,
         status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Run summaries the caller may see, newest first. ``since``/``until``: YYYY-MM-DD or ISO times."""
    out = []
    for rid in run_ids(report):
        run = load(rid)
        if run is None or (caller is not None and not may_see(run, caller)):
            continue
        started = str(run.get('started_at') or '')
        if since and started[:len(since)] < since:
            continue
        if until and started[:len(until)] > until:
            continue
        if status and run.get('status') != status:
            continue
        out.append(summary(run))
        if len(out) >= limit:
            break
    return out


def previous(report: str, parameters: Dict[str, Any], caller, before: str) -> Optional[Dict[str, Any]]:
    """The latest earlier run of ``report`` with the same parameters that the caller may see."""
    m = RUN_ID_RE.match(before or '')
    before_ts = m.group(2) if m else '99999999T999999999'
    for rid in run_ids(report):
        mm = RUN_ID_RE.match(rid)
        if rid == before or not mm or mm.group(2) > before_ts:
            continue
        run = load(rid)
        if run and run.get('parameters') == parameters and run.get('status') in ('succeeded', 'partial') \
                and may_see(run, caller):
            return run
    return None


def resolve(report: str, ref: str, caller) -> Optional[Dict[str, Any]]:
    """A run by id, or by date (YYYY-MM-DD: the latest run on that day the caller may see)."""
    if RUN_ID_RE.match(ref or ''):
        run = load(ref)
        return run if run and run.get('report') == report and may_see(run, caller) else None
    if re.match(r'^\d{4}-\d{2}-\d{2}$', ref or ''):
        for rid in run_ids(report):
            run = load(rid)
            if run and str(run.get('started_at', ''))[:10] == ref and may_see(run, caller):
                return run
    return None


def prune(report: str, keep: Optional[str] = None) -> List[str]:
    """Delete runs of ``report`` older than ``reports.history_days`` (0 keeps every run)."""
    days = settings.history_days()
    if days <= 0:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y%m%dT%H%M%S')
    st = _storage()
    removed = []
    for rid in run_ids(report):
        m = RUN_ID_RE.match(rid)
        if not m or m.group(2) >= cutoff or rid == keep:
            continue
        base = run_dir(rid)
        try:
            for f in st.list_files(base, '*'):
                st.delete(f)
            removed.append(rid)
        except Exception as e:
            logger.debug(f'reports prune {rid}: {e}')
    return removed


def dumps(data: Any) -> str:
    return json.dumps(data, indent=2, default=str, ensure_ascii=False)
