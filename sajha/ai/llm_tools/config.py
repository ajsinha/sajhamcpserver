"""
SAJHA MCP Server — LLM tools: server settings (``ai.llm_tools.*``), the ``llm`` block, load-time
validation, derived annotations and lint findings.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Design and as-built behaviour: docs/architecture/LLM Tools.md §4, §5, §11, §12, §19.

``ai.llm_tools.*`` values are **ceilings**: a tool's own ``llm.limits`` may ask for less, never
more (:meth:`LLMSpec.effective_limits`). Every key resolves env > YAML > default, the env name
being ``SAJHA_AI_LLM_TOOLS_<SECTION>_<FIELD>`` (for example
``SAJHA_AI_LLM_TOOLS_RUNTIME_MAX_CONCURRENT_RUNS``).
"""

from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sajha.ai.llm.settings import Layered, load_ai_yaml, resolve_layers

logger = logging.getLogger(__name__)

IMPLEMENTATION = "sajha.ai.llm_tools.LLMTool"
MODES = ("answer", "complete", "extract", "classify", "grounded", "narrate", "judge")
DETERMINISTIC_MODES = ("complete", "extract", "classify", "judge")      # may set cache: true
TEMPLATE_MODES = ("complete", "extract", "classify", "judge", "narrate")
QUESTION_MODES = ("answer", "grounded")
MEMORY_MODES = ("none", "conversation", "client")
# fields of the result that the run itself fills in (never asked of the model)
META_FIELDS = ("stopped_by", "conversation_id", "error", "note", "citations", "confidence", "steps", "models",
               "usage", "cached", "data")

PLACEHOLDER = re.compile(r"\{\{\s*input\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

# keys of the llm block, and the modes that may use each (None: every mode)
KEYS: Dict[str, Optional[Tuple[str, ...]]] = {
    "mode": None, "model": None, "system_prompt": None, "prompt": None, "limits": None, "output": None,
    "temperature": None, "memory": None, "sampling": None, "nesting": None,
    "planner": ("answer",),
    "planner_choices": ("answer",),
    "template": TEMPLATE_MODES,
    "tools": ("answer",),
    "confirm": ("answer",),
    "rag": ("grounded",),
    "source": ("narrate",),
    "rubric": ("judge",),
    "cache": DETERMINISTIC_MODES,
}
LIMIT_KEYS = ("max_steps", "max_tool_calls", "timeout_s", "max_input_chars", "max_output_tokens", "max_cost_usd")


# ── server settings: ai.llm_tools.* ─────────────────────────────────────────

class LimitSettings(Layered):
    """``ai.llm_tools.limits``: the ceilings every LLM tool's ``llm.limits`` is clamped to."""
    max_steps: int = 8
    max_tool_calls: int = 16
    timeout_s: float = 120.0
    max_input_chars: int = 20000
    max_output_tokens: int = 4000
    max_cost_usd: float = 1.0


class AnonymousSettings(Layered):
    """``ai.llm_tools.anonymous``: may anonymous callers run LLM tools, and under which limits."""
    enabled: bool = False
    max_steps: int = 3
    max_cost_usd: float = 0.02


class CacheSettings(Layered):
    """``ai.llm_tools.memory.cache``: the optional write-through hot cache of conversations (T1)."""
    enabled: bool = False
    max_mb: float = 64.0
    ttl_s: float = 300.0


class SpoolSettings(Layered):
    """``ai.llm_tools.memory.spool``: per-run files for large in-flight payloads (T3)."""
    dir: str = "data/spool/llm_tools"
    max_mb: float = 1024.0
    per_run_mb: float = 128.0
    orphan_minutes: float = 60.0


class WorkingSetSettings(Layered):
    """``ai.llm_tools.memory`` resource keys (the conversation keys are ToolMemorySettings in memory.py)."""
    working_set_max_kb: int = 2048
    spill_threshold_kb: int = 256


class GuardSettings(Layered):
    """``ai.llm_tools.runtime.memory_guard``: soft and hard resident-memory limits."""
    soft_pct: float = 70.0
    hard_pct: float = 85.0
    soft_mb: float = 0.0                   # > 0: an absolute limit instead of the percentage
    hard_mb: float = 0.0
    interval_s: float = 2.0
    enabled: bool = True


class RuntimeSettings(Layered):
    """``ai.llm_tools.runtime``: concurrency per process and the admission queue."""
    max_concurrent_runs: int = 8
    max_queued: int = 32
    queue_timeout_s: float = 30.0
    retry_after_s: int = 5                 # the Retry-After a busy REST answer carries


class ResultCacheSettings(Layered):
    """``ai.llm_tools.result_cache``: results of deterministic modes for tools that set ``cache: true``."""
    max_entries: int = 1000
    ttl_s: float = 3600.0


class TopSettings(Layered):
    enabled: bool = True
    default_model: str = "default"
    max_depth: int = 2


@dataclass
class LLMToolSettings:
    enabled: bool = True
    default_model: str = "default"
    max_depth: int = 2
    limits: LimitSettings = field(default_factory=LimitSettings)
    anonymous: AnonymousSettings = field(default_factory=AnonymousSettings)
    working_set: WorkingSetSettings = field(default_factory=WorkingSetSettings)
    cache: CacheSettings = field(default_factory=CacheSettings)
    spool: SpoolSettings = field(default_factory=SpoolSettings)
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)
    guard: GuardSettings = field(default_factory=GuardSettings)
    result_cache: ResultCacheSettings = field(default_factory=ResultCacheSettings)


def _resolve(cls, section: str, raw: Dict[str, Any], environ=None):
    cfg = {k: v for k, v in dict(raw or {}).items() if k in cls.model_fields}
    try:
        model, _ = resolve_layers(cls, section, cfg, environ=environ)
        return model
    except Exception as e:
        logger.warning(f"ai.{section.replace('_', '.', 1)}: {e}; using the defaults")
        return cls()


def load_settings(raw: Optional[Dict[str, Any]] = None, environ=None) -> LLMToolSettings:
    """Resolve ``ai.llm_tools`` (env > YAML > default). ``raw`` is the ``llm_tools`` mapping."""
    if raw is None:
        raw = load_ai_yaml().get("llm_tools") or {}
    raw = dict(raw or {})
    mem = dict(raw.get("memory") or {})
    rt = dict(raw.get("runtime") or {})
    top = _resolve(TopSettings, "llm_tools", raw, environ)
    return LLMToolSettings(
        enabled=top.enabled, default_model=top.default_model, max_depth=max(1, int(top.max_depth)),
        limits=_resolve(LimitSettings, "llm_tools_limits", raw.get("limits") or {}, environ),
        anonymous=_resolve(AnonymousSettings, "llm_tools_anonymous", raw.get("anonymous") or {}, environ),
        working_set=_resolve(WorkingSetSettings, "llm_tools_memory", mem, environ),
        cache=_resolve(CacheSettings, "llm_tools_memory_cache", mem.get("cache") or {}, environ),
        spool=_resolve(SpoolSettings, "llm_tools_memory_spool", mem.get("spool") or {}, environ),
        runtime=_resolve(RuntimeSettings, "llm_tools_runtime", rt, environ),
        guard=_resolve(GuardSettings, "llm_tools_runtime_memory_guard", rt.get("memory_guard") or {}, environ),
        result_cache=_resolve(ResultCacheSettings, "llm_tools_result_cache", raw.get("result_cache") or {}, environ),
    )


_settings: Optional[LLMToolSettings] = None


def settings() -> LLMToolSettings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def set_settings(s: Optional[LLMToolSettings]) -> None:
    """Install settings (tests); None re-reads them on next use."""
    global _settings
    _settings = s


# ── the llm block ─────────────────────────────────────────────────────────

class LLMConfigError(ValueError):
    """An ``llm`` block the loader refuses (the tool does not load; lint reports it)."""

    def __init__(self, problems: List[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


@dataclass
class Limits:
    max_steps: int
    max_tool_calls: int
    timeout_s: float
    max_input_chars: int
    max_output_tokens: int
    max_cost_usd: float

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class LLMSpec:
    mode: str
    model: str = ""
    system_prompt: str = ""
    prompt: Optional[Dict[str, Any]] = None
    template: str = ""
    planner: Any = None                   # a planner reference, an inline definition or an overlay (§9.12)
    planner_choices: List[str] = field(default_factory=list)
    allow: List[str] = field(default_factory=list)
    deny: List[str] = field(default_factory=list)
    rag_sources: List[str] = field(default_factory=list)
    rag_top_k: int = 5
    limits: Dict[str, Any] = field(default_factory=dict)
    memory_mode: str = "none"
    memory_ttl_minutes: Optional[int] = None
    memory_max_turns: Optional[int] = None
    accept_client_history: bool = False
    sampling: str = "never"
    citations: bool = True
    steps: bool = False
    confirm: str = "ask"
    nesting_allow: bool = False
    source: Dict[str, Any] = field(default_factory=dict)
    rubric: Dict[str, Any] = field(default_factory=dict)
    cache: bool = False
    temperature: Optional[float] = None

    def effective_limits(self, s: Optional[LLMToolSettings] = None, anonymous: bool = False) -> Limits:
        """The tool's limits clamped to the server ceilings (and the anonymous ones for anonymous callers)."""
        s = s or settings()
        ceil = s.limits
        out = {}
        for k in LIMIT_KEYS:
            c = getattr(ceil, k)
            v = self.limits.get(k)
            out[k] = min(v, c) if isinstance(v, (int, float)) and not isinstance(v, bool) else c
        if anonymous:
            out["max_steps"] = min(out["max_steps"], s.anonymous.max_steps)
            out["max_cost_usd"] = min(out["max_cost_usd"], s.anonymous.max_cost_usd)
        out["max_steps"], out["max_tool_calls"] = int(out["max_steps"]), int(out["max_tool_calls"])
        out["max_input_chars"], out["max_output_tokens"] = int(out["max_input_chars"]), int(out["max_output_tokens"])
        return Limits(**out)


def _str_list(v: Any) -> Optional[List[str]]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return list(v)
    return None


def placeholders(text: str) -> List[str]:
    return list(dict.fromkeys(PLACEHOLDER.findall(text or "")))


def _props(schema: Any) -> Dict[str, Any]:
    if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
        return schema["properties"]
    return {}


def label_enum(output_schema: Any) -> List[str]:
    lab = _props(output_schema).get("label")
    if isinstance(lab, dict) and isinstance(lab.get("enum"), list):
        return [str(x) for x in lab["enum"]]
    return []


def parse_llm_block(config: Dict[str, Any], prompts_registry: Any = None) -> LLMSpec:
    """The validated :class:`LLMSpec` of a tool config, or :class:`LLMConfigError` with every problem
    found (LLM Tools §5.2). Checks that need the whole catalog (``tools.allow`` matching a tool) are
    in :func:`catalog_problems`, because tools load in any order."""
    problems: List[str] = []
    llm = config.get("llm")
    if not isinstance(llm, dict):
        raise LLMConfigError(["the config has no llm block (an object)"])
    mode = llm.get("mode")
    if mode not in MODES:
        raise LLMConfigError([f"llm.mode must be one of {', '.join(MODES)}; is {mode!r}"])
    for k in llm:
        if k not in KEYS:
            problems.append(f"llm.{k} is not a known key")
        elif KEYS[k] is not None and mode not in KEYS[k]:
            problems.append(f"llm.{k} does not apply to mode {mode} (only {', '.join(KEYS[k])})")
    spec = LLMSpec(mode=mode)
    spec.model = str(llm.get("model") or "")
    if "system_prompt" in llm and "prompt" in llm:
        problems.append("llm.system_prompt and llm.prompt are mutually exclusive")
    if llm.get("system_prompt") is not None and not isinstance(llm.get("system_prompt"), str):
        problems.append("llm.system_prompt must be a string")
    spec.system_prompt = str(llm.get("system_prompt") or "")
    if "prompt" in llm:
        p = llm["prompt"]
        if not isinstance(p, dict) or not isinstance(p.get("name"), str) or not p["name"]:
            problems.append('llm.prompt must be {"name": "<prompt>", "arguments": {...}}')
        else:
            if p.get("arguments") is not None and not isinstance(p.get("arguments"), dict):
                problems.append("llm.prompt.arguments must be an object")
            spec.prompt = {"name": p["name"], "arguments": dict(p.get("arguments") or {})}
            if prompts_registry is not None and prompts_registry.get_prompt(p["name"]) is None:
                problems.append(f"llm.prompt.name {p['name']!r} is not in the prompts registry")
    if "template" in llm and not isinstance(llm["template"], str):
        problems.append("llm.template must be a string")
    spec.template = str(llm.get("template") or "")
    if mode in TEMPLATE_MODES and not spec.template.strip():
        problems.append(f"mode {mode} needs llm.template (the user message, with {{{{input.<field>}}}} placeholders)")

    planner = llm.get("planner")
    if planner is not None:            # a reference, name@version, an inline definition or an overlay (§9.12)
        try:
            from sajha.ai.planners_engine.registry import check_tool_planner
            spec.planner = check_tool_planner(planner, str(config.get("name") or "tool"), config.get("version"))
        except Exception as e:
            problems.append(f"llm.planner: {e}")
    if "planner_choices" in llm:       # the caller may choose among these (an enum on the planner argument)
        choices = llm["planner_choices"]
        if not isinstance(choices, list) or not choices or not all(isinstance(c, str) and c for c in choices):
            problems.append("llm.planner_choices must be a non-empty list of planner references")
        else:
            try:
                from sajha.ai.planners_engine.registry import check_tool_planner
                for c in choices:
                    check_tool_planner(c, str(config.get("name") or "tool"), config.get("version"))
                spec.planner_choices = list(dict.fromkeys(choices))
            except Exception as e:
                problems.append(f"llm.planner_choices: {e}")

    tools = llm.get("tools")
    if tools is not None:
        if not isinstance(tools, dict) or set(tools) - {"allow", "deny"}:
            problems.append('llm.tools must be {"allow": [...], "deny": [...]}')
        else:
            a, d = _str_list(tools.get("allow")), _str_list(tools.get("deny"))
            if a is None or d is None:
                problems.append("llm.tools.allow and llm.tools.deny must be lists of glob patterns")
            else:
                spec.allow, spec.deny = a, d
    rag = llm.get("rag")
    if rag is not None:
        if not isinstance(rag, dict) or set(rag) - {"sources", "top_k"}:
            problems.append('llm.rag must be {"sources": [...], "top_k": n}')
        else:
            srcs = _str_list(rag.get("sources"))
            if srcs is None:
                problems.append("llm.rag.sources must be a list of source names")
            else:
                spec.rag_sources = srcs
            if rag.get("top_k") is not None:
                if not isinstance(rag["top_k"], int) or isinstance(rag["top_k"], bool) or not 1 <= rag["top_k"] <= 20:
                    problems.append("llm.rag.top_k must be an integer from 1 to 20")
                else:
                    spec.rag_top_k = rag["top_k"]

    limits = llm.get("limits")
    if limits is not None:
        if not isinstance(limits, dict):
            problems.append("llm.limits must be an object")
        else:
            for k, v in limits.items():
                if k not in LIMIT_KEYS:
                    problems.append(f"llm.limits.{k} is not a known limit ({', '.join(LIMIT_KEYS)})")
                elif isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
                    problems.append(f"llm.limits.{k} must be a positive number")
            spec.limits = {k: v for k, v in limits.items() if k in LIMIT_KEYS}

    mem = llm.get("memory")
    if mem is not None:
        if not isinstance(mem, dict):
            problems.append("llm.memory must be an object")
        else:
            unknown = set(mem) - {"mode", "ttl_minutes", "max_turns", "on_overflow", "accept_client_history"}
            if unknown:
                problems.append(f"llm.memory: unknown key(s) {sorted(unknown)}")
            spec.memory_mode = str(mem.get("mode") or "none")
            if spec.memory_mode not in MEMORY_MODES:
                problems.append(f"llm.memory.mode must be one of {', '.join(MEMORY_MODES)}")
            for k in ("ttl_minutes", "max_turns"):
                v = mem.get(k)
                if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v <= 0):
                    problems.append(f"llm.memory.{k} must be a positive integer")
            spec.memory_ttl_minutes = mem.get("ttl_minutes")
            spec.memory_max_turns = mem.get("max_turns")
            if mem.get("on_overflow", "summarise") not in ("summarise", "summarize"):
                problems.append("llm.memory.on_overflow: only summarise is supported")
            spec.accept_client_history = bool(mem.get("accept_client_history", False))
            if spec.memory_mode != "none" and mode not in QUESTION_MODES:
                problems.append(f"llm.memory.mode {spec.memory_mode} needs mode answer or grounded")

    sampling = llm.get("sampling", "never")
    if sampling not in ("never", "prefer", "require"):
        problems.append("llm.sampling must be never, prefer or require")
    elif sampling != "never" and mode not in ("complete", "extract", "classify", "judge"):
        # sajha/ai/llm_tools/sampling.py: one model call per answer; planner-heavy modes come later (§12)
        problems.append(f"llm.sampling {sampling} is built for modes complete, extract, classify and judge, "
                        f"not {mode}; use never")
    else:
        spec.sampling = sampling

    out = llm.get("output")
    if out is not None:
        if not isinstance(out, dict) or set(out) - {"citations", "steps"}:
            problems.append('llm.output must be {"citations": bool, "steps": bool}')
        else:
            spec.citations = bool(out.get("citations", True))
            spec.steps = bool(out.get("steps", False))
    spec.confirm = str(llm.get("confirm", "ask"))
    if spec.confirm not in ("ask", "refuse"):
        problems.append("llm.confirm must be ask or refuse")
    nest = llm.get("nesting")
    if nest is not None:
        if not isinstance(nest, dict) or set(nest) - {"allow"}:
            problems.append('llm.nesting must be {"allow": true|false}')
        else:
            spec.nesting_allow = bool(nest.get("allow", False))
    if "temperature" in llm:
        t = llm["temperature"]
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not 0 <= t <= 2:
            problems.append("llm.temperature must be a number from 0 to 2")
        else:
            spec.temperature = float(t)
    if "cache" in llm:
        if not isinstance(llm["cache"], bool):
            problems.append("llm.cache must be true or false")
        spec.cache = bool(llm["cache"])

    # mode-specific checks: inputs the mode needs, outputs it fills
    ins, outs = _props(config.get("inputSchema")), _props(config.get("outputSchema"))
    if not isinstance(config.get("outputSchema"), dict) or config["outputSchema"].get("type") != "object":
        problems.append("an LLM tool needs an outputSchema of type object")
    if mode in QUESTION_MODES:
        if "question" not in ins:
            problems.append(f"mode {mode} needs a question property in inputSchema")
        if "answer" not in outs:
            problems.append(f"mode {mode} needs an answer property in outputSchema")
    for ph in placeholders(spec.template):
        if ph not in ins:
            problems.append(f"llm.template uses {{{{input.{ph}}}}}, which is not an inputSchema property")
    for v in (spec.prompt or {}).get("arguments", {}).values():
        for ph in placeholders(str(v)):
            if ph not in ins:
                problems.append(f"llm.prompt.arguments use {{{{input.{ph}}}}}, which is not an inputSchema property")
    if spec.memory_mode == "conversation" and "conversation_id" not in ins:
        problems.append("llm.memory.mode conversation needs a conversation_id property in inputSchema")
    if (spec.memory_mode == "client" or spec.accept_client_history) and "messages" not in ins:
        problems.append("client history needs a messages property in inputSchema")
    if mode in ("complete", "narrate") and "text" not in outs:
        problems.append(f"mode {mode} needs a text property in outputSchema")
    if mode == "complete" and spec.allow:
        problems.append("mode complete calls no tools: llm.tools.allow must be empty")
    if mode == "classify" and not label_enum(config.get("outputSchema")):
        problems.append("mode classify needs an outputSchema label property with an enum of the labels")
    if mode == "extract" and not [k for k in outs if k not in META_FIELDS]:
        problems.append("mode extract needs outputSchema properties for the fields to extract")
    if mode == "grounded" and spec.planner:
        problems.append("llm.planner applies to mode answer only")
    if mode == "narrate":
        src = llm.get("source")
        if not isinstance(src, dict) or len([k for k in ("composite", "workflow") if src.get(k)]) != 1 \
                or set(src) - {"composite", "workflow", "arguments"}:
            problems.append('mode narrate needs llm.source: {"composite": "<name>"} or {"workflow": "<name>"}, '
                            'optionally with "arguments"')
        else:
            if src.get("arguments") is not None and not isinstance(src.get("arguments"), dict):
                problems.append("llm.source.arguments must be an object")
            spec.source = dict(src)
        if "data" not in outs:
            problems.append("mode narrate needs a data property in outputSchema (the source's result)")
    if mode == "judge":
        rub = llm.get("rubric")
        crit = rub.get("criteria") if isinstance(rub, dict) else None
        if not isinstance(crit, list) or not crit:
            problems.append('mode judge needs llm.rubric: {"criteria": [{"name", "description", "min", "max"}], '
                            '"pass_score": n}')
        else:
            seen = set()
            for i, c in enumerate(crit):
                if not isinstance(c, dict) or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", str(c.get("name") or "")):
                    problems.append(f"llm.rubric.criteria[{i}] needs a name (letters, digits, _)")
                    continue
                if c["name"] in seen:
                    problems.append(f"llm.rubric.criteria: {c['name']} appears twice")
                seen.add(c["name"])
                lo, hi = c.get("min", 1), c.get("max", 5)
                if not all(isinstance(x, int) and not isinstance(x, bool) for x in (lo, hi)) or lo >= hi:
                    problems.append(f"llm.rubric.criteria[{i}]: min and max must be integers, min < max")
                w = c.get("weight", 1)
                if isinstance(w, bool) or not isinstance(w, (int, float)) or w <= 0:
                    problems.append(f"llm.rubric.criteria[{i}].weight must be a positive number")
            ps = rub.get("pass_score")
            if ps is not None and (isinstance(ps, bool) or not isinstance(ps, (int, float))):
                problems.append("llm.rubric.pass_score must be a number")
            spec.rubric = dict(rub)
        for k in ("scores", "verdict"):
            if k not in outs:
                problems.append(f"mode judge needs a {k} property in outputSchema")
    if problems:
        raise LLMConfigError(problems)
    return spec


# ── the catalog: which tools a tool may call, and what that makes it ────────

def is_llm_tool(tool: Any) -> bool:
    cfg = getattr(tool, "config", None) or {}
    return isinstance(cfg, dict) and isinstance(cfg.get("llm"), dict)


def _matches(name: str, patterns: List[str]) -> bool:
    return any(p == "*" or fnmatch.fnmatchcase(name, p) for p in patterns)


def allowed_names(spec: LLMSpec, self_name: str, registry: Any) -> List[str]:
    """``tools.allow − tools.deny`` over the catalog (before the caller's own access is applied):
    never the tool itself; other LLM tools only with ``nesting.allow``; destructive tools not at all
    with ``confirm: refuse``."""
    if not spec.allow or registry is None:
        return []
    from sajha.ai.intelligence import is_destructive
    out = []
    for name, tool in sorted((getattr(registry, "tools", {}) or {}).items()):
        if name == self_name or not _matches(name, spec.allow) or _matches(name, spec.deny):
            continue
        if is_llm_tool(tool) and not spec.nesting_allow:
            continue
        if spec.confirm == "refuse" and is_destructive(tool):
            continue
        out.append(name)
    return out


def derived_annotations(spec: LLMSpec, self_name: str, registry: Any) -> Dict[str, bool]:
    """LLM Tools §4: readOnlyHint only if every tool it may call is read-only; destructiveHint if any
    may be destructive; openWorldHint if any reaches outside the server."""
    names: List[str] = []
    if spec.mode == "answer":
        names = allowed_names(spec, self_name, registry)
    elif spec.mode == "narrate":
        src = source_tool_name(spec, registry)
        names = [src] if src else []
    elif spec.mode == "grounded":
        names = ["sajha_search_docs"]
    tools = (getattr(registry, "tools", {}) or {}) if registry is not None else {}
    read_only, destructive, open_world = True, False, False
    for n in names:
        t = tools.get(n)
        if t is None:
            # a tool the registry cannot show is not known to be read-only (fail closed); the
            # built-in document search is read-only by construction
            if n != "sajha_search_docs":
                read_only = False
            continue
        ann = (getattr(t, "config", None) or {}).get("annotations") or {}
        md = (getattr(t, "config", None) or {}).get("metadata") or {}
        if not isinstance(ann, dict):
            ann = {}
        if ann.get("readOnlyHint") is not True:
            read_only = False
        if ann.get("destructiveHint") is True or md.get("destructive") is True:
            destructive = True
        if ann.get("openWorldHint") is not False:        # MCP's default for a tool that does not say
            open_world = True
    if spec.mode == "narrate" and spec.source.get("workflow"):
        read_only = False
    return {"readOnlyHint": read_only and not destructive, "destructiveHint": destructive,
            "openWorldHint": open_world}


def source_tool_name(spec: LLMSpec, registry: Any) -> Optional[str]:
    """The registry tool a narrate source runs: the composite itself, or the workflow's published tool."""
    if spec.source.get("composite"):
        return str(spec.source["composite"])
    wf = spec.source.get("workflow")
    if not wf or registry is None:
        return None
    for name, tool in (getattr(registry, "tools", {}) or {}).items():
        md = (getattr(tool, "config", None) or {}).get("metadata") or {}
        if md.get("workflow") == wf:
            return name
    return None


def catalog_problems(spec: LLMSpec, self_name: str, registry: Any, strict: bool = False) -> List[str]:
    """Problems only the whole catalog shows. ``strict`` (lint): every allow pattern must match a tool;
    otherwise (a call) only an allow list that matches nothing at all is refused."""
    out = []
    tools = (getattr(registry, "tools", {}) or {}) if registry is not None else {}
    if spec.mode == "answer" and spec.allow and tools:
        unmatched = [p for p in spec.allow if not [n for n in tools if n != self_name and _matches(n, [p])]]
        if strict:
            out.extend(f"llm.tools.allow pattern {p!r} matches no tool" for p in unmatched)
        elif len(unmatched) == len(spec.allow):
            out.append(f"llm.tools.allow ({', '.join(spec.allow)}) matches no tool")
    if spec.mode == "answer" and spec.planner is not None and tools:      # P036: the planner's tool names
        try:
            from sajha.ai.planners_engine.registry import tool_name_problems
            out.extend(tool_name_problems(spec.planner, allowed_names(spec, self_name, registry), self_name))
        except Exception as e:
            logger.debug(f"{self_name}: planner tool check skipped: {e}")
    if spec.mode == "narrate" and tools and source_tool_name(spec, registry) not in tools:
        what = f"composite {spec.source.get('composite')!r}" if spec.source.get("composite") else \
            f"workflow {spec.source.get('workflow')!r} (published as a tool)"
        out.append(f"llm.source: no {what} in the catalog")
    return out


def _is_llm_implementation(path: Any) -> bool:
    if path == IMPLEMENTATION:
        return True
    try:
        import importlib
        mod, cls = str(path).rsplit(".", 1)
        from sajha.ai.llm_tools.tool import LLMTool
        return issubclass(getattr(importlib.import_module(mod), cls), LLMTool)
    except Exception:
        return False


def lint_findings(name: str, config: Dict[str, Any], registry: Any,
                  declared: Optional[Dict[str, Any]] = None) -> List[Tuple[str, str, str]]:
    """(level, rule, message) for one LLM tool config: rules ``llm-config``, ``llm-catalog``,
    ``llm-annotations`` (docs/architecture/Tool Quality.md §3)."""
    try:
        reg = None
        try:
            from sajha.core.prompts_registry import PromptsRegistry
            reg = PromptsRegistry._instance
        except Exception:
            reg = None
        spec = parse_llm_block(config, reg)
    except LLMConfigError as e:
        return [("error", "llm-config", p) for p in e.problems]
    out = [("error", "llm-catalog", p) for p in catalog_problems(spec, name, registry, strict=True)]
    if not _is_llm_implementation(config.get("implementation")):
        out.append(("error", "llm-config", f"an llm block needs implementation {IMPLEMENTATION} (or a subclass)"))
    claimed = declared if declared is not None else (config.get("annotations") or {})
    if isinstance(claimed, dict) and registry is not None:
        derived = derived_annotations(spec, name, registry)
        if claimed.get("readOnlyHint") is True and not derived["readOnlyHint"]:
            out.append(("warning", "llm-annotations", "the config claims readOnlyHint, but a tool it may call is not "
                                                      "read-only; the derived value (false) is used"))
        if claimed.get("destructiveHint") is False and derived["destructiveHint"]:
            out.append(("warning", "llm-annotations", "the config claims destructiveHint false, but a tool it may "
                                                      "call is destructive; the derived value (true) is used"))
        if claimed.get("openWorldHint") is False and derived["openWorldHint"]:
            out.append(("warning", "llm-annotations", "the config claims openWorldHint false, but a tool it may call "
                                                      "reaches outside the server; the derived value is used"))
    return out
