"""
SAJHA MCP Server — planners chosen by learning from results (``ai.planners.learning``).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Automatic planner selection (a ``classify`` stage with ``menu: planners``, the shipped ``auto``)
chooses by rules, a model's label and escalation on failed checks. This module adds a third
mechanism in two parts, both working only on the candidates that stage already allows (the tool's
``planner_choices``, the eval filter, and the roles that may run a role-limited planner):

* **Offline ranking, approved by a person.** ``learn()`` reads the evidence (saved eval runs per
  planner, and the outcomes of earlier automatic choices recorded in the audit), ranks planners
  per tool and question class, and writes a *proposal*. Nothing changes until an administrator
  approves the proposal's exact hash on the Planner routing page; the approved rules become a new
  immutable version, and any earlier version (or none) can be made active again (rollback).
* **An opt-in online bandit** (Thompson sampling or UCB), off by default, that exploits arms with
  enough evidence and explores at most ``bandit_exploration`` of the choices in a sliding window.
  Every choice and its reward go into the run's audit record (``planner_choice``). A kill switch
  in the state store stops it on every worker; a guard trips the switch when explored choices do
  badly.

Docs: docs/architecture/LLM Tools.md §9.13, docs/architecture/Planner Reference.md §6.6.2.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import math
import os
import random
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

APPROVE_ACTION = "planners.routing.approve"     # the pseudo tool the policy engine sees for an approval
ANY = "*"                                       # the class key of a tool-wide ranking
CLASSES = ("multi_part", "compare", "compute", "lookup", "general")
SELECTORS = ("auto",)                           # planners that choose another planner (their chain's 2nd name ran)
LEARNED_BY = ("learned", "bandit", "explore")   # choice.by values this module produces


def _settings(registry: Any = None):
    if registry is None:
        from sajha.ai.planners_engine.registry import peek_registry
        registry = peek_registry()
    ps = getattr(registry, "settings", None)
    if ps is None:
        from sajha.ai.planners_engine.settings import planner_settings
        ps = planner_settings()
    return ps.learning


# ── question classes ─────────────────────────────────────────────

_MULTI = re.compile(r"\b(and then|after that|as well as|respectively|each of|also)\b|^\s*\d+[.)]\s", re.I | re.M)
_COMPARE = re.compile(r"\b(compare[sd]?|comparison|versus|vs\.?|difference between|better than|which is "
                      r"(better|higher|lower|larger|smaller|cheaper))\b", re.I)
_COMPUTE = re.compile(r"(%|\b(percent(age)?|rate|ratio|average|mean|median|sum|total|growth|change|calculate|"
                      r"compute|how much|how many|npv|irr|cagr|return|interest|yield|forecast)\b)", re.I)
_LOOKUP = re.compile(r"^\s*(what|who|where|when|which|list|show|find|get|look up)\b", re.I)


def question_class(question: str) -> str:
    """One of CLASSES, by fixed rules (no model call), so the class of a question is reproducible:
    several questions or steps, a comparison, a computed figure, a short lookup, or general."""
    q = str(question or "")[:4000]
    if q.count("?") >= 2 or _MULTI.search(q):
        return "multi_part"
    if _COMPARE.search(q):
        return "compare"
    if re.search(r"\d", q) and _COMPUTE.search(q):
        return "compute"
    if _LOOKUP.search(q) and len(q.split()) <= 12:
        return "lookup"
    return "general"


# ── evidence ─────────────────────────────────────────────────────

@dataclass
class Outcome:
    """One piece of evidence: a planner answered a question of a class for a tool."""
    tool: str
    cls: str
    planner: str
    quality: float          # 0..1: an eval question passed, or an automatic choice that held
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    source: str = "eval"    # eval | run


def _base(name: str) -> str:
    return str(name or "").split("@")[0]


def _candidate(chain: str) -> str:
    """The planner a chain credits: ``react`` for "react". A chain through a selector ("auto>react")
    is not credited: after an escalation it names the escalation, not the first choice (the
    question's ``planner_choice`` says which planner was chosen)."""
    parts = [p for p in str(chain or "").split(">") if p]
    return _base(parts[0]) if len(parts) == 1 and parts[0] not in SELECTORS else ""


def _tools_of(es: Any) -> List[str]:
    if getattr(es, "tool", ""):
        return [es.tool]
    return ["ask"] + [t for t in (getattr(es, "tools", None) or []) if not any(c in t for c in "*?[")]


def eval_outcomes(since: float, max_runs: int = 200, store: Any = None, sets: Optional[Dict[str, Any]] = None
                  ) -> List[Outcome]:
    """Outcomes from saved eval runs (``quality_runs``) started after ``since``. A run on a named
    planner credits that planner; a run on a tool's own planner credits the chain's planner when it
    is unambiguous. Each read holds its connection only for that read."""
    if store is None:
        from sajha.quality.store import get_run_store
        store = get_run_store()
    if sets is None:
        from sajha.quality.evals import load_sets
        sets = load_sets()
    out: List[Outcome] = []
    for row in store.list("eval", limit=max_runs):
        if row.get("status", "done") != "done" or float(row.get("started_at") or 0) < since:
            continue
        s = row.get("summary") or {}
        es = sets.get(s.get("set"))
        if es is None:
            continue
        detail = row.get("detail")
        if detail is None and row.get("id"):
            got = store.get(row["id"])
            detail = (got or {}).get("detail")
        if not isinstance(detail, dict):
            continue
        named = str(s.get("planner") or detail.get("planner") or "")
        fixed = "" if named in ("", "default") or named.startswith("tool:") or _base(named) in SELECTORS else _base(named)
        for q in detail.get("questions") or []:
            pc = q.get("planner_choice") if isinstance(q.get("planner_choice"), dict) else None
            planner = fixed or (_base(pc.get("chosen")) if pc and pc.get("chosen") else _candidate(q.get("planner") or ""))
            if not planner:
                continue
            cls = str(pc.get("class")) if pc and pc.get("class") else question_class(q.get("question") or "")
            held = fixed or not pc or (pc.get("outcome") or {}).get("success", True)   # an escalated first choice lost
            for tool in _tools_of(es):
                out.append(Outcome(tool, cls, planner, 1.0 if q.get("passed") and held else 0.0,
                                   float(q.get("cost_usd") or 0.0), float(q.get("latency_ms") or 0.0), "eval"))
    return out


def extract_choice(details: str) -> Optional[Dict[str, Any]]:
    """The ``planner_choice`` object of an audit record's details (which may be cut at 4000 characters)."""
    if not details:
        return None
    i = details.find('"planner_choice": ')
    if i < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(details[i + len('"planner_choice": '):])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def run_outcomes(since: float, limit: int = 5000, rows: Optional[Iterable[str]] = None) -> List[Outcome]:
    """Outcomes of automatic choices recorded in the audit (``llm_tool_run`` and ``ai_ask`` records
    with a ``planner_choice`` that has an outcome). The query's connection is released before the
    records are parsed."""
    if rows is None:
        rows = _audit_details(since, limit)
    out: List[Outcome] = []
    for details in rows:
        c = extract_choice(details)
        o = (c or {}).get("outcome")
        if not c or not isinstance(o, dict) or o.get("success") is None or not c.get("chosen"):
            continue
        out.append(Outcome(str(c.get("tool") or "ask"), str(c.get("class") or "general"), _base(c["chosen"]),
                           1.0 if o.get("success") else 0.0, float(o.get("cost_usd") or 0.0),
                           float(o.get("latency_ms") or 0.0), "run"))
    return out


def _audit_details(since: float, limit: int) -> List[str]:
    try:
        from sqlalchemy import select
        from sajha.db.engine import get_engine
        from sajha.db.models import AuditLog
        t = AuditLog.__table__
        q = (select(t.c.details).where(t.c.action.in_(("llm_tool_run", "ai_ask")))
             .where(t.c.created_at >= datetime.fromtimestamp(since, timezone.utc).replace(tzinfo=None))
             .where(t.c.details.like('%"planner_choice"%')).order_by(t.c.created_at.desc()).limit(max(1, limit)))
        with get_engine().connect() as c:
            return [r[0] for r in c.execute(q).fetchall()]
    except Exception as e:
        logger.warning(f"planner learning: audit records unavailable: {e}")
        return []


# ── ranking ──────────────────────────────────────────────────────

def rank(outcomes: Iterable[Outcome], min_samples: int = 5, cost_weight: float = 0.0,
         latency_weight: float = 0.0) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """{tool: {class or "*": {"order": [planner, ...], "scores": {planner: stats}}}}.

    A planner's score is mean quality - cost_weight * mean cost (USD) - latency_weight * mean
    latency (seconds). Only planners with ``min_samples`` outcomes are ranked, and a class gets a
    rule only when at least two planners are ranked (a ranking of one compares nothing). Ties go to
    more evidence, then to the name."""
    groups: Dict[Tuple[str, str, str], List[Outcome]] = {}
    for o in outcomes:
        for cls in (o.cls, ANY):
            groups.setdefault((o.tool, cls, o.planner), []).append(o)
    table: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for (tool, cls, planner), xs in groups.items():
        n = len(xs)
        qual = sum(x.quality for x in xs) / n
        cost = sum(x.cost_usd for x in xs) / n
        lat = sum(x.latency_ms for x in xs) / n
        score = qual - cost_weight * cost - latency_weight * lat / 1000.0
        table.setdefault(tool, {}).setdefault(cls, {"scores": {}})["scores"][planner] = {
            "n": n, "quality": round(qual, 4), "cost_usd": round(cost, 6), "latency_ms": round(lat, 1),
            "score": round(score, 4), "eval": sum(1 for x in xs if x.source == "eval"),
            "runs": sum(1 for x in xs if x.source == "run"), "ranked": n >= min_samples}
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for tool, by_cls in sorted(table.items()):
        for cls, entry in sorted(by_cls.items()):
            sc = entry["scores"]
            order = sorted((p for p, s in sc.items() if s["ranked"]), key=lambda p: (-sc[p]["score"], -sc[p]["n"], p))
            if len(order) >= 2:
                out.setdefault(tool, {})[cls] = {"order": order, "scores": dict(sorted(sc.items()))}
    return out


def rules_hash(rules: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(rules, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _orders(rules: Dict[str, Any]) -> Dict[str, Dict[str, List[str]]]:
    return {t: {c: list(e.get("order") or []) for c, e in (cl or {}).items()} for t, cl in (rules or {}).items()}


def diff(old: Dict[str, Any], new: Dict[str, Any]) -> List[Dict[str, Any]]:
    """What approving ``new`` changes against ``old``: one row per (tool, class) whose order differs."""
    a, b = _orders(old), _orders(new)
    rows = []
    for tool in sorted(set(a) | set(b)):
        for cls in sorted(set(a.get(tool, {})) | set(b.get(tool, {}))):
            x, y = a.get(tool, {}).get(cls), b.get(tool, {}).get(cls)
            if x != y:
                rows.append({"tool": tool, "class": cls, "before": x, "after": y,
                             "change": "added" if x is None else ("removed" if y is None else "changed")})
    return rows


# ── proposals, approved versions, the active pointer ─────────────

class RoutingError(ValueError):
    def __init__(self, message: str, status: int = 400, **extra: Any):
        super().__init__(message)
        self.status = status
        self.extra = extra


def _write_json(path: Path, doc: Any, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=2, sort_keys=False, default=str)
    if exclusive:                                       # a version number is taken once, by one writer
        with open(path, "x", encoding="utf-8") as f:
            f.write(text)
        return
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class RoutingStore:
    """Files under ``ai.planners.learning.dir``: ``proposals/<id>.json`` (reviewable, with the
    evidence and a diff), ``versions/<n>.json`` (approved, never changed) and ``active.json`` (the
    version in effect and the history of approvals and rollbacks). Every worker re-reads
    ``active.json`` when it changes, so a shared directory serves several workers."""

    def __init__(self, directory: Optional[str] = None, reload_interval_s: Optional[float] = None):
        st = _settings()
        self.dir = Path(directory or st.dir)
        self.reload_interval_s = st.reload_interval_s if reload_interval_s is None else reload_interval_s
        self._lock = threading.Lock()
        self._cache: Optional[Tuple[float, Any, int, Dict[str, Any]]] = None    # (checked, mtime, version, rules)

    # files
    def _proposal_path(self, pid: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", pid or ""):
            raise RoutingError(f"no proposal {pid!r}", 404)
        return self.dir / "proposals" / f"{pid}.json"

    def _version_path(self, n: int) -> Path:
        return self.dir / "versions" / f"{int(n)}.json"

    # active rules (read on every automatic choice; cached, re-read when the file changes)
    def active(self) -> Tuple[int, Dict[str, Any]]:
        now = time.time()
        c = self._cache
        if c is not None and now - c[0] < self.reload_interval_s:
            return c[2], c[3]
        path = self.dir / "active.json"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
        if c is not None and c[1] == mtime:
            self._cache = (now, mtime, c[2], c[3])
            return c[2], c[3]
        doc = _read_json(path) if mtime is not None else None
        n = int((doc or {}).get("version") or 0)
        rules = ((_read_json(self._version_path(n)) or {}).get("rules") or {}) if n else {}
        self._cache = (now, mtime, n, rules)
        return n, rules

    def order_for(self, tool: str, cls: str) -> Optional[List[str]]:
        _, rules = self.active()
        by_cls = rules.get(tool or "ask") or {}
        entry = by_cls.get(cls) or by_cls.get(ANY)
        return list(entry.get("order") or []) if entry else None

    def _active_doc(self) -> Dict[str, Any]:
        return _read_json(self.dir / "active.json") or {"version": 0, "history": []}

    # proposals
    def propose(self, rules: Dict[str, Any], *, evidence: Dict[str, Any], settings: Dict[str, Any],
                created_by: str = "", source: str = "cli") -> Dict[str, Any]:
        _, current = self.active_fresh()
        pid = datetime.now(timezone.utc).strftime("p%Y%m%d%H%M%S-") + uuid.uuid4().hex[:6]
        doc = {"id": pid, "status": "proposed", "created_at": time.time(), "created_by": created_by or "",
               "source": source, "settings": settings, "evidence": evidence, "rules": rules,
               "hash": rules_hash(rules), "diff": diff(current, rules)}
        _write_json(self._proposal_path(pid), doc)
        return doc

    def proposal(self, pid: str) -> Dict[str, Any]:
        doc = _read_json(self._proposal_path(pid))
        if not isinstance(doc, dict):
            raise RoutingError(f"no proposal {pid!r}", 404)
        return doc

    def proposals(self, limit: int = 50) -> List[Dict[str, Any]]:
        files = sorted((self.dir / "proposals").glob("*.json"), reverse=True)[:max(1, limit)]
        return [d for d in (_read_json(f) for f in files) if isinstance(d, dict)]

    def reject(self, pid: str, user: str, reason: str = "") -> Dict[str, Any]:
        with self._lock:
            doc = self.proposal(pid)
            if doc.get("status") != "proposed":
                raise RoutingError(f"proposal {pid} is {doc.get('status')}, not proposed", 409)
            doc.update(status="rejected", decided_by=user, decided_at=time.time(), reason=str(reason or "")[:500])
            _write_json(self._proposal_path(pid), doc)
        return doc

    def approve(self, pid: str, hash_: str, user: str, note: str = "") -> Dict[str, Any]:
        """Make the proposal's rules a new version and activate it. ``hash_`` must be the hash the
        reviewer saw; a proposal that is not ``proposed`` or has no rules is refused."""
        with self._lock:
            doc = self.proposal(pid)
            if doc.get("status") != "proposed":
                raise RoutingError(f"proposal {pid} is {doc.get('status')}, not proposed", 409)
            if not hash_ or hash_ != doc.get("hash") or rules_hash(doc.get("rules") or {}) != doc.get("hash"):
                raise RoutingError("the hash is not the proposal's: review it again", 409)
            if not doc.get("rules"):
                raise RoutingError("the proposal has no rules (not enough evidence)", 409)
            for _ in range(20):
                n = 1 + max([int(p.stem) for p in (self.dir / "versions").glob("*.json") if p.stem.isdigit()] or [0])
                try:
                    _write_json(self._version_path(n), {
                        "version": n, "rules": doc["rules"], "hash": doc["hash"], "proposal": pid,
                        "approved_by": user, "approved_at": time.time(), "note": str(note or "")[:500]},
                        exclusive=True)
                    break
                except FileExistsError:
                    continue
            else:
                raise RoutingError("could not take a version number", 503)
            doc.update(status="approved", decided_by=user, decided_at=time.time(), version=n)
            _write_json(self._proposal_path(pid), doc)
            self._activate(n, user, "approve", f"proposal {pid}")
        return doc

    # versions and rollback
    def versions(self) -> List[Dict[str, Any]]:
        files = sorted((p for p in (self.dir / "versions").glob("*.json") if p.stem.isdigit()),
                       key=lambda p: -int(p.stem))
        return [d for d in (_read_json(f) for f in files) if isinstance(d, dict)]

    def history(self) -> List[Dict[str, Any]]:
        return list(reversed(self._active_doc().get("history") or []))

    def activate(self, n: int, user: str, reason: str = "") -> Dict[str, Any]:
        """Make version ``n`` active again (a rollback or roll-forward); 0 turns the rules off."""
        with self._lock:
            n = int(n)
            if n and not self._version_path(n).exists():
                raise RoutingError(f"no version {n}", 404)
            return self._activate(n, user, "rollback" if n else "off", reason)

    def _activate(self, n: int, user: str, action: str, reason: str) -> Dict[str, Any]:
        doc = self._active_doc()
        hist = list(doc.get("history") or [])
        hist.append({"version": n, "from": int(doc.get("version") or 0), "action": action, "by": user,
                     "at": time.time(), "reason": str(reason or "")[:500]})
        doc = {"version": n, "history": hist[-200:]}
        _write_json(self.dir / "active.json", doc)
        self._cache = None
        return doc

    def active_fresh(self) -> Tuple[int, Dict[str, Any]]:
        self._cache = None
        return self.active()


_store: Optional[RoutingStore] = None
_store_installed = False
_store_lock = threading.Lock()


def get_store() -> RoutingStore:
    global _store
    with _store_lock:
        if _store is None or (not _store_installed and str(_store.dir) != str(Path(_settings().dir))):
            _store = RoutingStore()
        return _store


def set_store(s: Optional[RoutingStore]) -> None:
    """Install a store (tests); None builds one from the settings on next use."""
    global _store, _store_installed
    _store, _store_installed = s, s is not None


# ── the offline job ──────────────────────────────────────────────

def learn(*, created_by: str = "", source: str = "cli", write: bool = True, store: Optional[RoutingStore] = None,
          eval_store: Any = None, audit_rows: Optional[Iterable[str]] = None,
          sets: Optional[Dict[str, Any]] = None, settings: Any = None) -> Dict[str, Any]:
    """Rank planners from the evidence and write a proposal (``write``); returns it. Nothing takes
    effect until a person approves the proposal."""
    st = settings or _settings()
    since = time.time() - float(st.window_days) * 86400
    evals: List[Outcome] = []
    try:
        evals = eval_outcomes(since, st.max_eval_runs, store=eval_store, sets=sets)
    except Exception as e:
        logger.warning(f"planner learning: eval runs unavailable: {e}")
    runs = run_outcomes(since, st.max_records, rows=audit_rows)
    rules = rank(evals + runs, st.min_samples, st.cost_weight, st.latency_weight)
    evidence = {"eval_outcomes": len(evals), "run_outcomes": len(runs), "since": since,
                "tools": sorted({o.tool for o in evals + runs})}
    used = {k: getattr(st, k) for k in ("min_samples", "cost_weight", "latency_weight", "window_days")}
    if not write:
        return {"status": "dry run", "rules": rules, "hash": rules_hash(rules), "evidence": evidence,
                "settings": used}
    s = store or get_store()
    doc = s.propose(rules, evidence=evidence, settings=used, created_by=created_by, source=source)
    _audit("planners.routing.propose", created_by, doc["id"],
           {"hash": doc["hash"], "evidence": evidence, "changes": len(doc["diff"])})
    return doc


def _audit(action: str, user: str, resource: str, details: Dict[str, Any]) -> None:
    try:
        from sajha.core.audit import AuditLogger
        AuditLogger().log(action, user_id=user or None, resource_type="planner_routing", resource_id=resource,
                          details=json.dumps(details, default=str)[:4000])
    except Exception as e:
        logger.debug(f"planner routing audit failed: {e}")


def policy_gate(pid: str, user: Any) -> Optional[Dict[str, Any]]:
    """The policy engine's say on approving a proposal (pseudo tool ``planners.routing.approve``,
    arguments ``{"proposal": <id>}``): ``deny`` refuses; ``require_approval`` asks another
    administrator on the Approvals page and consumes the grant when approving again."""
    from sajha.policy import approvals
    from sajha.policy.engine import Call, enabled as policy_enabled, get_engine
    if not policy_enabled():
        return None
    from sajha.observability.caller import Caller
    caller = Caller(str(getattr(user, "user_id", "") or "anonymous"), "", tuple(getattr(user, "roles", None) or ()),
                    str(getattr(user, "auth_type", "") or "session"))
    args = {"proposal": pid}
    d = get_engine().evaluate(Call(APPROVE_ACTION, args, caller, "rest"))
    if d.effect == "deny":
        raise RoutingError(f"the policy engine refuses this approval: {d.reason}", 403, rule=d.rule)
    if d.effect == "require_approval":
        grant = approvals.consume_grant(APPROVE_ACTION, args, caller)
        if grant is not None:
            return grant
        rec = approvals.request(tool=APPROVE_ACTION, arguments=args, caller=caller, source="rest", rule=d.rule,
                                reason=d.reason, ttl=getattr(d.approval_rule, "approval_ttl", None))
        raise RoutingError(f"policy rule {d.rule} requires a second approval: an administrator other than you must "
                           f"approve request {rec['id']} on the Approvals page, then approve again.", 409,
                           approval_id=rec["id"], rule=d.rule)
    return None


def approve(pid: str, hash_: str, user: Any, note: str = "", store: Optional[RoutingStore] = None) -> Dict[str, Any]:
    grant = policy_gate(pid, user)
    uid = str(getattr(user, "user_id", "") or user or "")
    doc = (store or get_store()).approve(pid, hash_, uid, note)
    _audit("planners.routing.approve", uid, pid, {"hash": hash_, "version": doc.get("version"),
                                                  "approval": (grant or {}).get("id")})
    return doc


def reject(pid: str, user: str, reason: str = "", store: Optional[RoutingStore] = None) -> Dict[str, Any]:
    doc = (store or get_store()).reject(pid, user, reason)
    _audit("planners.routing.reject", user, pid, {"reason": reason})
    return doc


def activate(n: int, user: str, reason: str = "", store: Optional[RoutingStore] = None) -> Dict[str, Any]:
    doc = (store or get_store()).activate(n, user, reason)
    _audit("planners.routing.activate", user, str(n), {"reason": reason})
    return doc


# ── the online bandit ────────────────────────────────────────────

K = "planners.learn."


def _state():
    from sajha.core.state import get_state_store
    return get_state_store()


class Bandit:
    """Per (tool, class, planner) arms in the state store: ``n`` outcomes and ``r`` summed reward
    (0..1). ``choose`` exploits the best arm with ``bandit_min_samples`` outcomes and, on at most
    ``bandit_exploration`` of the choices in ``bandit_window_s`` seconds, explores with Thompson
    sampling or UCB1. It only ever picks from the labels it is given."""

    def __init__(self, settings: Any = None, store: Any = None, rng: Optional[random.Random] = None):
        self.st = settings or _settings()
        self._store = store
        self.rng = rng or random.Random(self.st.bandit_seed)
        self._lock = threading.Lock()

    @property
    def store(self):
        return self._store if self._store is not None else _state()

    # switches
    def killed(self) -> Optional[Dict[str, Any]]:
        try:
            v = self.store.get(K + "kill")
        except Exception:
            return None
        return v if isinstance(v, dict) else None

    def kill(self, by: str, reason: str = "") -> Dict[str, Any]:
        rec = {"by": by or "system", "at": time.time(), "reason": str(reason or "")[:300]}
        self.store.set(K + "kill", rec)
        _audit("planners.routing.bandit_stop", by, "bandit", rec)
        return rec

    def resume(self, by: str) -> None:
        self.store.delete(K + "kill")
        _audit("planners.routing.bandit_resume", by, "bandit", {})

    def active(self, tool: str) -> bool:
        if not self.st.bandit:
            return False
        tools = list(self.st.bandit_tools or [])
        if tools and not any(fnmatch.fnmatchcase(tool or "ask", p) for p in tools):
            return False
        return self.killed() is None

    # arms
    def _key(self, tool: str, cls: str, planner: str) -> str:
        return f"{K}arm:{tool or 'ask'}|{cls}|{_base(planner)}"

    def arm(self, tool: str, cls: str, planner: str) -> Dict[str, float]:
        v = self.store.get(self._key(tool, cls, planner))
        return {"n": float((v or {}).get("n") or 0), "r": float((v or {}).get("r") or 0)}

    def arms(self) -> List[Dict[str, Any]]:
        out = []
        for key, v in self.store.scan(K + "arm:"):
            tail = key.split(K + "arm:", 1)[-1]
            parts = tail.split("|")
            if len(parts) == 3 and isinstance(v, dict):
                n = float(v.get("n") or 0)
                out.append({"tool": parts[0], "class": parts[1], "planner": parts[2], "n": int(n),
                            "mean": round(float(v.get("r") or 0) / n, 4) if n else None})
        return sorted(out, key=lambda a: (a["tool"], a["class"], -(a["mean"] or 0), a["planner"]))

    def reset(self, by: str = "") -> int:
        n = self.store.delete_prefix(K + "arm:")
        _audit("planners.routing.bandit_reset", by, "bandit", {"arms": n})
        return n

    # choosing
    def _sample(self, labels: List[str], stats: Dict[str, Dict[str, float]]) -> str:
        if self.st.bandit_algorithm == "ucb":
            for lab in labels:
                if stats[lab]["n"] == 0:
                    return lab
            total = sum(stats[lab]["n"] for lab in labels)
            return max(labels, key=lambda lab: stats[lab]["r"] / stats[lab]["n"]
                       + math.sqrt(2 * math.log(total) / stats[lab]["n"]))
        draws = {lab: self.rng.betavariate(1 + stats[lab]["r"], 1 + max(0.0, stats[lab]["n"] - stats[lab]["r"]))
                 for lab in labels}
        return max(labels, key=lambda lab: draws[lab])

    def _explore_allowed(self, tool: str) -> bool:
        """At most ``bandit_exploration`` of this tool's bandit choices in the window explore."""
        w = float(self.st.bandit_window_s)
        n = self.store.window_count(f"{K}n:{tool}", w)
        x = self.store.window_count(f"{K}x:{tool}", w)
        return (x + 1) <= float(self.st.bandit_exploration) * n

    def choose(self, tool: str, cls: str, labels: List[str], baseline: Optional[str]) -> Optional[Tuple[str, str, str]]:
        """(label, by, reason), or None to leave the choice to the baseline (approved rules, the model)."""
        if len(labels) < 2:
            return None
        tool = tool or "ask"
        with self._lock:
            stats = {lab: self.arm(tool, cls, lab) for lab in labels}
            self.store.window_add(f"{K}n:{tool}", float(self.st.bandit_window_s))
            roll = self.rng.random()
            minimum = max(1, int(self.st.bandit_min_samples))
            evidenced = [lab for lab in labels if stats[lab]["n"] >= minimum]
            exploit = max(evidenced, key=lambda lab: (stats[lab]["r"] / stats[lab]["n"], -labels.index(lab))) \
                if evidenced else None
            if roll < float(self.st.bandit_exploration) and self._explore_allowed(tool):
                pick = self._sample(labels, stats)
                if pick != (exploit or baseline):
                    self.store.window_add(f"{K}x:{tool}", float(self.st.bandit_window_s))
                    return pick, "explore", f"{self.st.bandit_algorithm} exploration"
        if exploit is not None:
            s = stats[exploit]
            return exploit, "bandit", f"best mean reward {s['r'] / s['n']:.2f} over {int(s['n'])}"
        return None

    def update(self, tool: str, cls: str, planner: str, reward: float, explored: bool) -> None:
        tool = tool or "ask"
        reward = min(1.0, max(0.0, float(reward)))

        def bump(cur):
            cur = dict(cur or {})
            cur["n"] = float(cur.get("n") or 0) + 1
            cur["r"] = float(cur.get("r") or 0) + reward
            return cur
        self.store.update(self._key(tool, cls, planner), bump)
        if explored:
            w = float(self.st.bandit_window_s)
            _, runs = self.store.window_add(f"{K}xo:{tool}", w)
            ok = self.store.window_add(f"{K}xs:{tool}", w)[1] if reward >= 0.5 else \
                self.store.window_count(f"{K}xs:{tool}", w)
            if runs >= int(self.st.bandit_guard_min_runs) and ok / runs < float(self.st.bandit_guard_min_success):
                if self.killed() is None:
                    logger.warning(f"planner bandit stopped by its guard: {tool} explored choices succeeded "
                                   f"{ok}/{runs}")
                    self.kill("guard", f"{tool}: explored choices succeeded {ok} of {runs} in the window")


_bandit: Optional[Bandit] = None


def get_bandit(settings: Any = None) -> Bandit:
    global _bandit
    st = settings or _settings()
    if _bandit is None or _bandit.st is not st:
        _bandit = Bandit(st)
    return _bandit


def set_bandit(b: Optional[Bandit]) -> None:
    """Install a bandit (tests); None builds one from the settings on next use."""
    global _bandit
    _bandit = b


# ── the stage hooks (classify with menu: planners; the end of the run) ──

def select(registry: Any, tool: str, question: str, labels: List[str]) -> Tuple[str, Optional[Dict[str, Any]]]:
    """For a ``classify`` stage with ``menu: planners``, after its filters and its rules: the
    question's class and, when learning decides, ``{label, by, reason}``. ``labels`` are already
    only the planners this caller may run, so nothing here can widen the choice."""
    st = _settings(registry)
    cls = question_class(question)
    if len(labels) < 2:
        return cls, None
    learned = None
    if st.rules:
        try:
            order = get_store().order_for(tool or "ask", cls)
        except Exception as e:
            logger.debug(f"planner routing rules unavailable: {e}")
            order = None
        allowed = {_base(lab): lab for lab in labels}
        learned = next((allowed[_base(p)] for p in order or [] if _base(p) in allowed), None)
    b = get_bandit(st)
    try:
        if b.active(tool or "ask"):
            got = b.choose(tool or "ask", cls, labels, learned)
            if got is not None:
                return cls, {"label": got[0], "by": got[1], "reason": got[2]}
    except Exception as e:
        logger.warning(f"planner bandit skipped: {e}")
    if learned is not None:
        return cls, {"label": learned, "by": "learned", "reason": f"approved routing rules ({cls})"}
    return cls, None


def finish(choice: Dict[str, Any], subruns: List[Dict[str, Any]], stopped_by: Optional[str], cost_usd: float,
           latency_ms: float, registry: Any = None, record: bool = True) -> Dict[str, Any]:
    """The ``planner_choice`` audit field: the choice and, when the run has ended, its outcome. The
    choice *held* when its planner answered, nothing escalated after it, and the run ended by
    ``answer``. The reward is 1 for a choice that held, 0 otherwise, less the cost and latency weights."""
    rec = {k: choice.get(k) for k in ("tool", "class", "candidates", "chosen", "by", "reason")}
    rec["reason"] = str(rec.get("reason") or "")[:200]
    if stopped_by in ("needs_input", "needs_confirmation", "needs_connection"):
        rec["outcome"] = None                           # paused: judged by nobody
        return rec
    subs = [s for s in subruns if s.get("frame") == choice.get("frame")]
    first = subs[0] if subs else None
    held = bool(first and _base(first.get("planner")) == _base(choice.get("chosen")) and first.get("outcome") == "answered"
                and not first.get("stopped_by") and len(subs) == 1 and stopped_by == "answer")
    st = _settings(registry)
    reward = (1.0 if held else 0.0) - st.cost_weight * float(cost_usd or 0) - st.latency_weight * float(latency_ms or 0) / 1000
    rec["outcome"] = {"success": held, "reward": round(min(1.0, max(0.0, reward)), 4), "escalated": len(subs) > 1,
                      "stopped_by": stopped_by or "stopped", "cost_usd": round(float(cost_usd or 0), 6),
                      "latency_ms": int(latency_ms or 0)}
    if record:
        try:
            b = get_bandit(st)
            if b.active(rec["tool"] or "ask"):
                b.update(rec["tool"], rec["class"], rec["chosen"], rec["outcome"]["reward"], rec["by"] == "explore")
                rec["bandit"] = True
        except Exception as e:
            logger.warning(f"planner bandit not updated: {e}")
    return rec


def status(store: Optional[RoutingStore] = None) -> Dict[str, Any]:
    """For the page and the API: the settings, the active version, versions, proposals and the bandit."""
    st = _settings()
    s = store or get_store()
    n, rules = s.active_fresh()
    b = get_bandit(st)
    try:
        arms, killed = b.arms(), b.killed()
    except Exception as e:
        arms, killed = [], None
        logger.debug(f"planner bandit state unavailable: {e}")
    return {"settings": st.model_dump(), "dir": str(s.dir), "active": n, "rules": rules,
            "versions": s.versions(), "history": s.history(), "proposals": s.proposals(),
            "bandit": {"enabled": bool(st.bandit), "killed": killed, "arms": arms[:500],
                       "algorithm": st.bandit_algorithm, "exploration": st.bandit_exploration,
                       "tools": list(st.bandit_tools or [])}}


__all__ = ["CLASSES", "Outcome", "RoutingError", "RoutingStore", "Bandit", "question_class", "eval_outcomes",
           "run_outcomes", "extract_choice", "rank", "diff", "rules_hash", "learn", "approve", "reject", "activate",
           "select", "finish", "status", "get_store", "set_store", "get_bandit", "set_bandit", "policy_gate"]
