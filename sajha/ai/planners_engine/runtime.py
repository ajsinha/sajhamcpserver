"""
SAJHA MCP Server — the planner graph runtime.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Reference: docs/architecture/Planner Reference.md §5 (state), §7 (transitions), §10 (how a
planner runs) and §11 (limits).

A :class:`GraphPlanner` is an ordinary ``sajha.ai.planners.Planner``: the service
(``IntelligenceService``) keeps every guarantee it has today — the access-filtered shortlist,
refusing tools that were not offered, confirmation, running calls as the caller, result caps,
limits, budgets, synthesis, confidence, audit and the event stream. The graph only proposes.
Internally a run is a Python generator: stages that need tool calls *yield* a ``CallTools`` and
are resumed when the service has run them, so a graph of any shape is driven by the service's
existing step loop. Model calls go through ``PlanState.chat`` (the gateway bound to the caller)
as canonical Chat Completions requests.
"""

from __future__ import annotations

import copy
import json
import logging
import time
import uuid
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

from sajha.ai.llm.canonical import ChatCompletion, ChatMessage, ToolCall
from sajha.ai.planners import Answer, CallTools, PlanState, Planner, call_args
from sajha.ai.planners_engine import expr as E
from sajha.ai.planners_engine.model import BUILTIN_SLOTS, PlannerDef, Stage, Transition, slot_accepts

logger = logging.getLogger(__name__)

NO_REBIND = object()
MAX_ASKS = 3
MAX_CAVEATS = 20
RESUME_KEY = "sajha_planner"            # the MRTR inputRequests key of an ask_user stage
RESUME_STATE = "sajha_planner_resume"   # the MRTR state key holding the snapshot id


class RunStop(Exception):
    """Ends the whole run with ``stopped_by = reason``."""

    def __init__(self, reason: str, message: str = "", code: str = "", input_request: Optional[Dict] = None):
        super().__init__(message or reason)
        self.reason, self.message, self.code, self.input_request = reason, message, code, input_request


class SubStop(Exception):
    """Ends one sub-run (its sub-budget ran out): the ``planner`` stage's outcome is ``stopped``."""

    def __init__(self, reason: str, frame: "Frame"):
        super().__init__(reason)
        self.reason, self.frame = reason, frame


# ── a (sub-)run ──────────────────────────────────────────────────

class Frame:
    """One run or sub-run of one planner: its graph position, private slots and edge counters."""

    def __init__(self, pdef: PlannerDef, slots: Dict[str, Any], transcript: List[ChatMessage], depth: int = 0,
                 parent: Optional["Frame"] = None, chain: Optional[List[str]] = None, rebind: Any = NO_REBIND,
                 forked: bool = False):
        self.pdef = pdef
        self.slots = slots
        self.transcript = transcript
        self.depth = depth
        self.parent = parent
        self.chain = chain or [pdef.name]
        self.rebind = rebind
        self.forked = forked
        self.custom: Dict[str, Any] = {k: copy.deepcopy(d.get("default")) for k, d in (pdef.state or {}).items()}
        self.edges: Dict[str, int] = {}
        self.visits: Dict[str, int] = {}
        self.stages_run = 0
        self.last: Dict[str, Any] = {"stage": None, "type": None, "outcome": None}
        self.caps: Dict[str, float] = {}       # sub-budget: absolute caps on the run counters
        self.stage_cap: Optional[int] = None
        self.stage_base = 0
        self.extra: Dict[str, Any] = {}        # foreach item name -> value

    def model_for(self, role: str, rc: "RunCtx") -> Optional[str]:
        if rc.force_model:
            return rc.force_model
        if self.rebind is not NO_REBIND:
            return self.rebind
        role = role or "default"
        alias = (self.pdef.models or {}).get(role)
        return alias or None


class RunCtx:
    """What every frame of one run shares: the service's PlanState, counters, the path and events."""

    def __init__(self, planner: "GraphPlanner", state: PlanState):
        self.planner = planner
        self.state = state
        self.registry = planner.registry
        self.ps = planner.registry.settings
        self.ceil = self.ps.ceilings()
        self.overlays: Dict[str, Dict[str, Any]] = dict(planner.overlays or {})
        self.tool = planner.tool
        self.choices = list(planner.choices or [])
        self.input = dict(planner.input or {})
        self.force_model = planner.force_model
        self.t0 = time.time()
        self.deadline = self.t0 + max(0.1, float(state.remaining.seconds))
        self.steps = 0
        self.tool_calls = 0
        self.stages_run = 0
        self.model_calls = 0
        self.cost_usd = 0.0
        self.tokens = 0
        self.max_stages = min(int(planner.pdef.limits.get("max_stages_run") or self.ceil.max_stages_run),
                              self.ceil.max_stages_run)
        self.path: List[str] = []            # every stage run, sub-runs as "<planner>/<stage>"
        self.top_path: List[str] = []
        self.loops_exhausted: List[str] = []
        self.asks = 0
        self.seen_ids: set = set()
        self.chain: List[str] = [planner.pdef.name]
        self.resume: Optional[Dict[str, Any]] = None
        self.top: Optional[Frame] = None

    # events and metrics
    def emit(self, type_: str, **kw) -> None:
        try:
            self.state.emit({"type": type_, **kw})
        except Exception as e:
            logger.debug(f"planner event {type_}: {e}")

    def max_output_tokens(self, cfg: Dict[str, Any]) -> Optional[int]:
        v = cfg.get("max_output_tokens") or self.planner.pdef.limits.get("max_output_tokens")
        c = self.ceil.max_output_tokens
        return min(int(v), c) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def check(self, frame: Frame) -> None:
        """Run-wide and sub-budget limits, before a stage and before a step."""
        if time.time() > self.deadline:
            raise RunStop("timeout")
        if self.stages_run >= self.max_stages:
            raise RunStop("stage_limit")
        cap = self.planner.pdef.limits.get("max_cost_usd")
        if isinstance(cap, (int, float)) and self.cost_usd >= cap:
            raise RunStop("cost_limit")
        f = frame
        while f is not None:
            if f.caps or f.stage_cap is not None:
                reason = self._exceeded(f)
                if reason:
                    if f.parent is None:
                        raise RunStop(reason)
                    raise SubStop(reason, f)
            f = f.parent

    def _exceeded(self, f: Frame) -> Optional[str]:
        caps = f.caps
        if "steps" in caps and self.steps >= caps["steps"]:
            return "step_limit"
        if "tool_calls" in caps and self.tool_calls >= caps["tool_calls"]:
            return "tool_limit"
        if "deadline" in caps and time.time() >= caps["deadline"]:
            return "timeout"
        if "cost" in caps and self.cost_usd >= caps["cost"]:
            return "cost_limit"
        if f.stage_cap is not None and self.stages_run - f.stage_base >= f.stage_cap:
            return "stage_limit"
        return None

    # slots as expressions and templates see them
    def lookup(self, frame: Frame) -> Callable[[str], Any]:
        def get(root: str) -> Any:
            if root in frame.extra:
                return frame.extra[root]
            if root in frame.custom:
                return frame.custom[root]
            if root == "settings":
                return frame.pdef.settings
            if root == "input":
                return self.input
            if root == "confidence":
                return provisional_confidence(self.state.steps)
            if root == "counters":
                return {"stages_run": self.stages_run, "steps": self.steps, "tool_calls": self.tool_calls,
                        "tokens": self.tokens, "cost_usd": self.cost_usd, "elapsed_s": time.time() - self.t0,
                        "model_calls": self.model_calls}
            if root == "remaining":
                return {"steps": max(0, int(self.state.remaining.steps) - self.steps),
                        "tool_calls": max(0, int(self.state.remaining.tool_calls) - self.tool_calls),
                        "tokens": self.state.remaining.tokens, "cost_usd": None,
                        "seconds": max(0.0, self.deadline - time.time()),
                        "stages": max(0, self.max_stages - self.stages_run)}
            if root == "planner":
                return {"name": frame.pdef.name, "version": frame.pdef.version, "chain": ">".join(frame.chain),
                        "path": self.path[-200:]}
            if root == "last":
                return frame.last
            if root == "shortlist":
                return [{"name": e.name, "description": (e.description or "")[:300], "score": e.score}
                        for e in self.state.shortlist]
            return frame.slots.get(root)
        return get

    def env(self, frame: Frame) -> E.Env:
        get = self.lookup(frame)

        def whole():
            out = {k: get(k) for k in BUILTIN_SLOTS}
            out.update(frame.custom)
            out.update(frame.extra)
            return out
        return E.Env(get, whole, visits=lambda s: frame.visits.get(s, 0),
                     offered=lambda t: t in self.state.offered)

    def truth(self, frame: Frame, ex: E.Expression, stage: str) -> bool:
        try:
            return E.evaluate_bool(ex, self.env(frame))
        except Exception as e:
            self.expression_error(frame, stage, ex.text, str(e))
            return False

    def expression_error(self, frame: Frame, stage: str, text: str, message: str) -> None:
        self.emit("expression_error", stage=stage, expression=text, message=message[:300])
        from sajha.ai.planners_engine import metrics
        metrics.expression_error(frame.pdef.name)

    # caveats
    def caveat(self, frame: Frame, text: str) -> None:
        cav = frame.slots.setdefault("caveats", [])
        text = str(text)[:300]
        if text not in cav and len(cav) < MAX_CAVEATS:
            cav.append(text)


def provisional_confidence(steps: List[Any]) -> float:
    """Today's composition-framework confidence over the results so far (0.5 with no results)."""
    if not steps:
        return 0.5
    ok = [s for s in steps if getattr(s, "ok", False)]
    if not ok:
        return 0.0
    try:
        from sajha.core.composition import EntropyGuard
        guard = EntropyGuard()
        for s in ok:
            guard.record_step(s.name, s.confidence)
        for s in steps:
            if not s.ok and s.status == "error":
                guard.record_step(f"{s.name}:failed", 0.9)
        return float(guard.cumulative_confidence)
    except Exception:
        return 0.5


def initial_slots(state: PlanState) -> Dict[str, Any]:
    hist = []
    n = state.history_turns * 2
    for m in state.messages[:n]:
        hist.append({"role": m.role, "content": m.text})
    return {"original_question": state.original_question or state.question, "question": state.question,
            "history": hist, "summary": str(state.data.get("summary") or ""), "results": [], "plan": [],
            "plan_revision": 0, "draft": "", "draft_json": None, "draft_source": "none", "citations": [],
            "caveats": [], "critique": None, "findings": [], "candidates": [], "vote": None, "chosen": None,
            "choice": None, "groups": {}, "rule": None, "matched": None, "items": [], "item": None,
            "outputs": [], "user_reply": None, "subrun": None}


# ── tool calls ───────────────────────────────────────────────────

def make_result(call: ToolCall, step: Any, msg: Optional[ChatMessage], stage: str, planner: str) -> Dict[str, Any]:
    from sajha.ai.planners import _content_data
    data = _content_data(msg) if msg is not None else None
    status = getattr(step, "status", "not_run") if step is not None else "not_run"
    ok = bool(getattr(step, "ok", False))
    return {"id": call.id, "tool": call.function.name, "arguments": call_args(call), "ok": ok, "status": status,
            "summary": getattr(step, "summary", "") if step is not None else "not run",
            "preview": (msg.text if msg is not None else "")[:4000],
            "data": data if isinstance(data, (dict, list)) else None, "spilled": False, "stage": stage,
            "planner": planner}


def unique_calls(rc: RunCtx, calls: List[ToolCall]) -> Tuple[List[ToolCall], bool]:
    """Calls with ids unique within the run (two forks may produce the same id)."""
    out, changed = [], False
    for c in calls:
        cid = c.id or "call"
        if cid in rc.seen_ids:
            k = 2
            while f"{cid}_{k}" in rc.seen_ids:
                k += 1
            c = ToolCall.of(f"{cid}_{k}", c.function.name, c.function.arguments)
            cid, changed = c.id, True
        rc.seen_ids.add(cid)
        out.append(c)
    return out, changed


def run_calls(rc: RunCtx, frame: Frame, calls: List[ToolCall], message: Optional[ChatMessage], parallel: bool,
              stage: str) -> Generator[Any, Any, List[Dict[str, Any]]]:
    """Ask the service to run ``calls`` (one step) and return the results as result records. In a
    fork, the calls of every fork of one round go to the service together (``run_forks``), which
    counts that round as one step."""
    rc.check(frame)
    calls, changed = unique_calls(rc, list(calls))
    if message is None or changed:
        message = ChatMessage.assistant(message.text if message is not None else None, calls)
    yield CallTools(calls, message, parallel=parallel and len(calls) > 1)
    return absorb(rc, frame, calls, message, stage, count=not frame.forked)


def absorb(rc: RunCtx, frame: Frame, calls: List[ToolCall], message: ChatMessage, stage: str,
           count: bool = True) -> List[Dict[str, Any]]:
    """After the service ran ``calls``: count them and record their results in the frame."""
    if count:
        rc.steps += 1
        rc.tool_calls += len(calls)
    by_id = rc.state.results()
    new = []
    msgs = []
    for c in calls:
        msg = by_id.get(c.id)
        new.append(make_result(c, rc.state.step(c.id), msg, stage, frame.pdef.name))
        if msg is not None:
            msgs.append(msg)
    if frame.transcript is not rc.state.messages:
        frame.transcript.append(message)
        frame.transcript.extend(msgs)
    frame.slots.setdefault("results", []).extend(new)
    return new


def run_forks(rc: RunCtx, owner: Frame, gens: List[Generator], concurrency: int) -> Generator[Any, Any, List[Any]]:
    """Drive several sub-run generators together: each round, every active one advances to its
    next tool round; their calls go to the service as one parallel step."""
    n = len(gens)
    results: List[Any] = [None] * n
    errors: List[Optional[BaseException]] = [None] * n
    queue = list(range(n))
    active: List[int] = []
    started = set()
    while queue or active:
        while queue and len(active) < max(1, concurrency):
            active.append(queue.pop(0))
        batch: List[Tuple[int, CallTools]] = []
        for i in list(active):
            try:
                act = gens[i].send(None) if i in started else next(gens[i])
                started.add(i)
                batch.append((i, act))
            except StopIteration as e:
                started.add(i)
                results[i] = e.value
                active.remove(i)
            except (SubStop, RunStop) as e:
                if isinstance(e, RunStop):
                    raise
                errors[i] = e
                active.remove(i)
            except Exception as e:
                if _is_fatal(e):
                    raise
                errors[i] = e
                active.remove(i)
        if not batch:
            continue
        calls = [c for _i, a in batch for c in a.calls]
        msg = ChatMessage.assistant(None, calls)
        yield CallTools(calls, msg, parallel=len(calls) > 1)
        if not owner.forked:                  # one round of every fork is one step
            rc.steps += 1
            rc.tool_calls += len(calls)
        # each fork records its own results when it resumes (absorb)
    return [(results[i], errors[i]) for i in range(n)]


def _is_fatal(e: BaseException) -> bool:
    try:
        from sajha.ai.llm.errors import BudgetExceeded
        from sajha.core.mcp_mrtr import InputRequired
        return isinstance(e, (BudgetExceeded, InputRequired))
    except Exception:
        return False


# ── the frame loop ───────────────────────────────────────────────

def stage_gen(rc: RunCtx, frame: Frame, st: Stage):
    """Run one stage; a stage type's ``run`` may be a generator (it asks for tool calls) or not."""
    import inspect
    r = st.impl.run(rc, frame, st)
    if inspect.isgenerator(r):
        return (yield from r)
    return r



def choose(rc: RunCtx, frame: Frame, st: Stage, outcome: str) -> Optional[Transition]:
    lst = st.outcomes.get(outcome)
    tried_star = False
    if lst is None:
        lst, tried_star = st.outcomes.get("*"), True
    for candidates in ([lst] if tried_star else [lst, st.outcomes.get("*")]):
        for t in candidates or []:
            if t.when is None or rc.truth(frame, t.when, st.id):
                return t
    return None


def take(rc: RunCtx, frame: Frame, st: Stage, t: Transition) -> str:
    if isinstance(t.max_visits, int):
        n = frame.edges.get(t.edge, 0)
        if n >= t.max_visits:
            rc.loops_exhausted.append(f"{frame.pdef.name}:{t.edge}")
            rc.emit("loop_exhausted", stage=st.id, edge=t.edge, to=t.on_exhausted, planner=frame.pdef.name)
            from sajha.ai.planners_engine import metrics
            metrics.loop_exhausted(frame.pdef.name, t.edge)
            return t.on_exhausted or t.next
        frame.edges[t.edge] = n + 1
    return t.next


def apply_sets(rc: RunCtx, frame: Frame, st: Stage) -> None:
    for slot, ex in st.sets:
        try:
            v = E.evaluate(ex, rc.env(frame))
        except Exception as e:
            rc.expression_error(frame, st.id, ex.text, str(e))
            continue
        decl = (frame.pdef.state or {}).get(slot) or {}
        if not slot_accepts(decl, v):
            rc.expression_error(frame, st.id, ex.text, f"value does not match slot {slot} ({decl.get('type')})")
            continue
        if decl.get("type") == "integer" and isinstance(v, float) and v.is_integer():
            v = int(v)
        frame.custom[slot] = bound_value(rc, frame, decl, v, slot)


def bound_value(rc: RunCtx, frame: Frame, decl: Dict[str, Any], v: Any, slot: str) -> Any:
    t = decl.get("type")
    if t == "string" and isinstance(v, str):
        lim = int(decl.get("max_chars") or 4000)
        if len(v) > lim:
            rc.caveat(frame, f"{slot} was clipped to {lim} characters")
            return v[:lim]
    if t == "array" and isinstance(v, list):
        lim = int(decl.get("max_items") or 100)
        if len(v) > lim:
            rc.caveat(frame, f"{slot} kept its first {lim} items")
            return v[:lim]
    return v


def write_slot(rc: RunCtx, frame: Frame, slot: str, value: Any) -> None:
    """Write ``into`` targets: a custom slot (type-checked, bounded) or a built-in one."""
    if slot in frame.custom or slot in (frame.pdef.state or {}):
        decl = (frame.pdef.state or {}).get(slot) or {}
        if slot_accepts(decl, value):
            frame.custom[slot] = bound_value(rc, frame, decl, value, slot)
        else:
            rc.caveat(frame, f"{slot}: the value did not match its type and was not stored")
    else:
        frame.slots[slot] = value


def run_frame(rc: RunCtx, frame: Frame) -> Generator[Any, Any, Tuple[str, Any]]:
    """Run ``frame``'s graph to a terminal stage: returns ("answered", stage) or ("failed", reason)."""
    from sajha.ai.planners_engine import metrics
    pdef = frame.pdef
    sid = frame.extra.pop("__resume_stage", None) or pdef.start
    while True:
        st = pdef.stages[sid]
        rc.check(frame)
        rc.stages_run += 1
        frame.stages_run += 1
        frame.visits[sid] = frame.visits.get(sid, 0) + 1
        qualified = sid if frame.depth == 0 and not frame.forked else f"{'>'.join(frame.chain)}/{sid}"
        rc.path.append(qualified)
        if frame.depth == 0 and not frame.forked:
            rc.top_path.append(sid)
        rc.emit("stage_start", stage=sid, stage_type=st.type, visit=frame.visits[sid], planner=pdef.name)
        t0 = time.time()
        if st.guard is not None and not rc.truth(frame, st.guard, sid):
            outcome = "else"
            rc.emit("stage_end", stage=sid, outcome="skipped", ms=0, planner=pdef.name)
            metrics.stage(pdef.name, sid, "skipped")
            frame.last = {"stage": sid, "type": st.type, "outcome": "skipped"}
            apply_sets(rc, frame, st)
            nxt = take(rc, frame, st, st.else_) if st.else_ is not None else None
            if nxt is None:
                raise RunStop("error", f"no transition for the guard of stage {sid}", code="no_transition")
            sid = nxt
            continue
        outcome = yield from stage_gen(rc, frame, st)
        ms = int((time.time() - t0) * 1000)
        rc.emit("stage_end", stage=sid, outcome=outcome, ms=ms, planner=pdef.name)
        metrics.stage(pdef.name, sid, str(outcome))
        frame.last = {"stage": sid, "type": st.type, "outcome": outcome}
        if st.impl.terminal:
            return ("answered", st) if outcome == "answered" else ("failed", outcome)
        apply_sets(rc, frame, st)
        t = choose(rc, frame, st, outcome)
        if t is None:
            raise RunStop("error", f"no transition for outcome {outcome} at stage {sid}", code="no_transition")
        sid = take(rc, frame, st, t)


# ── sub-runs ─────────────────────────────────────────────────────

def sub_frame(rc: RunCtx, parent: Frame, pdef: PlannerDef, *, fork: bool = False, question: Optional[str] = None,
              rebind_role: Optional[str] = None, limits: Optional[Dict[str, Any]] = None,
              extra: Optional[Dict[str, Any]] = None) -> Frame:
    if fork:
        slots = copy.deepcopy({k: v for k, v in parent.slots.items()})
        transcript = list(parent.transcript)
    else:
        slots = parent.slots
        transcript = parent.transcript
    if question is not None and question != parent.slots.get("question"):
        slots["question"] = question
        transcript.append(ChatMessage.user(question))
    rebind = parent.rebind
    if rebind_role:
        rebind = parent.model_for(rebind_role, rc)
    chain = parent.chain + [pdef.name] if pdef is not parent.pdef else list(parent.chain)
    f = Frame(pdef, slots, transcript, depth=parent.depth + (0 if pdef is parent.pdef else 1), parent=parent,
              chain=chain, rebind=rebind, forked=fork or parent.forked)
    if pdef is parent.pdef:
        f.custom = copy.deepcopy(parent.custom)
    if extra:
        f.extra.update(extra)
    if limits:
        f.caps = {}
        if limits.get("max_steps"):
            f.caps["steps"] = rc.steps + int(limits["max_steps"])
        if limits.get("max_tool_calls"):
            f.caps["tool_calls"] = rc.tool_calls + int(limits["max_tool_calls"])
        if limits.get("timeout_s"):
            f.caps["deadline"] = time.time() + float(limits["timeout_s"])
        if limits.get("max_cost_usd"):
            f.caps["cost"] = rc.cost_usd + float(limits["max_cost_usd"])
        if limits.get("max_stages_run"):
            f.stage_cap = int(limits["max_stages_run"])
            f.stage_base = rc.stages_run
    return f


def run_python_planner(rc: RunCtx, frame: Frame, pdef: PlannerDef, settings: Dict[str, Any]
                       ) -> Generator[Any, Any, Tuple[str, Any]]:
    """A ``kind: python`` planner as a sub-run: its CallTools go to the service; its Answer ends it."""
    from sajha.ai.planners import Emit
    cls = pdef.cls
    planner = cls(cls.config_model(**(settings or {})))
    planner.start(rc.state)
    while True:
        rc.check(frame)
        act = planner.next_action(rc.state)
        if isinstance(act, Emit):
            rc.state.emit(act.event)
            continue
        if isinstance(act, Answer):
            if act.message is not None:
                frame.transcript.append(act.message)
            frame.slots["draft"] = act.text or ""
            frame.slots["draft_source"] = "act" if act.synthesize else "subrun"
            return ("answered", None)
        yield from run_calls(rc, frame, list(act.calls), act.message, bool(act.parallel), pdef.name)


# ── the top level ────────────────────────────────────────────────

class GraphPlanner(Planner):
    """A planner file run by the stage library (Planner Reference §10)."""

    def __init__(self, pdef: PlannerDef, registry: Any, *, overlays: Optional[Dict[str, Any]] = None,
                 tool: str = "", choices: Optional[List[str]] = None, input: Optional[Dict[str, Any]] = None,
                 force_model: Optional[str] = None, by: str = "", output_schema: Optional[Dict[str, Any]] = None):
        super().__init__(None, factory=lambda n: registry.build(n))
        self.pdef = pdef
        self.name = pdef.name
        self.registry = registry
        self.overlays = overlays or {}
        self.tool = tool
        self.choices = choices
        self.input = input
        self.force_model = force_model
        self.by = by
        self.output_schema = output_schema
        self.chosen = [pdef.name]
        self.rc: Optional[RunCtx] = None
        self._gen = None
        self._started_at = time.time()

    @property
    def version(self) -> str:
        return self.pdef.version

    def start(self, state: PlanState) -> None:
        self.rc = RunCtx(self, state)
        self._started_at = time.time()
        state.data["plan"] = lambda: [dict(p) for p in (self.rc.top.slots.get("plan") or [])] if self.rc.top else []
        self._gen = self._main()

    def next_action(self, state: PlanState):
        try:
            act = next(self._gen)
        except StopIteration as e:
            act = e.value
        self.chosen = list(self.rc.chain)
        return act

    def _main(self):
        from sajha.ai.planners_engine import metrics
        rc = self.rc
        frame = Frame(self.pdef, initial_slots(rc.state), rc.state.messages, depth=0, chain=[self.pdef.name])
        rc.top = frame
        caps = {k: v for k, v in (self.pdef.limits or {}).items() if k in ("max_steps", "max_tool_calls",
                                                                             "timeout_s", "max_cost_usd")}
        if caps:
            tmp = sub_frame(rc, frame, self.pdef, limits=caps)
            frame.caps = tmp.caps
        from sajha.ai.planners_engine.stages import maybe_resume
        maybe_resume(rc, frame)
        try:
            end = yield from run_frame(rc, frame)
            ans = self._finish(frame, "answer", end[1] if end[0] == "answered" else None,
                               failed=None if end[0] == "answered" else end[1])
        except RunStop as e:
            if e.code:
                rc.emit("error", code=e.code, message=e.message[:300])
            ans = self._finish(frame, e.reason, None, error=e.message if e.code else "", input_request=e.input_request)
        except SubStop as e:                      # the top frame's own limits
            ans = self._finish(frame, e.reason, None)
        metrics.run_seconds(self.pdef.name, time.time() - self._started_at)
        return ans

    # how the run ends (§6.17, §6.18, §10.3)
    def _finish(self, frame: Frame, stopped_by: str, answer_stage: Optional[Stage], failed: Any = None,
                error: str = "", input_request: Optional[Dict[str, Any]] = None) -> Answer:
        rc = self.rc
        slots = frame.slots
        caveats = list(slots.get("caveats") or [])
        if failed is not None:
            reason = str(slots.get("_fail_reason") or failed or "the planner failed")
            for f in slots.get("findings") or []:
                caveats.append(str(f.get("message"))[:300])
            return Answer(reason, synthesize=False, stopped_by="failed", citations=[], caveats=caveats[:MAX_CAVEATS])
        mode = (answer_stage.cfg.get("synthesize") if answer_stage is not None else None) or "auto"
        text, synth, cites = self.final_text(frame, mode)
        if answer_stage is not None and answer_stage.cfg.get("caveats_from_findings", True):
            for f in slots.get("findings") or []:
                note = str(f.get("message"))[:300]
                if note not in caveats:
                    caveats.append(note)
        return Answer(text, synthesize=synth, stopped_by=stopped_by, citations=cites, caveats=caveats[:MAX_CAVEATS],
                      error=error, input_request=input_request)

    def final_text(self, frame: Optional[Frame] = None, mode: str = "auto") -> Tuple[str, bool, Optional[List[str]]]:
        """(text, synthesize, citations) for the best answer so far."""
        frame = frame or (self.rc.top if self.rc else None)
        if frame is None:
            return "", True, None
        slots = frame.slots
        ds = slots.get("draft_source") or "none"
        ok_ids = [r["id"] for r in slots.get("results") or [] if r.get("ok")]
        has_results = bool(slots.get("results"))
        if mode == "always":
            synth = True
        elif mode == "never":
            synth = False
        else:
            synth = has_results and ds in ("none", "act")
        text = str(slots.get("draft") or "")
        if not text and not synth:
            text = " ".join(r.get("summary") or "" for r in slots.get("results") or [] if r.get("ok")).strip()
        cites: Optional[List[str]] = None
        if ds in ("draft", "revise", "vote"):
            cites = [c for c in slots.get("citations") or [] if c in ok_ids] or ok_ids
        elif not synth and ds in ("template", "subrun"):
            cites = ok_ids
        return text, synth, cites

    def info(self) -> Dict[str, Any]:
        """For the service: the audit fields of this run."""
        rc = self.rc
        if rc is None:
            return {"planner_version": self.pdef.version}
        path = rc.path
        shown = path[:200] + (["…"] if len(path) > 200 else [])
        return {"planner_version": self.pdef.version, "planner_path": shown, "planner_top_path": rc.top_path[:200],
                "loops_exhausted": list(rc.loops_exhausted), "stages_run": rc.stages_run}

    def final_for(self, stopped_by: str) -> Optional[Tuple[str, bool, Optional[List[str]]]]:
        """When the service ended the run (step or tool limit, ...): the best answer so far (§10.3)."""
        if self.rc is None or self.rc.top is None:
            return None
        return self.final_text(self.rc.top, "auto")
