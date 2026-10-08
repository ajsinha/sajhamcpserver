"""
SAJHA MCP Server — planner files: loading, validation (P001–P071) and the compiled form.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Reference: docs/architecture/Planner Reference.md §2, §3, §5, §6, §7, §11, §12 and Appendix A.

``compile_planner(doc, ...)`` turns one planner document (plain ``yaml.safe_load`` output) into a
:class:`PlannerDef`, or raises :class:`PlannerError` carrying every error found. The JSON Schema
of Appendix A (``planner.schema.json``) checks the shape; the rules a schema cannot express
(reachability, bounded cycles, roles, references, expressions, ceilings) follow. Sub-planner
references (P033–P035, P071) are checked by the registry, which sees every file.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from sajha.ai.planners_engine import expr as E

IDENT = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
OUTCOME = re.compile(r"^([A-Za-z0-9_.@-]{1,64}|\*)$")
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$")
PLANNER_REF = re.compile(r"^([a-z][a-z0-9_]{0,63})(?:@([0-9][0-9A-Za-z.+-]*|latest))?$")
TOP_KEYS = ("name", "version", "kind", "class", "description", "use_when", "models", "prompts", "settings",
            "limits", "state", "start", "stages")
PYTHON_KEYS = ("name", "version", "kind", "class", "description", "use_when", "settings")

BUILTIN_SLOTS = ("input", "original_question", "question", "history", "summary", "shortlist", "results", "plan",
                 "plan_revision", "draft", "draft_json", "draft_source", "citations", "caveats", "critique",
                 "findings", "candidates", "vote", "chosen", "choice", "groups", "rule", "matched", "items", "item",
                 "outputs", "user_reply", "confidence", "subrun", "last", "counters", "remaining", "settings",
                 "planner")
READ_ONLY = {"input", "original_question", "history", "summary", "shortlist", "item", "confidence", "last",
             "counters", "remaining", "settings", "planner"}
SLOT_TYPES = ("string", "number", "integer", "boolean", "array", "object", "any")
MAX_STAGES = 100
# settings every planner accepts without declaring them: ``locality`` (any | local | net:<name>) restricts
# where the tools offered to it run (sajha/ai/locality.py; docs/architecture/SAJHA Net.md §13)
RESERVED_SETTINGS = ("locality",)
MAX_CUSTOM_SLOTS = 32
MAX_ALTERNATIVES = 10
MAX_RULES = 200


# ── diagnostics ──────────────────────────────────────────────────

@dataclass
class Diagnostic:
    code: str
    level: str                 # error | warning
    location: str
    message: str

    def render(self, who: str) -> str:
        loc = f"{self.location}: " if self.location else ""
        return f"planner {who}: {loc}{self.message}"

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "level": self.level, "location": self.location, "message": self.message}


class PlannerError(ValueError):
    """A planner file that does not validate: ``diagnostics`` holds every error (and warning)."""

    def __init__(self, who: str, diagnostics: List[Diagnostic]):
        self.who = who
        self.diagnostics = list(diagnostics)
        errs = [d for d in self.diagnostics if d.level == "error"] or self.diagnostics
        super().__init__("; ".join(f"{d.code} {d.render(who)}" for d in errs[:8]))

    @property
    def codes(self) -> List[str]:
        return [d.code for d in self.diagnostics if d.level == "error"]


# ── the compiled form ────────────────────────────────────────────

@dataclass
class Transition:
    next: str
    when: Optional[E.Expression] = None
    max_visits: Any = None            # None | int | "steps"
    on_exhausted: Optional[str] = None
    edge: str = ""                    # "<stage>:<outcome>[<pos>]" or "<stage>:else"


@dataclass
class Stage:
    id: str
    type: str
    cfg: Dict[str, Any]
    impl: Any                         # the StageType
    guard: Optional[E.Expression] = None
    else_: Optional[Transition] = None
    outcomes: Dict[str, List[Transition]] = field(default_factory=dict)
    sets: List[Tuple[str, E.Expression]] = field(default_factory=list)
    description: str = ""
    compiled: Dict[str, Any] = field(default_factory=dict)   # per-type precompiled pieces


@dataclass
class PlannerDef:
    name: str
    version: str
    kind: str = "graph"
    description: str = ""
    use_when: str = ""
    models: Dict[str, Optional[str]] = field(default_factory=dict)
    prompts: Dict[str, Any] = field(default_factory=dict)
    settings: Dict[str, Any] = field(default_factory=dict)
    limits: Dict[str, Any] = field(default_factory=dict)
    state: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    start: str = ""
    stages: Dict[str, Stage] = field(default_factory=dict)
    refs: List[Tuple[str, str, Any]] = field(default_factory=list)      # (stage id, kind, ref) sub-planners
    warnings: List[Diagnostic] = field(default_factory=list)
    file: str = ""
    raw: Any = None
    digest: str = ""
    cls: Any = None                   # kind python: the Planner class
    has_condense: bool = False

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"

    def describe(self) -> Dict[str, Any]:
        return {"name": self.name, "version": self.version, "kind": self.kind, "description": self.description,
                "use_when": self.use_when, "file": self.file, "start": self.start,
                "stages": {sid: {"type": s.type, "outcomes": sorted(s.outcomes)} for sid, s in self.stages.items()},
                "settings": self.settings, "models": self.models,
                "warnings": [w.to_dict() for w in self.warnings]}


def semver_key(v: str) -> Tuple:
    m = SEMVER.match(v or "")
    if not m:
        return (-1, -1, -1, 0, ())
    pre = m.group(4)
    pre_key: Tuple = ()
    if pre:
        pre_key = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre[1:].split("."))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if pre else 1, pre_key)


def parse_ref(ref: str) -> Tuple[str, Optional[str]]:
    """``name`` / ``name@latest`` -> (name, None); ``name@1.2.0`` -> (name, "1.2.0")."""
    m = PLANNER_REF.match(ref or "")
    if not m:
        raise ValueError(f"{ref!r} is not a planner reference (name, name@version or name@latest)")
    v = m.group(2)
    return m.group(1), (None if v in (None, "latest") else v)


# ── the JSON Schema (Appendix A) ─────────────────────────────────

_SCHEMA: Optional[Dict[str, Any]] = None
_VALIDATORS: Dict[str, Any] = {}
BUILTIN_DEF = {"act": "act", "plan": "plan", "execute": "execute", "call": "call", "match": "match",
               "classify": "classify", "draft": "draft", "critique": "critique", "revise": "revise",
               "verify": "verify", "sample": "sample", "vote": "vote", "foreach": "foreach",
               "planner": "plannerStage", "ask_user": "askUser", "condense": "condense", "answer": "answer",
               "fail": "fail"}


def planner_schema() -> Dict[str, Any]:
    """The JSON Schema for planner files (Planner Reference, Appendix A)."""
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = json.loads((Path(__file__).parent / "planner.schema.json").read_text())
    return _SCHEMA


def _validator(def_name: str):
    if def_name not in _VALIDATORS:
        import jsonschema
        s = planner_schema()
        sub = {"$schema": s["$schema"], "$defs": s["$defs"], "$ref": f"#/$defs/{def_name}"}
        _VALIDATORS[def_name] = jsonschema.Draft202012Validator(sub)
    return _VALIDATORS[def_name]


def schema_errors(value: Any, def_name: str) -> List[str]:
    out = []
    for e in sorted(_validator(def_name).iter_errors(value), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(p) for p in e.absolute_path)
        msg = e.message
        if len(msg) > 240:
            msg = msg[:237] + "..."
        out.append(f"{path + ': ' if path else ''}{msg}")
    return out


# ── P006: everything that must be a string loaded as one ─────────

def _yaml_word(v: Any) -> str:
    return json.dumps(v)


def p006(doc: Any) -> List[Diagnostic]:
    out: List[Diagnostic] = []

    def walk(v: Any, path: str, in_schema: bool = False):
        if isinstance(v, dict):
            for k, x in v.items():
                if not isinstance(k, str):
                    stage = path.split(".")[1] if path.startswith("stages.") and path.count(".") >= 1 else ""
                    if k is True and not in_schema:
                        out.append(Diagnostic("P006", "error", path or "(top)",
                                              (f'stage "{stage}": ' if stage else "") +
                                              'key true is not allowed (a bare on: loads as true; transitions go '
                                              'under "outcomes")'))
                    else:
                        out.append(Diagnostic("P006", "error", f"{path}.{k}" if path else str(k),
                                              (f'stage "{stage}": ' if stage else "") +
                                              f"{path or '(top)'} key loaded as {type(k).__name__} {_yaml_word(k)}; "
                                              f"quote it"))
                    continue
                walk(x, f"{path}.{k}" if path else k, in_schema or k == "schema")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]", in_schema)
    walk(doc, "")
    stages = doc.get("stages") if isinstance(doc, dict) else None
    if isinstance(stages, dict):
        for sid, st in stages.items():
            if not isinstance(st, dict):
                continue
            for i, rule in enumerate(st.get("rules") or [] if isinstance(st.get("rules"), list) else []):
                if isinstance(rule, dict):
                    for key in ("name", "label"):
                        if key in rule and not isinstance(rule[key], str):
                            out.append(Diagnostic("P006", "error", f"stages.{sid}.rules[{i}].{key}",
                                                  f'stage "{sid}": rule {key} loaded as '
                                                  f"{type(rule[key]).__name__} {_yaml_word(rule[key])}; quote it"))
            labels = st.get("labels")
            if isinstance(labels, list):
                for i, lab in enumerate(labels):
                    if not isinstance(lab, str):
                        out.append(Diagnostic("P006", "error", f"stages.{sid}.labels[{i}]",
                                              f'stage "{sid}": label loaded as {type(lab).__name__} '
                                              f"{_yaml_word(lab)}; quote it"))
    return out


# ── compile ──────────────────────────────────────────────────────

@dataclass
class Ceilings:
    max_stages_run: int = 40
    max_visits_per_edge: int = 10
    max_subplanner_depth: int = 2
    max_parallel: int = 4
    max_samples: int = 5
    max_foreach_items: int = 50
    max_steps: int = 8
    max_tool_calls: int = 16
    timeout_s: float = 120.0
    max_cost_usd: float = 1.0
    max_output_tokens: int = 4000


class _Ctx:
    """State of one compile: diagnostics, the slot roots and the hooks."""

    def __init__(self, who: str, ceilings: Ceilings, stage_types: Dict[str, Any],
                 check_alias: Optional[Callable[[str], bool]], check_prompt: Optional[Callable[[str], bool]]):
        self.who = who
        self.ceil = ceilings
        self.types = stage_types
        self.check_alias = check_alias
        self.check_prompt = check_prompt
        self.diags: List[Diagnostic] = []

    def err(self, code: str, loc: str, msg: str):
        self.diags.append(Diagnostic(code, "error", loc, msg))

    def warn(self, code: str, loc: str, msg: str):
        self.diags.append(Diagnostic(code, "warning", loc, msg))


def _digest(doc: Any) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()[:16]


def own_settings(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A planner's settings without the reserved ones (what a Python planner's config model sees)."""
    return {k: v for k, v in (settings or {}).items() if k not in RESERVED_SETTINGS}


def apply_overlay(doc: Dict[str, Any], overlay: Optional[Dict[str, Any]], where: str) -> Dict[str, Any]:
    """Replace top-level ``settings`` keys and re-point ``models`` roles (§2.5). Unknown settings
    keys and roles are refused: an overlay cannot add what the file does not declare."""
    if not overlay:
        return doc
    out = copy.deepcopy(doc)
    sets = overlay.get("settings") or {}
    if not isinstance(sets, dict):
        raise ValueError(f"{where}: settings must be an object")
    declared = out.get("settings") or {}
    unknown = sorted(k for k in sets if k not in declared and k not in RESERVED_SETTINGS)
    if "locality" in sets:
        from sajha.ai.locality import parse
        try:
            parse(sets["locality"])
        except ValueError as e:
            raise ValueError(f"{where}: settings.{e}")
    if unknown:
        raise ValueError(f"{where}: unknown setting(s) {unknown} (the planner declares: {sorted(declared)})")
    out["settings"] = {**declared, **copy.deepcopy(sets)}
    models = overlay.get("models") or {}
    if not isinstance(models, dict):
        raise ValueError(f"{where}: models must be an object")
    if models:
        roles = dict(out.get("models") or {})
        for role, alias in models.items():
            if role != "default" and role not in roles:
                raise ValueError(f"{where}: models.{role} is not a role of the planner")
            roles[role] = alias
        out["models"] = roles
    return out


def compile_planner(doc: Any, *, file_stem: Optional[str] = None, ceilings: Optional[Ceilings] = None,
                    stage_types: Optional[Dict[str, Any]] = None, overlay: Optional[Dict[str, Any]] = None,
                    check_alias: Optional[Callable[[str], bool]] = None,
                    check_prompt: Optional[Callable[[str], bool]] = None, file: str = "",
                    inline_defaults: Optional[Dict[str, str]] = None, python_class: Optional[Callable] = None,
                    overlay_where: str = "overlay") -> PlannerDef:
    """Validate and compile one planner document. Raises PlannerError when any error is found."""
    from sajha.ai.planners_engine.stages import stage_types as _types
    ceil = ceilings or Ceilings()
    types = stage_types if stage_types is not None else _types()
    if inline_defaults and isinstance(doc, dict):
        doc = {**{k: v for k, v in inline_defaults.items() if k not in doc}, **doc}
    who = f"{(doc or {}).get('name') if isinstance(doc, dict) else '?'}@" \
          f"{(doc or {}).get('version') if isinstance(doc, dict) else '?'}"
    cx = _Ctx(who, ceil, types, check_alias, check_prompt)
    if not isinstance(doc, dict):
        cx.err("P001", "", f"not a planner file (expected a mapping, got {type(doc).__name__})")
        raise PlannerError(who, cx.diags)
    cx.diags.extend(p006(doc))
    if any(d.level == "error" for d in cx.diags):
        raise PlannerError(who, cx.diags)
    kind = doc.get("kind", "graph")
    allowed = PYTHON_KEYS if kind == "python" else TOP_KEYS
    for k in doc:
        if k not in allowed:
            cx.err("P004", k, f'unknown key "{k}" (allowed: {", ".join(allowed)})')
    name, version = doc.get("name"), doc.get("version")
    if not isinstance(name, str) or not IDENT.match(name):
        cx.err("P002", "name", f'name "{name}" is not an identifier ([a-z][a-z0-9_]*)')
    elif file_stem is not None:
        stem, _, ver = file_stem.partition("@")
        if stem != name:
            cx.err("P002", "name", f'name "{name}" does not match the file name "{file_stem}"')
        elif ver and ver != version:
            cx.err("P002", "version", f'version "{version}" does not match the file name "{file_stem}"')
    if not isinstance(version, str) or not SEMVER.match(version):
        cx.err("P003", "version", f'version "{version}" is not MAJOR.MINOR.PATCH')
    if cx.diags and any(d.level == "error" for d in cx.diags):
        raise PlannerError(who, cx.diags)
    try:
        doc = apply_overlay(doc, overlay, overlay_where)
    except ValueError as e:
        cx.err("P011", "settings", str(e))
        raise PlannerError(who, cx.diags)
    pdef = PlannerDef(name=name, version=version, kind=kind, description=str(doc.get("description") or ""),
                      use_when=str(doc.get("use_when") or ""), settings=dict(doc.get("settings") or {}),
                      file=file, raw=doc, digest=_digest(doc))
    if isinstance(doc.get("settings"), dict) and "locality" in doc["settings"]:
        from sajha.ai.locality import LocalityError, parse
        try:
            parse(doc["settings"]["locality"])
        except LocalityError as e:
            cx.err("P011", "settings.locality", str(e))
            raise PlannerError(who, cx.diags)
    if kind == "python":
        for msg in schema_errors(doc, "pythonPlanner"):
            cx.err("P011", "", msg)
        if not any(d.level == "error" for d in cx.diags):
            _python_kind(doc, pdef, cx, python_class)
        if any(d.level == "error" for d in cx.diags):
            raise PlannerError(who, cx.diags)
        pdef.warnings = [d for d in cx.diags if d.level == "warning"]
        return pdef
    if kind != "graph":
        cx.err("P011", "kind", f'kind must be graph or python, not "{kind}"')
        raise PlannerError(who, cx.diags)
    _compile_graph(doc, pdef, cx, top=True)
    if any(d.level == "error" for d in cx.diags):
        raise PlannerError(who, cx.diags)
    pdef.warnings = [d for d in cx.diags if d.level == "warning"]
    return pdef


def _python_kind(doc, pdef: PlannerDef, cx: _Ctx, python_class) -> None:
    from pydantic import ValidationError
    cls_path = doc.get("class") or ""
    try:
        if python_class is not None:
            cls = python_class(cls_path)
        else:
            import importlib
            from sajha.ai.planners import Planner
            mod, _, attr = cls_path.partition(":")
            cls = getattr(importlib.import_module(mod), attr)
            if not (isinstance(cls, type) and issubclass(cls, Planner)):
                raise TypeError("not a subclass of sajha.ai.planners.Planner")
        cls.config_model(**own_settings(doc.get("settings")))
        pdef.cls = cls
    except ValidationError as e:
        cx.err("P061", "settings", f'class "{cls_path}": {e}'.replace("\n", " ")[:400])
    except Exception as e:
        cx.err("P061", "class", f'class "{cls_path}": {e}')


def _roots(custom: Iterable[str], extra: Iterable[str] = ()) -> Set[str]:
    return set(BUILTIN_SLOTS) | set(custom) | set(extra)


def _compile_graph(doc: Dict[str, Any], pdef: PlannerDef, cx: _Ctx, top: bool,
                   parent: Optional[PlannerDef] = None, extra_roots: Iterable[str] = (), loc: str = "") -> None:
    """Compile a graph (a file, or a foreach ``do`` sub-graph when ``parent`` is given)."""
    # 1. shape: the schema of Appendix A for everything but the stages, then each stage on its own
    if top:
        shape = {k: v for k, v in doc.items() if k != "stages"}
        shape["stages"] = {"x": {"type": "answer"}}
        for msg in schema_errors(shape, "graphPlanner"):
            cx.err("P011", "", msg)
    stages_raw = doc.get("stages")
    if not isinstance(stages_raw, dict) or not stages_raw:
        cx.err("P011", f"{loc}stages", "stages must be a mapping of 1 to 100 stages")
        return
    if len(stages_raw) > MAX_STAGES:
        cx.err("P011", f"{loc}stages", f"{len(stages_raw)} stages; at most {MAX_STAGES}")
    # 2. custom slots
    if top:
        state = doc.get("state") or {}
        if isinstance(state, dict):
            if len(state) > MAX_CUSTOM_SLOTS:
                cx.err("P050", "state", f"{len(state)} custom slots; at most {MAX_CUSTOM_SLOTS}")
            for sname, decl in state.items():
                if sname in BUILTIN_SLOTS:
                    cx.err("P050", f"state.{sname}", f'state.{sname}: "{sname}" is a built-in slot')
                elif not IDENT.match(str(sname)):
                    cx.err("P050", f"state.{sname}", f'state.{sname}: "{sname}" is not an identifier')
                elif isinstance(decl, dict):
                    if decl.get("default") is not None and not slot_accepts(decl, decl.get("default")):
                        cx.err("P011", f"state.{sname}.default", f"state.{sname}: the default does not match "
                                                                 f"type {decl.get('type')}")
            pdef.state = {k: dict(v) for k, v in state.items() if isinstance(v, dict)}
        pdef.prompts = dict(doc.get("prompts") or {})
        for pname, p in pdef.prompts.items():
            if isinstance(p, dict) and "name" in p and cx.check_prompt is not None and not cx.check_prompt(p["name"]):
                cx.err("P032", f"prompts.{pname}", f'prompt "{p["name"]}" is not in the prompts registry')
    settings = pdef.settings if parent is None else parent.settings
    # 3. models (settings references resolve at load)
    if top:
        try:
            models = E.resolve_settings_refs(dict(doc.get("models") or {}), settings)
        except E.SettingsRefMissing as e:
            cx.err("P044", "models", str(e))
            models = {}
        for role, alias in models.items():
            if alias is not None and not isinstance(alias, str):
                cx.err("P031", f"models.{role}", f"models.{role}: must be an alias, provider/model or null")
            elif alias and cx.check_alias is not None and not cx.check_alias(alias):
                cx.err("P031", f"models.{role}", f'models.{role}: "{alias}" is not a gateway alias or a known model')
        pdef.models = models
        # limits (P060: above the ceiling is clamped with a warning)
        try:
            limits = E.resolve_settings_refs(dict(doc.get("limits") or {}), settings)
        except E.SettingsRefMissing as e:
            cx.err("P044", "limits", str(e))
            limits = {}
        pdef.limits = clamp_limits(limits, cx.ceil, lambda k, v, c: cx.warn("P060", f"limits.{k}",
                                                                              f"limits.{k} {v} clamped to {c}"))
        start = doc.get("start")
    else:
        start = doc.get("start")
    roles = set((pdef.models if parent is None else parent.models) or {}) | {"default"}
    custom = set((pdef.state if parent is None else parent.state) or {})
    roots = _roots(custom, extra_roots)
    stage_ids = set(str(s) for s in stages_raw)
    for sid in stages_raw:
        if not IDENT.match(str(sid)):
            cx.err("P011", f"{loc}stages.{sid}", f'stage id "{sid}" is not an identifier')
    if start not in stages_raw:
        cx.err("P012", f"{loc}start", f'start "{start}" is not a stage')
    pdef.start = start if isinstance(start, str) else ""
    # 4. stages
    for sid, raw in stages_raw.items():
        where = f"{loc}stages.{sid}"
        if not isinstance(raw, dict):
            cx.err("P011", where, f'stage "{sid}": must be a mapping')
            continue
        st_type = raw.get("type")
        impl = cx.types.get(st_type) if isinstance(st_type, str) else None
        if impl is None:
            cx.err("P010", f"{where}.type", f'stage "{sid}": unknown type "{st_type}"')
            continue
        flow_err = False
        if impl.terminal and ("outcomes" in raw or "next" in raw):
            cx.err("P017", where, f'stage "{sid}": {st_type} is terminal and takes no transitions')
            flow_err = True
        if "outcomes" in raw and "next" in raw:
            cx.err("P017", where, f'stage "{sid}": give "next" or "outcomes", not both')
            flow_err = True
        if not flow_err:
            for msg in impl.schema_errors(raw):
                cx.err("P011", where, f'stage "{sid}": {msg}')
        if any(d.level == "error" and d.location.startswith(where) for d in cx.diags):
            continue
        try:
            cfg = E.resolve_settings_refs(copy.deepcopy(raw), settings)
        except E.SettingsRefMissing as e:
            cx.err("P044", where, f'stage "{sid}": {e}')
            continue
        st = Stage(id=sid, type=st_type, cfg=cfg, impl=impl, description=str(cfg.get("description") or ""))
        st.compiled["dynamic"] = any(isinstance(raw.get(k), str) and E.SETTINGS_REF.match(raw[k].strip())
                                     for k in ("rules", "labels")) or "from" in raw
        # transitions
        if not impl.terminal and "outcomes" not in raw and "next" not in raw:
            cx.err("P014", where, f'stage "{sid}": needs "outcomes" or "next"')
        outs = cfg.get("outcomes") or ({"*": {"next": cfg["next"]}} if "next" in cfg else {})
        for okey, tv in outs.items():
            lst = tv if isinstance(tv, list) else [tv]
            if len(lst) > MAX_ALTERNATIVES:
                cx.err("P011", f"{where}.outcomes.{okey}", f'stage "{sid}": at most {MAX_ALTERNATIVES} alternatives')
            st.outcomes[str(okey)] = [_transition(t, f"{sid}:{okey}[{i}]", f"{where}.outcomes.{okey}[{i}]", sid,
                                                  roots, stage_ids, cx) for i, t in enumerate(lst)]
        if "when" in cfg:
            st.guard = _expr(cfg["when"], f"{where}.when", sid, roots, stage_ids, cx)
            if isinstance(cfg.get("else"), dict):
                st.else_ = _transition(cfg["else"], f"{sid}:else", f"{where}.else", sid, roots, stage_ids, cx)
        for slot, ex in (cfg.get("set") or {}).items():
            if slot in BUILTIN_SLOTS:
                cx.err("P052", f"{where}.set.{slot}", f'stage "{sid}": cannot write read-only slot "{slot}"'
                       if slot in READ_ONLY else f'stage "{sid}": set may write custom slots only, not "{slot}"')
                continue
            if slot not in custom:
                cx.err("P051", f"{where}.set.{slot}", f'stage "{sid}": set "{slot}" is not a declared slot')
                continue
            e = _expr(ex, f"{where}.set.{slot}", sid, roots, stage_ids, cx)
            if e is not None:
                st.sets.append((slot, e))
        if impl.model_using:
            role = cfg.get("model")
            if role is not None and role not in roles:
                cx.err("P030", f"{where}.model", f'stage "{sid}": model role "{role}" is not in models')
            prompt = cfg.get("prompt")
            if isinstance(prompt, str) and prompt not in pdef.prompts and (parent is None or prompt not in parent.prompts):
                cx.err("P032", f"{where}.prompt", f'stage "{sid}": prompt "{prompt}" is not in prompts or the '
                                                  f'prompts registry')
            if isinstance(prompt, dict):
                if "name" in prompt and cx.check_prompt is not None and not cx.check_prompt(prompt["name"]):
                    cx.err("P032", f"{where}.prompt", f'stage "{sid}": prompt "{prompt["name"]}" is not in the '
                                                      f'prompts registry')
                for bad in _template_roots(prompt.get("text"), roots, f"{where}.prompt", sid, cx):
                    pass
        if cfg.get("model") is not None and st_type == "planner" and cfg["model"] not in roles:
            cx.err("P030", f"{where}.model", f'stage "{sid}": model role "{cfg["model"]}" is not in models')
        if st_type == "condense":
            pdef.has_condense = True
        # per-type checks (into, templates, regexes, clamps, refs)
        helper = _TypeChecks(cx, pdef, parent, st, where, roots, custom, stage_ids)
        impl.check(helper)
        pdef.stages[sid] = st
    if any(d.level == "error" for d in cx.diags):
        return
    _graph_checks(pdef, cx, loc)


def _expr(text: Any, loc: str, sid: str, roots: Set[str], stage_ids: Set[str], cx: _Ctx) -> Optional[E.Expression]:
    try:
        return E.compile_expression(text, roots, stage_ids)
    except E.ExprSyntaxError as e:
        cx.err("P040", loc, f'stage "{sid}": when: {e} at column {e.column}')
    except E.ExprNameError as e:
        cx.err("P041", loc, f'stage "{sid}": when: {e}')
    except E.ExprTypeError as e:
        cx.err("P042", loc, f'stage "{sid}": when: {e}')
    return None


def _template_roots(text: Any, roots: Set[str], loc: str, sid: str, cx: _Ctx) -> List[str]:
    try:
        bad = E.check_template(text, roots)
    except E.ExprSyntaxError as e:
        cx.err("P043", loc, f'stage "{sid}": template: {e}')
        return []
    for b in bad:
        cx.err("P043", loc, f'stage "{sid}": template references unknown slot "{b}"')
    return bad


def _transition(t: Any, edge: str, loc: str, sid: str, roots: Set[str], stage_ids: Set[str],
                cx: _Ctx) -> Transition:
    if not isinstance(t, dict):
        cx.err("P011", loc, f'stage "{sid}": a transition is a mapping with "next"')
        return Transition(next="", edge=edge)
    tr = Transition(next=str(t.get("next") or ""), edge=edge)
    if tr.next not in stage_ids:
        cx.err("P015", f"{loc}.next", f'stage "{sid}": "{tr.next}" is not a stage')
    if "when" in t:
        tr.when = _expr(t["when"], f"{loc}.when", sid, roots, stage_ids, cx)
    mv = t.get("max_visits")
    if mv is not None:
        if mv == "steps":
            tr.max_visits = "steps"
        elif isinstance(mv, int) and not isinstance(mv, bool) and mv >= 0:
            if mv > cx.ceil.max_visits_per_edge:
                cx.warn("P023", f"{loc}.max_visits",
                        f'stage "{sid}": max_visits {mv} clamped to {cx.ceil.max_visits_per_edge}')
                mv = cx.ceil.max_visits_per_edge
            tr.max_visits = mv
            if not t.get("on_exhausted"):
                cx.err("P021", loc, f'stage "{sid}": bounded edge "{edge}" has no on_exhausted')
        else:
            cx.err("P011", f"{loc}.max_visits", f'stage "{sid}": max_visits must be an integer >= 0 or "steps"')
    if t.get("on_exhausted") is not None:
        tr.on_exhausted = str(t["on_exhausted"])
        if tr.on_exhausted not in stage_ids:
            cx.err("P015", f"{loc}.on_exhausted", f'stage "{sid}": "{tr.on_exhausted}" is not a stage')
    return tr


class _TypeChecks:
    """What a stage type's ``check`` may use: diagnostics, slot roots, clamps and sub-planner refs."""

    def __init__(self, cx: _Ctx, pdef: PlannerDef, parent: Optional[PlannerDef], st: Stage, where: str,
                 roots: Set[str], custom: Set[str], stage_ids: Set[str]):
        self.cx, self.pdef, self.parent, self.st, self.where = cx, pdef, parent, st, where
        self.roots, self.custom, self.stage_ids = roots, custom, stage_ids
        self.ceil = cx.ceil

    @property
    def cfg(self) -> Dict[str, Any]:
        return self.st.cfg

    def err(self, code: str, msg: str, sub: str = ""):
        self.cx.err(code, f"{self.where}{'.' + sub if sub else ''}", f'stage "{self.st.id}": {msg}')

    def warn(self, code: str, msg: str, sub: str = ""):
        self.cx.warn(code, f"{self.where}{'.' + sub if sub else ''}", f'stage "{self.st.id}": {msg}')

    def template(self, text: Any, sub: str, extra: Iterable[str] = ()) -> None:
        _template_roots(text, self.roots | set(extra), f"{self.where}.{sub}", self.st.id, self.cx)

    def expression(self, text: Any, sub: str) -> Optional[E.Expression]:
        return _expr(text, f"{self.where}.{sub}", self.st.id, self.roots, self.stage_ids, self.cx)

    def ref_root(self, ref: Any, sub: str) -> None:
        if not isinstance(ref, str):
            return
        try:
            node = E._Parser(ref).reference_only()
        except E.ExprSyntaxError as e:
            self.err("P041", f"{sub}: {e}", sub)
            return
        if node[1] not in self.roots:
            self.err("P041", f'{sub}: unknown name "{node[1]}"', sub)

    def clamp(self, key: str, ceiling: int) -> None:
        v = self.cfg.get(key)
        if isinstance(v, int) and not isinstance(v, bool) and v > ceiling:
            self.warn("P060", f"{key} {v} clamped to {ceiling}", key)
            self.cfg[key] = ceiling

    def into(self, allowed_builtin: Iterable[str] = (), value_type: str = "any") -> None:
        slot = self.cfg.get("into")
        if slot is None:
            return
        if slot in READ_ONLY:
            self.err("P052", f'cannot write read-only slot "{slot}"', "into")
        elif slot in BUILTIN_SLOTS and slot not in allowed_builtin:
            self.err("P051", f'into "{slot}" is not a declared slot of type {value_type}', "into")
        elif slot not in BUILTIN_SLOTS:
            decl = (self.pdef.state if self.parent is None else self.parent.state).get(slot)
            if decl is None:
                self.err("P051", f'into "{slot}" is not a declared slot of type {value_type}', "into")
            elif value_type != "any" and decl.get("type") not in ("any", value_type):
                self.err("P051", f'into "{slot}" is not a declared slot of type {value_type}', "into")

    def regex(self, pattern: Any, rule: str, sub: str) -> Optional[re.Pattern]:
        if not isinstance(pattern, str):
            return None
        if len(pattern) > 1000:
            self.err("P045", f'rule "{rule}": the pattern is longer than 1000 characters', sub)
            return None
        try:
            rx = re.compile(pattern)
        except re.error as e:
            self.err("P045", f'rule "{rule}": pattern does not compile: {e}', sub)
            return None
        if re.search(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)[+*{]", pattern):
            self.warn("P046", f'rule "{rule}": pattern may backtrack catastrophically', sub)
        return rx

    def planner_ref(self, ref: Any, sub: str, kind: str = "planner") -> None:
        if isinstance(ref, dict):
            if not isinstance(ref.get("use"), str):
                self.err("P033", "an overlay needs use: <planner reference>", sub)
                return
            ref_s = ref["use"]
        else:
            ref_s = ref
        try:
            parse_ref(ref_s)
        except ValueError as e:
            self.err("P033", str(e), sub)
            return
        root = self.pdef if self.parent is None else self.parent
        root.refs.append((self.st.id, kind, ref))

    def subgraph(self, doc: Dict[str, Any], sub: str, extra_roots: Iterable[str]) -> Optional[PlannerDef]:
        root = self.pdef if self.parent is None else self.parent
        sub_def = PlannerDef(name=f"{root.name}.{self.st.id}", version=root.version, settings=root.settings,
                             models=root.models, prompts=root.prompts, state={})
        before = len(self.cx.diags)
        _compile_graph(doc, sub_def, self.cx, top=False, parent=root, extra_roots=extra_roots,
                       loc=f"{self.where}.{sub}.")
        if any(d.level == "error" for d in self.cx.diags[before:]):
            return None
        root.refs.extend(sub_def.refs)
        root.has_condense = root.has_condense or sub_def.has_condense
        return sub_def


def clamp_limits(limits: Dict[str, Any], ceil: Ceilings, warn: Callable[[str, Any, Any], None]) -> Dict[str, Any]:
    out = {}
    for k, v in (limits or {}).items():
        c = getattr(ceil, k, None)
        if c is not None and isinstance(v, (int, float)) and not isinstance(v, bool) and v > c:
            warn(k, v, c)
            v = c
        out[k] = v
    return out


def slot_accepts(decl: Dict[str, Any], value: Any) -> bool:
    t = decl.get("type", "any")
    if value is None or t == "any":
        return True
    if t == "string":
        return isinstance(value, str)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool) or \
            (isinstance(value, float) and value.is_integer())
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "array":
        if not isinstance(value, list):
            return False
        it = decl.get("items", "any")
        return all(slot_accepts({"type": it}, x) for x in value)
    if t == "object":
        return isinstance(value, dict)
    return True


# ── graph rules: P013 P014 P016 P020 P022 P062 P063 ───────────────

def _edges(st: Stage) -> List[Tuple[str, Transition]]:
    out = []
    for lst in st.outcomes.values():
        for t in lst:
            out.append((t.next, t))
            if t.on_exhausted:
                out.append((t.on_exhausted, Transition(next=t.on_exhausted, edge=t.edge + ":exhausted")))
    if st.else_ is not None:
        out.append((st.else_.next, st.else_))
        if st.else_.on_exhausted:
            out.append((st.else_.on_exhausted, Transition(next=st.else_.on_exhausted, edge=st.else_.edge + ":exhausted")))
    return out


def _graph_checks(pdef: PlannerDef, cx: _Ctx, loc: str) -> None:
    stages = pdef.stages
    for sid, st in stages.items():
        where = f"{loc}stages.{sid}"
        known = st.impl.outcomes(st)
        if known is None:
            if "*" not in st.outcomes and not st.impl.terminal:
                cx.err("P062", f"{where}.outcomes", f'stage "{sid}": outcomes are not known at load; '
                                                   f'add a "*" transition')
        else:
            for o in known:
                if o not in st.outcomes and "*" not in st.outcomes and not st.impl.terminal:
                    cx.err("P014", f"{where}.outcomes", f'stage "{sid}": outcome "{o}" has no transition '
                                                        f'(add it or "*")')
            for o in st.outcomes:
                if o != "*" and o not in known:
                    cx.err("P016", f"{where}.outcomes.{o}", f'stage "{sid}": "{o}" is not an outcome of {st.type} '
                                                            f'(outcomes: {", ".join(known)})')
        for o, lst in st.outcomes.items():
            if lst and all(t.when is not None for t in lst) and "*" not in st.outcomes:
                cx.warn("P016", f"{where}.outcomes.{o}", f'stage "{sid}": outcome "{o}" may find no transition')
            for t in lst:
                if t.max_visits == "steps" and not ((st.type == "act" and o == "called") or st.type == "execute"):
                    cx.err("P022", f"{where}.outcomes.{o}", f'stage "{sid}": max_visits "steps" is allowed only on '
                                                            f'act.called and execute outcomes')
        if st.else_ is not None and st.else_.max_visits == "steps":
            cx.err("P022", f"{where}.else", f'stage "{sid}": max_visits "steps" is allowed only on act.called and '
                                            f'execute outcomes')
    if pdef.start not in stages:
        return
    # reachability
    seen, todo = {pdef.start}, [pdef.start]
    while todo:
        for nxt, _t in _edges(stages[todo.pop()]):
            if nxt in stages and nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    for sid in stages:
        if sid not in seen:
            cx.err("P013", f"{loc}stages.{sid}", f'stage "{sid}" is unreachable from "{pdef.start}"')
    # a terminal stage reachable from every stage
    rev: Dict[str, Set[str]] = {s: set() for s in stages}
    for sid, st in stages.items():
        for nxt, _t in _edges(st):
            if nxt in rev:
                rev[nxt].add(sid)
    ok = {s for s, st in stages.items() if st.impl.terminal}
    todo = list(ok)
    while todo:
        for prev in rev[todo.pop()]:
            if prev not in ok:
                ok.add(prev)
                todo.append(prev)
    for sid in stages:
        if sid not in ok:
            cx.err("P063", f"{loc}stages.{sid}", f'stage "{sid}": no answer or fail stage is reachable from here')
    # every cycle crosses a bounded edge
    graph = {sid: [n for n, t in _edges(st) if n in stages and t.max_visits is None] for sid, st in stages.items()}
    color: Dict[str, int] = {}
    stack: List[str] = []
    found: List[List[str]] = []

    def dfs(u: str):
        color[u] = 1
        stack.append(u)
        for v in graph[u]:
            if found:
                return
            if color.get(v, 0) == 0:
                dfs(v)
            elif color.get(v) == 1:
                found.append(stack[stack.index(v):] + [v])
                return
        stack.pop()
        color[u] = 2

    for sid in stages:
        if color.get(sid, 0) == 0 and not found:
            dfs(sid)
    if found:
        cyc = " -> ".join(found[0])
        cx.err("P020", f"{loc}stages", f"unbounded cycle: {cyc} (add max_visits to an edge of it)")
