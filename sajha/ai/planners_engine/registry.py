"""
SAJHA MCP Server — the planner registry: files, versions, reload with last-good fallback.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Reference: docs/architecture/Planner Reference.md §2 and LLM Tools.md §9.9, §9.10, §9.12.

``config/planners/<name>.yaml`` (and ``<name>@<version>.yaml`` for kept older versions) are read
with plain ``yaml.safe_load`` through the storage backend (``ai.planners.dir``). Every file is
validated (P001–P071); one that fails never replaces the last good version of its
``name@version`` (the error is logged and ``sajha_planner_load_errors_total`` counts it). Python
planners take part as ``kind: python`` files, as ``@register_planner`` registrations and as
``package.module:Class`` references. The four built-in strategies (react, plan_execute, recipes,
router) ship as files; their Python classes run instead only when ``ai.planners.python_builtins``
is true, or when a class path names them.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

import yaml

from sajha.ai.planners_engine import metrics
from sajha.ai.planners_engine.model import (Diagnostic, PlannerDef, PlannerError, apply_overlay, compile_planner,
                                            parse_ref, semver_key)
from sajha.ai.planners_engine.settings import PlannerSettings, planner_settings

logger = logging.getLogger(__name__)

PY_BUILTINS = ("react", "plan_execute", "recipes", "router")
NESTING_KINDS = ("planner", "choice", "foreach", "sample")


@dataclass
class Entry:
    name: str
    version: str
    kind: str                         # graph | python
    source: str                       # file | python
    doc: Any = None
    file: str = ""
    pdef: Optional[PlannerDef] = None  # compiled without overlays
    cls: Any = None
    warnings: List[Diagnostic] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"


class UnknownPlanner(ValueError):
    pass


def _check_alias(alias: str) -> bool:
    try:
        from sajha.ai.llm import llm_factory
        gw = llm_factory()
    except Exception:
        gw = None
    if gw is None:
        return True
    aliases = getattr(getattr(gw, "settings", None), "aliases", {}) or {}
    if alias in aliases:
        return True
    if "/" in alias:
        return alias.split("/", 1)[0] in (getattr(gw, "providers", {}) or {})
    return False


def _check_prompt(name: str) -> bool:
    try:
        from sajha.core.prompts_registry import PromptsRegistry
        reg = PromptsRegistry._instance
    except Exception:
        reg = None
    return True if reg is None else reg.get_prompt(name) is not None


class PlannerRegistry:
    def __init__(self, storage: Any = None, settings: Optional[PlannerSettings] = None, directory: Optional[str] = None):
        self._storage = storage
        self.settings = settings or planner_settings()
        self.dir = (directory or self.settings.dir).rstrip("/")
        self.files: Dict[str, Dict[str, Entry]] = {}       # name -> version -> last good entry
        self.errors: Dict[str, List[Diagnostic]] = {}      # file -> diagnostics of its last load
        self.warnings: Dict[str, List[Diagnostic]] = {}
        self._digests: Dict[Tuple[str, str], str] = {}
        self._sig: Optional[Tuple] = None
        self._checked = 0.0
        self._cache: Dict[str, PlannerDef] = {}
        self._lock = threading.RLock()
        self._eval_cache: Dict[str, Tuple[float, List[str]]] = {}

    # ── storage ───────────────────────────────────────────────────
    def storage(self):
        if self._storage is not None:
            return self._storage
        from sajha.core.storage import get_storage
        return get_storage()

    def _listing(self) -> List[str]:
        st = self.storage()
        out = []
        for pat in ("*.yaml", "*.yml", "*.json"):
            try:
                out.extend(p for p in st.list_files(self.dir, pat)
                           if PurePosixPath(p).parent.as_posix() == PurePosixPath(self.dir).as_posix())
            except Exception as e:
                logger.debug(f"planners: cannot list {self.dir}: {e}")
        return sorted(set(out), key=lambda p: PurePosixPath(p).name)

    def _signature(self, paths: List[str]) -> Tuple:
        st = self.storage()
        sig = []
        for p in paths:
            try:
                sig.append((p, st.get_modified_time(p)))
            except Exception:
                sig.append((p, 0))
        return tuple(sig)

    def invalidate(self) -> None:
        with self._lock:
            self._sig = None
            self._checked = 0.0
            self._cache.clear()

    def maybe_reload(self) -> None:
        if getattr(self, "_loading", False):
            return
        now = time.time()
        if self._sig is not None and now - self._checked < self.settings.reload_interval_s:
            return
        self._checked = now
        paths = self._listing()
        sig = self._signature(paths)
        if sig != self._sig:
            self.load(paths, sig)

    # ── loading ───────────────────────────────────────────────────
    def _python_registrations(self) -> Dict[str, Any]:
        from sajha.ai.planners import registered_planners
        return registered_planners()

    def load(self, paths: Optional[List[str]] = None, sig: Optional[Tuple] = None) -> None:
        """(Re)read every planner file; a file that fails keeps its last good version in use."""
        with self._lock:
            self._loading = True
            try:
                self._load(paths, sig)
            finally:
                self._loading = False

    def _load(self, paths: Optional[List[str]], sig: Optional[Tuple]) -> None:
        if True:
            paths = self._listing() if paths is None else paths
            st = self.storage()
            py = self._python_registrations()
            fresh: Dict[str, Dict[str, Entry]] = {}
            errors: Dict[str, List[Diagnostic]] = {}
            failed: Dict[Tuple[str, str], str] = {}
            seen_files: Dict[Tuple[str, str], str] = {}
            ceil = self.settings.ceilings()
            for p in paths:
                fname = PurePosixPath(p).name
                stem = fname.rsplit(".", 1)[0]
                try:
                    doc = yaml.safe_load(st.read_text(p))
                except Exception as e:
                    errors[fname] = [Diagnostic("P001", "error", "", f"not a planner file ({e.__class__.__name__}: "
                                                                     f"{str(e)[:200]})")]
                    metrics.load_error(stem.split("@")[0])
                    continue
                try:
                    pdef = compile_planner(doc, file_stem=stem, ceilings=ceil, check_alias=_check_alias,
                                           check_prompt=_check_prompt, file=p)
                except PlannerError as e:
                    errors[fname] = e.diagnostics
                    nm = doc.get("name") if isinstance(doc, dict) else stem
                    ver = doc.get("version") if isinstance(doc, dict) else ""
                    failed[(str(nm), str(ver))] = fname
                    metrics.load_error(str(nm))
                    logger.warning(f"planner file {fname} refused: {e}")
                    continue
                key = (pdef.name, pdef.version)
                if key in seen_files:
                    errors[fname] = [Diagnostic("P005", "error", "", f"{pdef.ref} is also defined in {seen_files[key]}")]
                    metrics.load_error(pdef.name)
                    continue
                if pdef.name in py and pdef.name not in PY_BUILTINS:
                    errors[fname] = [Diagnostic("P005", "error", "", f"{pdef.ref} is also registered as the Python "
                                                                     f"planner {py[pdef.name].__module__}:"
                                                                     f"{py[pdef.name].__name__}")]
                    metrics.load_error(pdef.name)
                    continue
                seen_files[key] = fname
                warns = list(pdef.warnings)
                old = self._digests.get(key)
                if old is not None and old != pdef.digest:
                    warns.append(Diagnostic("P070", "warning", "version", f"content changed but version is still "
                                                                          f"{pdef.version}"))
                self._digests[key] = pdef.digest
                pdef.warnings = warns
                fresh.setdefault(pdef.name, {})[pdef.version] = Entry(pdef.name, pdef.version, pdef.kind, "file", doc,
                                                                      p, pdef, pdef.cls, warns)
                if warns:
                    self.warnings[fname] = warns
            # last good: a refused file keeps the version it replaced
            for (nm, ver), fname in failed.items():
                prev = self.files.get(nm, {}).get(ver)
                if prev is not None and ver not in fresh.get(nm, {}):
                    fresh.setdefault(nm, {})[ver] = prev
                    logger.warning(f"planner {nm}@{ver}: keeping the last good version ({fname} failed validation)")
            self.files = fresh
            self.errors = errors
            self._cache.clear()
            # link: sub-planner references (P033 P034 P035), which need every file
            for nm in list(self.files):
                for ver, entry in list(self.files[nm].items()):
                    if entry.kind != "graph":
                        continue
                    diags = self.link(entry.pdef, {})
                    errs = [d for d in diags if d.level == "error"]
                    entry.warnings = list(entry.pdef.warnings) + [d for d in diags if d.level == "warning"]
                    if errs:
                        fname = PurePosixPath(entry.file).name
                        self.errors[fname] = self.errors.get(fname, []) + errs
                        metrics.load_error(nm)
                        logger.warning(f"planner {entry.ref} refused: {errs[0].render(entry.ref)}")
                        del self.files[nm][ver]
                if not self.files.get(nm):
                    self.files.pop(nm, None)
            self._sig = sig if sig is not None else self._signature(paths)
            self._checked = time.time()

    # ── resolution ────────────────────────────────────────────────
    def entry(self, ref: str) -> Entry:
        """``name``, ``name@latest``, ``name@1.2.0`` or ``package.module:Class``."""
        self.maybe_reload()
        ref = str(ref or "").strip()
        from sajha.ai.planners import ALIASES
        if ":" in ref:
            from sajha.ai.planners import planner_class
            cls = planner_class(ref)
            return Entry(cls.name or ref, getattr(cls, "version", "") or "0.0.0", "python", "python", cls=cls)
        ref = ALIASES.get(ref, ref)
        try:
            name, version = parse_ref(ref)
        except ValueError as e:
            raise UnknownPlanner(str(e))
        versions = self.files.get(name) or {}
        py = self._python_registrations()
        if name in py and (name not in PY_BUILTINS or self.settings.python_builtins or not versions):
            cls = py[name]
            v = str(getattr(cls, "version", "") or "1.0.0")
            if version is None or version == v or (name in PY_BUILTINS and not versions):
                return Entry(name, v, "python", "python", cls=cls)
        if versions:
            if version is None:
                v = max(versions, key=semver_key)
                return versions[v]
            if version in versions:
                return versions[version]
            raise UnknownPlanner(f"planner {name}@{version} not found (versions: {', '.join(sorted(versions, key=semver_key))})")
        known = sorted(set(self.files) | set(py))
        raise UnknownPlanner(f"unknown planner {ref!r}; known: {', '.join(known)} (or give package.module:Class)")

    def names(self) -> List[str]:
        self.maybe_reload()
        return sorted(set(self.files) | set(self._python_registrations()))

    def use_when(self, ref: str) -> str:
        try:
            e = self.entry(ref)
        except ValueError:
            return ""
        if e.pdef is not None:
            return e.pdef.use_when
        return str(getattr(e.cls, "use_when", "") or getattr(e.cls, "description", "") or "")

    def compiled(self, ref: Any, overlays: Optional[Dict[str, Dict[str, Any]]] = None) -> PlannerDef:
        """The planner a run uses for ``ref``: compiled with the run's overlay for that name."""
        overlays = dict(overlays or {})
        if isinstance(ref, dict):                                   # an overlay object {use, settings, models}
            base = self.entry(ref["use"])
            ov = dict(overlays.get(base.name) or {})
            if ref.get("settings"):
                ov["settings"] = {**(ov.get("settings") or {}), **ref["settings"]}
            if ref.get("models"):
                ov["models"] = {**(ov.get("models") or {}), **ref["models"]}
            overlays[base.name] = ov
            ref = base.ref
        e = self.entry(ref)
        ov = overlays.get(e.name) or {}
        if e.kind == "python" and e.pdef is None:
            settings = dict(ov.get("settings") or {})
            try:
                e.cls.config_model(**settings)
            except Exception as ex:
                raise ValueError(f"settings for the Python planner {e.name}: {ex}".replace("\n", " "))
            return PlannerDef(name=e.name, version=e.version, kind="python", cls=e.cls, settings=settings,
                              description=str(getattr(e.cls, "description", "") or ""),
                              use_when=str(getattr(e.cls, "use_when", "") or getattr(e.cls, "description", "") or ""))
        if not ov:
            return e.pdef
        key = json.dumps([e.ref, ov], sort_keys=True, default=str)
        if key in self._cache:
            return self._cache[key]
        pdef = compile_planner(e.doc, file_stem=None, ceilings=self.settings.ceilings(), overlay=ov,
                               check_alias=_check_alias, check_prompt=_check_prompt, file=e.file,
                               overlay_where=f"overlay of {e.name}")
        errs = [d for d in self.link(pdef, overlays) if d.level == "error"]
        if errs:
            raise PlannerError(pdef.ref, errs)
        self._cache[key] = pdef
        return pdef

    for_run = compiled

    def rules_from(self, spec: str, overlays: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        ref, _, stage = spec.rpartition(".")
        pdef = self.compiled(ref, overlays)
        st = pdef.stages.get(stage)
        if st is None or st.type != "match":
            raise ValueError(f"rules_from {spec}: {stage} is not a match stage of {pdef.ref}")
        if st.cfg.get("rules_from"):
            return self.rules_from(st.cfg["rules_from"], overlays)
        return list(st.cfg.get("rules") or [])

    def link(self, pdef: PlannerDef, overlays: Dict[str, Any], _stack: Optional[List[str]] = None) -> List[Diagnostic]:
        """P033 (missing), P034 (cycle), P035 (depth) and P071 (unpinned) for ``pdef``'s references."""
        out: List[Diagnostic] = []
        stack = list(_stack or []) + [pdef.name]
        max_depth = self.settings.limits.max_subplanner_depth

        def depth_of(p: PlannerDef, chain: List[str]) -> int:
            best = 1 if any(s.type == "foreach" and s.compiled.get("do") for s in p.stages.values()) else 0
            for sid, kind, ref in p.refs:
                if kind not in NESTING_KINDS:
                    continue
                name = ref["use"] if isinstance(ref, dict) else ref
                try:
                    sub = self.compiled(name, overlays)
                except Exception:
                    continue
                if sub.name in chain:
                    continue
                best = max(best, 1 + (depth_of(sub, chain + [sub.name]) if sub.kind == "graph" else 0))
            return best

        for sid, kind, ref in pdef.refs:
            name = ref["use"] if isinstance(ref, dict) else ref
            if not isinstance(name, str):
                continue
            ref_name = name.split(".")[0] if kind.startswith("rules_from") else name
            try:
                e = self.entry(ref_name)
            except ValueError as ex:
                out.append(Diagnostic("P033", "error", f"stages.{sid}", f'stage "{sid}": planner "{ref_name}" not '
                                                                       f'found ({ex})'))
                continue
            if "@" not in ref_name and ":" not in ref_name:
                out.append(Diagnostic("P071", "warning", f"stages.{sid}", f'stage "{sid}": planner "{ref_name}" is not '
                                                                         f'pinned (resolves to {e.ref})'))
            if kind not in NESTING_KINDS:
                continue
            if e.name in stack:
                out.append(Diagnostic("P034", "error", f"stages.{sid}", "planner cycle: " + " -> ".join(stack + [e.name])))
                continue
            if e.kind == "graph" and e.pdef is not None:
                sub_diags = self.link(e.pdef, overlays, stack)
                cyc = [d for d in sub_diags if d.code == "P034"]
                out.extend(cyc[:1])
        if not _stack:
            try:
                d = depth_of(pdef, [pdef.name])
            except RecursionError:
                d = 99
            if d > max_depth:
                out.append(Diagnostic("P035", "error", "stages", f"sub-planner depth {d} exceeds {max_depth} "
                                                                 f"({pdef.name} > ...)"))
        return out

    # ── building a planner for a run ──────────────────────────────
    def build(self, ref: Any = None, *, overlays: Optional[Dict[str, Any]] = None, tool: str = "",
              choices: Optional[List[str]] = None, input: Optional[Dict[str, Any]] = None,
              force_model: Optional[str] = None, by: str = "", output_schema: Optional[Dict[str, Any]] = None,
              inline_defaults: Optional[Dict[str, str]] = None):
        from sajha.ai.planners_engine.runtime import GraphPlanner
        ref = ref if ref is not None else self.settings.default
        if isinstance(ref, dict) and "use" not in ref:                 # an inline planner definition
            pdef = self.inline(ref, inline_defaults or {}, overlays)
        else:
            pdef = self.compiled(ref, overlays)
        if pdef.kind == "python":
            cls = pdef.cls
            if pdef.name in PY_BUILTINS and cls.__module__ == "sajha.ai.planners":
                from sajha.ai.planners import build_planner
                raw = {k: dict((v or {}).get("settings") or {}) for k, v in (overlays or {}).items()}
                return build_planner(cls.name, raw)
            return cls(cls.config_model(**(pdef.settings or {})), factory=lambda n: self.build(n, overlays=overlays))
        return GraphPlanner(pdef, self, overlays=overlays, tool=tool, choices=choices, input=input,
                            force_model=force_model, by=by, output_schema=output_schema)

    def inline(self, doc: Dict[str, Any], defaults: Dict[str, str], overlays: Optional[Dict[str, Any]] = None
               ) -> PlannerDef:
        pdef = compile_planner(doc, ceilings=self.settings.ceilings(), check_alias=_check_alias,
                               check_prompt=_check_prompt, inline_defaults=defaults)
        errs = [d for d in self.link(pdef, overlays or {}) if d.level == "error"]
        if errs:
            raise PlannerError(pdef.ref, errs)
        return pdef

    # ── automatic selection: eval filtering of a planner menu (§6.6.1) ──
    def eval_filter(self, tool: str, labels: List[str]) -> List[str]:
        if not tool or not labels:
            return labels
        hit = self._eval_cache.get(tool)
        if hit is not None and time.time() - hit[0] < 60:
            failing = hit[1]
        else:
            failing = []
            try:
                from sajha.quality.evals import load_sets
                from sajha.quality.store import get_run_store
                sets = {n for n, es in load_sets().items() if es.tool == tool or tool in (es.tools or [])}
                latest: Dict[str, Dict[str, Any]] = {}
                if sets:
                    for run in get_run_store().list("eval", limit=200):
                        s = run.get("summary") or {}
                        if s.get("set") in sets and s.get("planner") and s["planner"] not in latest:
                            latest[s["planner"]] = s
                floor = float(self.settings.menu_min_pass_rate)
                failing = [p for p, s in latest.items() if float(s.get("pass_rate", 1.0)) < floor]
            except Exception as e:
                logger.debug(f"planner menu eval filter: {e}")
            self._eval_cache[tool] = (time.time(), failing)
        return [lab for lab in labels if lab.split("@")[0] not in failing and lab not in failing]

    # ── views ─────────────────────────────────────────────────────
    def describe(self) -> List[Dict[str, Any]]:
        self.maybe_reload()
        out = []
        for name in self.names():
            try:
                e = self.entry(name)
            except ValueError:
                continue
            if e.pdef is not None:
                out.append({"name": e.name, "version": e.version, "kind": e.kind, "source": "file",
                            "file": e.file, "description": e.pdef.description, "use_when": e.pdef.use_when,
                            "versions": sorted(self.files.get(name, {}), key=semver_key),
                            "warnings": [w.to_dict() for w in e.warnings]})
            else:
                cls = e.cls
                out.append({"name": e.name, "version": e.version, "kind": "python", "source": "python",
                            "class": f"{cls.__module__}:{cls.__name__}",
                            "description": str(getattr(cls, "description", "") or ""),
                            "use_when": str(getattr(cls, "use_when", "") or ""), "versions": [e.version]})
        return out

    def problems(self) -> Dict[str, List[Dict[str, Any]]]:
        self.maybe_reload()
        out = {f: [d.to_dict() for d in ds] for f, ds in self.errors.items()}
        for f, ds in self.warnings.items():
            out.setdefault(f, []).extend(d.to_dict() for d in ds if d.to_dict() not in out.get(f, []))
        return out


# ── the process registry ─────────────────────────────────────────

_registry: Optional[PlannerRegistry] = None
_reg_lock = threading.Lock()


def get_registry() -> PlannerRegistry:
    global _registry
    if _registry is None:
        with _reg_lock:
            if _registry is None:
                _registry = PlannerRegistry()
    return _registry


def peek_registry() -> Optional[PlannerRegistry]:
    return _registry


def set_registry(reg: Optional[PlannerRegistry]) -> None:
    """Install a registry (tests); None builds a fresh one on next use."""
    global _registry
    _registry = reg


def ask_overlays(planner_config: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """``ai.ask.planner_config`` ({name: settings}) as overlays keyed by planner name."""
    return {k: {"settings": dict(v or {})} for k, v in (planner_config or {}).items()}


def validate_ask(planner: str, planner_config: Optional[Dict[str, Dict[str, Any]]] = None,
                 registry: Optional[PlannerRegistry] = None) -> None:
    """Fail at start-up on an unknown ``ai.ask.planner`` or invalid ``ai.ask.planner_config``."""
    reg = registry or get_registry()
    ov = ask_overlays(planner_config)
    for name in planner_config or {}:
        try:
            reg.entry(name)
        except ValueError:
            raise ValueError(f"ai.ask.planner_config names an unknown planner {name!r}")
        try:
            reg.compiled(name, ov)
        except (PlannerError, ValueError) as e:
            raise ValueError(f"ai.ask.planner_config.{name}: {e}")
    try:
        reg.compiled(planner or reg.settings.default, ov)
    except UnknownPlanner:
        raise
    except PlannerError as e:
        raise ValueError(f"ai.ask.planner {planner!r}: {e}")


OVERLAY_KEYS = {"use", "settings", "models", "planners"}


def tool_overlays(planner: Any) -> Dict[str, Dict[str, Any]]:
    """An LLM tool's ``planners`` overlays (§2.5) keyed by planner name."""
    if isinstance(planner, dict) and isinstance(planner.get("planners"), dict):
        return {k: dict(v or {}) for k, v in planner["planners"].items()}
    return {}


def check_tool_planner(planner: Any, tool_name: str, version: Any = None) -> Any:
    """Validate an LLM tool's ``llm.planner`` (or one ``planner_choices`` entry) at load; returns it."""
    reg = get_registry()
    if isinstance(planner, str) and planner.strip():
        reg.compiled(planner.strip())
        return planner.strip()
    if isinstance(planner, dict):
        if "use" in planner:
            unknown = set(planner) - OVERLAY_KEYS
            if unknown:
                raise ValueError(f"an overlay takes {sorted(OVERLAY_KEYS)}, not {sorted(unknown)}")
            reg.compiled({k: v for k, v in planner.items() if k != "planners"}, tool_overlays(planner))
            return planner
        reg.inline(planner, inline_defaults(tool_name, version))
        return planner
    raise ValueError("must be a planner reference (name or name@version), an inline definition or an overlay "
                     "{use, settings, models}")


def inline_defaults(tool_name: str, version: Any) -> Dict[str, str]:
    import re
    from sajha.ai.planners_engine.model import SEMVER
    name = re.sub(r"[^a-z0-9_]", "_", str(tool_name or "tool").lower())
    if not name[:1].isalpha():
        name = "t_" + name
    ver = str(version or "")
    return {"name": f"{name[:55]}__inline", "version": ver if SEMVER.match(ver) else "1.0.0"}


def lint_findings(registry: Optional[PlannerRegistry] = None) -> List[Tuple[str, str, str, str, str]]:
    """(file, level, code, message, location) for every planner file: load errors, warnings and the
    registry's link warnings (unpinned sub-planners, P071)."""
    reg = registry or get_registry()
    reg.maybe_reload()
    out = []
    for fname, diags in sorted(reg.errors.items()):
        out.extend((fname, d.level, d.code, d.render(fname.rsplit(".", 1)[0]), d.location) for d in diags)
    for name in sorted(reg.files):
        for ver, e in sorted(reg.files[name].items()):
            fname = PurePosixPath(e.file).name
            out.extend((fname, d.level, d.code, d.render(e.ref), d.location) for d in e.warnings
                       if (fname, d.level, d.code, d.render(e.ref), d.location) not in out)
    return out


def tool_name_problems(planner: Any, allowed: List[str], tool_name: str = "") -> List[str]:
    """P036: every ``call`` tool and ``act`` tools.allow pattern of the planner (and its literal
    sub-planners) must match a tool the LLM tool's ``tools.allow`` permits."""
    import fnmatch
    reg = get_registry()
    if isinstance(planner, dict) and "use" not in planner:
        pdef = reg.inline(planner, inline_defaults(tool_name, None))
    else:
        pdef = reg.compiled({k: v for k, v in planner.items() if k != "planners"} if isinstance(planner, dict)
                            else planner, tool_overlays(planner))
    out: List[str] = []
    seen = set()

    def walk(p: PlannerDef) -> None:
        if p.ref in seen or p.kind != "graph":
            return
        seen.add(p.ref)
        for sid, st in p.stages.items():
            names = []
            if st.type == "call" and st.cfg.get("tool"):
                names.append(st.cfg["tool"])
            if st.type == "act" and isinstance(st.cfg.get("tools"), dict):
                names.extend(st.cfg["tools"].get("allow") or [])
            for n in names:
                if not any(fnmatch.fnmatchcase(a, n) for a in allowed):
                    out.append(f'planner {p.ref}: P036 stage "{sid}": tool "{n}" matches no allowed tool')
        for _sid, kind, ref in p.refs:
            if kind in ("planner", "foreach", "sample") and isinstance(ref, str):
                try:
                    walk(reg.compiled(ref))
                except Exception:
                    pass
    walk(pdef)
    return out
