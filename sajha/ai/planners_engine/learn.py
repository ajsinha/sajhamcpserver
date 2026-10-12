"""
SAJHA MCP Server — the planner learning job: ``python -m sajha.ai.planners_engine.learn``.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Ranks planners per tool and question class from saved eval runs and the recorded outcomes of
automatic choices, and writes a *proposal* that takes effect only when an administrator approves
it on the Planner routing page (``/admin/planner-routing``). Also lists proposals and versions,
rolls back, and stops or resumes the online bandit.

    python -m sajha.ai.planners_engine.learn                 # rank and write a proposal
    python -m sajha.ai.planners_engine.learn --dry-run       # rank and print, write nothing
    python -m sajha.ai.planners_engine.learn status          # active version, proposals, bandit
    python -m sajha.ai.planners_engine.learn rollback N      # make version N active (0: no rules)
    python -m sajha.ai.planners_engine.learn bandit stop|resume|reset

Docs: docs/architecture/LLM Tools.md §9.13, docs/architecture/Planner Reference.md §6.6.2.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional


def _ensure_db() -> None:
    """Open SAJHA's database when this process has not (eval runs, audit records, the database state store)."""
    try:
        from sajha.db import engine
        if engine._engine is None:
            from sajha.core.config import get_settings
            engine.init_db(get_settings())
    except Exception as e:
        print(f"database not available: {e}", file=sys.stderr)


def _print_rules(rules) -> None:
    if not rules:
        print("  no rules: no class has two planners with enough evidence (ai.planners.learning.min_samples)")
    for tool, by_cls in rules.items():
        for cls, e in by_cls.items():
            sc = e["scores"]
            ranked = ", ".join(f"{p} {sc[p]['score']:.2f} (n={sc[p]['n']})" for p in e["order"])
            print(f"  {tool} [{cls}]: {ranked}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sajha.ai.planners_engine.learn",
                                 description="Rank planners from results and propose routing rules.")
    ap.add_argument("--dry-run", action="store_true", help="rank and print; write no proposal")
    ap.add_argument("--json", action="store_true", help="print JSON")
    ap.add_argument("--by", default="cli", help="recorded as the proposal's author (default cli)")
    sub = ap.add_subparsers(dest="cmd")
    ss = sub.add_parser("status", help="the active version, versions, proposals and the bandit")
    ss.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print JSON")
    rb = sub.add_parser("rollback", help="make an approved version active again (0: no rules)")
    rb.add_argument("version", type=int)
    bd = sub.add_parser("bandit", help="the online bandit's kill switch and its statistics")
    bd.add_argument("action", choices=["stop", "resume", "reset"])
    a = ap.parse_args(argv)
    _ensure_db()
    from sajha.ai.planners_engine import learning as L
    if a.cmd == "status":
        st = L.status()
        if a.json:
            print(json.dumps(st, indent=2, default=str))
            return 0
        print(f"rules directory: {st['dir']}; active version: {st['active'] or 'none'}")
        for v in st["versions"][:10]:
            print(f"  version {v['version']}: approved by {v.get('approved_by')} from {v.get('proposal')}")
        for p in st["proposals"][:10]:
            print(f"  proposal {p['id']}: {p['status']}, {len(p.get('diff') or [])} change(s), hash {p['hash'][:12]}")
        b = st["bandit"]
        print(f"bandit: {'on' if b['enabled'] else 'off'}{', stopped: ' + b['killed']['reason'] if b['killed'] else ''}"
              f"; {len(b['arms'])} arm(s)")
        return 0
    if a.cmd == "rollback":
        try:
            L.activate(a.version, a.by, "command line")
        except L.RoutingError as e:
            print(str(e), file=sys.stderr)
            return 2
        print(f"active version: {a.version or 'none'}")
        return 0
    if a.cmd == "bandit":
        b = L.get_bandit()
        if a.action == "stop":
            b.kill(a.by, "command line")
        elif a.action == "resume":
            b.resume(a.by)
        else:
            print(f"cleared {b.reset(a.by)} arm(s)")
        return 0
    doc = L.learn(created_by=a.by, source="cli", write=not a.dry_run)
    if a.json:
        print(json.dumps(doc, indent=2, default=str))
        return 0
    ev = doc["evidence"]
    print(f"evidence: {ev['eval_outcomes']} eval outcome(s), {ev['run_outcomes']} run outcome(s)")
    _print_rules(doc["rules"])
    if not a.dry_run:
        print(f"proposal {doc['id']} written ({len(doc['diff'])} change(s)); approve it on /admin/planner-routing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
