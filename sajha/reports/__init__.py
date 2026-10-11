"""
SAJHA MCP Server — Reports: governed, repeatable documents built from tool calls.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

  settings.py  reports.* keys
  model.py     the definition (YAML in reports.dir): parse, name rules, reserved names, checks
  store.py     definitions on disk: load, hot reload, notices
  engine.py    a run: sections as tool calls made as the caller, quantities, files, audit
  values.py    value formats and displayed precision
  render.py    Markdown, HTML, PDF (Playwright), XLSX, PPTX, DOCX; marking; provenance appendix
  history.py   stored runs (report data + files under reports.output_dir), visibility, pruning
  compare.py   two runs, section by section
  tools.py     report_<name>, report_list, report_describe, report_run, report_history,
               report_render, report_compare
  service.py   the generated report_<name> tool configs (tool folder "reports"), start-up, watcher

Design: docs/architecture/Reports.md.

API for code that works on runs (``report_narrate``, the report library page)
==============================================================================

Load a run and check the caller may see it::

    from sajha.reports import history
    run = history.load(run_id)                       # dict, or None when there is no such run
    history.may_see(run, caller)                     # caller: sajha.observability.caller.Caller
    history.runs(report, caller, since=None, until=None, status=None, limit=100)   # summaries, newest first
    history.file_bytes(run_id, fmt)                  # a rendered file (bytes) or None
    history.file_path(run_id, fmt)                   # its storage path; history.EXT maps fmt -> extension

Definitions: ``store.definitions()`` (name -> ReportDefinition), ``store.get(name)``,
``engine.may_run(defn, caller)`` (None, or why not). Run one: ``engine.run_report(defn, params,
caller=None, formats=None)`` returns the stored run (raises ``engine.ReportRunError``). Render
again: ``engine.render_and_store(run, [fmt]); history.save(run)``. Compare:
``compare.compare_runs(run_a, run_b)``.

The report data (``run.json``, ``schema: sajha.report.run/1``)::

    run_id, report, title, description, definition_hash, definition_source, owner
    runner: {user_id, roles, auth_type, api_key, is_admin}
    parameters: {...}                     after defaults; dates and years here count as "in the run"
    started_at, finished_at (ISO, UTC), duration_ms
    declared_classification, classification (effective: raised to confidential by data classes)
    status: succeeded | partial | failed
    sections: [{
        id, kind (kpis|table|chart|metric|text|report), title,
        status: ok | empty | text | pending_narration | not_permitted | unavailable | error | skipped,
        error?,
        source?: {tool, version, arguments, called_at, as_of, attribution, data_classes?},
        kpis?: [{label, key, path, format, decimals, currency?, value, display,
                 previous?, change?, pct_change?, previous_display?, change_display?, pct_change_display?}],
        table?: {columns: [{key, label, format, decimals?, currency?}], rows: [{key: value}],
                 row_count, truncated, highlight?: {column, rows: [row index], above?, below?}, key?},
        chart?: {type: bar|line, x, y: [column keys]},
        text?,                             static text, or the commentary once narrated
        narrate?: {sections: [ids], length?, ...}   only on status pending_narration (narration's input)
    }]
    quantities: [{id, section, label, kind, value, display, decimals, format, row?, column?, against?}]
        kind: value       every number a KPI or table cell shows
              previous    the same KPI in the previous run with the same parameters (``against``: its run id)
              change      value - previous
              pct_change  (value - previous) / |previous| * 100
              share       a table cell's percent of its column total (tables of 2..50 rows, all >= 0)
              rank        1-based rank of a table cell in its column, largest first
        ``display`` is the text the report shows and ``decimals`` the precision it shows it at: the
        numbers check compares at that precision (Reports.md §5).
    previous_run_id
    narration: null                        report_narrate records {model, sections, ...} here
    files: {fmt: path}, files_unavailable: {fmt: reason}, deliveries: [], warnings: [str]

To store commentary: set the text section's ``text`` and ``status`` ("text"), set ``narration``,
``history.save(run)``, then ``engine.render_and_store(run, list(run["files"]))`` and save again.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def init_reports(registry):
    """Start-up hook (sajha/app.py): load definitions and publish the generated report tools."""
    from sajha.reports.service import init_reports as _init
    return _init(registry)


def shutdown_reports() -> None:
    from sajha.reports.service import shutdown_reports as _stop
    _stop()
