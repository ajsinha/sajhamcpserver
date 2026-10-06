"""
SAJHA Intelligence Layer — configuration.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Every setting of the intelligence layer is a field of a pydantic model, so every setting
is validated at startup, documented in one place, and overridable from the environment.

Precedence for each field, highest first:

    1. SAJHA_AI_<SECTION>_<FIELD>          e.g. SAJHA_AI_OPENAI_BASE_URL, SAJHA_AI_ASK_MAX_STEPS
    2. the vendor's own variable           e.g. OPENAI_API_KEY, OLLAMA_HOST  (providers only)
    3. config/application.yml  ai.*        (the raw YAML, ${VAR:default} substituted)
    4. the llm_providers / llm_models DB tables (providers only; written by the AI settings page)
    5. the code default

<SECTION> is the provider's name upper-cased with non-alphanumerics as "_" (azure_openai ->
AZURE_OPENAI), or a gateway section (ALIASES, POLICY, BUDGETS, CACHE, RETRY, BREAKER,
GATEWAY, ASK). Scalars are parsed by the field's type; lists accept JSON or a comma list;
dicts and lists of objects take JSON.

Each resolved value remembers where it came from (``default`` | ``config`` | ``env:NAME`` |
``db``), which the admin endpoint ``GET /api/ai/config`` reports with secrets redacted.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple, Type, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

logger = logging.getLogger(__name__)

_VAR = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")
SECRET_FIELDS = {"api_key", "aws_secret_access_key", "aws_session_token"}
REDACTED = "********"


# ── Raw YAML (ai.* is nested and contains lists, so it is not read through _CFG) ──

def _subst(obj: Any) -> Any:
    if isinstance(obj, str):
        return _VAR.sub(lambda m: os.environ.get(m.group(1), m.group(2) if m.group(2) is not None else ""), obj)
    if isinstance(obj, dict):
        return {k: _subst(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_subst(v) for v in obj]
    return obj


def load_ai_yaml(path: Optional[str] = None) -> Dict[str, Any]:
    """The ``ai:`` section of application.yml as nested Python data (``${VAR:default}`` substituted)."""
    path = path or os.environ.get("SAJHA_CONFIG_FILE", "config/application.yml")
    p = Path(path)
    if not p.is_absolute():
        p = Path.cwd() / p
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:      # a broken YAML is reported by the main config loader too
        logger.warning(f"ai config: cannot read {p}: {e}")
        return {}
    return _subst(data.get("ai") or {})


def env_prefix(section: str) -> str:
    return "SAJHA_AI_" + re.sub(r"[^A-Za-z0-9]", "_", section).upper() + "_"


# ── Field coercion from strings (env) ──────────────────────────────

def _annotation_kind(annotation: Any) -> str:
    """'json' for dict/list-of-objects fields, 'list' for list[str], else 'scalar'."""
    text = str(annotation)
    if "Dict" in text or "dict" in text:
        return "json"
    if ("List" in text or "list" in text) and ("str" in text and "Override" not in text
                                               and "Dict" not in text):
        return "list"
    if "List" in text or "list" in text or "Tuple" in text or "tuple" in text:
        return "json"
    return "scalar"


def _coerce_env(raw: str, annotation: Any) -> Any:
    kind = _annotation_kind(annotation)
    s = raw.strip()
    if kind == "json":
        return json.loads(s) if s else None
    if kind == "list":
        if s.startswith("["):
            return json.loads(s)
        return [x.strip() for x in s.split(",") if x.strip()]
    return raw


# ── Generic layered resolution ────────────────────────────────────

class Layered(BaseModel):
    """Base for every config model: forbid unknown keys so typos fail at startup."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True, protected_namespaces=())

    # field -> vendor environment variables, highest priority first (providers set this)
    vendor_env: ClassVar[Dict[str, List[str]]] = {}


def resolve_layers(model_cls: Type[Layered], section: str, config: Optional[Dict[str, Any]] = None,
                   db: Optional[Dict[str, Any]] = None, environ: Optional[Dict[str, str]] = None,
                   ) -> Tuple[Layered, Dict[str, str]]:
    """Build ``model_cls`` from env > vendor env > config > db > default. Returns (model, sources)."""
    environ = os.environ if environ is None else environ
    config = dict(config or {})
    db = dict(db or {})
    values: Dict[str, Any] = {}
    sources: Dict[str, str] = {}
    prefix = env_prefix(section)
    for name, finfo in model_cls.model_fields.items():
        keys = [name] + ([finfo.alias] if finfo.alias else [])
        env_name = prefix + name.upper()
        if env_name in environ:
            try:
                values[name] = _coerce_env(environ[env_name], finfo.annotation)
                sources[name] = f"env:{env_name}"
                continue
            except Exception as e:
                raise ValueError(f"{env_name}: cannot parse {environ[env_name]!r}: {e}")
        hit = False
        for vendor_var in model_cls.vendor_env.get(name, []):
            v = environ.get(vendor_var)
            if v not in (None, ""):
                values[name] = _coerce_env(v, finfo.annotation)
                sources[name] = f"env:{vendor_var}"
                hit = True
                break
        if hit:
            continue
        for k in keys:
            if k in config and config[k] is not None and config[k] != "":
                values[name] = config[k]
                sources[name] = "config"
                hit = True
                break
        if hit:
            continue
        if name in db and db[name] not in (None, "", [], {}):
            values[name] = db[name]
            sources[name] = "db"
            continue
        sources[name] = "default"
    unknown = set(config) - set(model_cls.model_fields) - {f.alias for f in model_cls.model_fields.values() if f.alias}
    if unknown:
        raise ValueError(f"ai.{section}: unknown setting(s) {sorted(unknown)}; "
                         f"valid: {sorted(model_cls.model_fields)}")
    try:
        return model_cls(**values), sources
    except ValidationError as e:
        raise ValueError(f"ai.{section}: invalid configuration: {e}") from None


def _plain(value: Any) -> Any:
    if isinstance(value, SecretStr):
        return REDACTED if value.get_secret_value() else ""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def redact(name: str, value: Any) -> Any:
    if name in SECRET_FIELDS and value:
        return REDACTED
    if name == "extra_headers" and isinstance(value, dict):
        return {k: (REDACTED if any(s in k.lower() for s in ("key", "auth", "token", "secret")) else v)
                for k, v in value.items()}
    return _plain(value)


def describe(model: BaseModel, sources: Dict[str, str]) -> Dict[str, Any]:
    """{field: {value (redacted), source}} for the effective-config endpoint."""
    return {name: {"value": redact(name, getattr(model, name)), "source": sources.get(name, "default")}
            for name in type(model).model_fields}


# ── Provider configuration ───────────────────────────────────────

class ModelOverride(Layered):
    """Add a model to a provider, or override a catalog model's capabilities and prices."""
    id: str
    kind: Literal["chat", "embedding"] = "chat"
    display_name: str = ""
    enabled: bool = True                     # false hides a catalog model
    tools: Optional[bool] = None
    structured_output: Optional[bool] = None
    vision: Optional[bool] = None
    streaming: Optional[bool] = None
    temperature: Optional[bool] = None
    forced_tool_choice: Optional[bool] = None
    context_window: Optional[int] = None
    max_output_tokens: Optional[int] = None
    input_cost_per_mtok: Optional[float] = None
    output_cost_per_mtok: Optional[float] = None
    dimensions: Optional[int] = None
    tags: Optional[List[str]] = None
    deployment: Optional[str] = None         # Azure: the deployment that serves this model


class ProviderConfig(Layered):
    """Settings every provider accepts. Subclasses add vendor-specific fields."""
    # false by default: a provider is used only when enabled explicitly (config or
    # SAJHA_AI_<PROVIDER>_ENABLED=true). "auto" = enabled when it has a key (keyless: when
    # its base_url was configured). A key in the environment never enables a provider alone.
    enabled: Union[Literal["auto"], bool] = False
    api_key: Optional[SecretStr] = None
    api_key_ref: Optional[str] = None          # env:NAME | file:/path | db:llm_providers/<type>
    base_url: Optional[str] = None
    extra_headers: Dict[str, str] = Field(default_factory=dict)
    proxy: Optional[str] = None
    verify_tls: bool = True
    ca_bundle: Optional[str] = None
    connect_timeout_s: float = 5.0
    read_timeout_s: float = 120.0
    max_retries: Optional[int] = None          # None -> ai.retry.max_retries
    backoff_base_s: Optional[float] = None     # None -> ai.retry.backoff_base_s
    backoff_max_s: Optional[float] = None      # None -> ai.retry.backoff_max_s
    max_concurrency: int = 8
    default_model: Optional[str] = None
    default_embedding_model: Optional[str] = None
    embedding_dimensions: Optional[int] = None
    default_temperature: Optional[float] = None
    default_max_output_tokens: int = 4096
    streaming: bool = True
    health_timeout_s: float = 2.0
    catalog: bool = True                       # include the built-in curated model list
    models: List[ModelOverride] = Field(default_factory=list)


# ── Gateway and ask sections ─────────────────────────────────────

# Out of the box the mock is the active default: every real provider ships disabled, and
# an alias only names real providers once a deployment points it at them, e.g.
#   SAJHA_AI_ALIASES_DEFAULT=anthropic,ollama,mock/mock-planner
# A bare provider name means that provider's default_model.
DEFAULT_ALIASES: Dict[str, List[str]] = {
    "default": ["mock/mock-planner"],
    "fast": ["mock/mock-planner"],
    "reasoning": ["mock/mock-planner"],
    "embedding": ["mock/mock-embed"],
}


class RolePolicy(Layered):
    allowed: List[str] = Field(default_factory=lambda: ["*"])    # provider/model globs
    tools: bool = True
    max_output_tokens: Optional[int] = None
    daily_tokens: Optional[int] = None


class PolicySettings(Layered):
    enabled: bool = True
    roles: Dict[str, RolePolicy] = Field(default_factory=dict)
    default: Optional[RolePolicy] = None       # for roles not listed; None = unrestricted


class BudgetSettings(Layered):
    enabled: bool = True
    per_user_daily_tokens: Optional[int] = None
    per_role_daily_tokens: Dict[str, int] = Field(default_factory=dict)


class CacheSettings(Layered):
    enabled: bool = True
    ttl_seconds: int = 3600
    max_entries: int = 500
    cache_nonzero_temperature: bool = False


class RetrySettings(Layered):
    max_retries: int = 2
    backoff_base_s: float = 0.5
    backoff_max_s: float = 20.0
    jitter: float = 0.5                        # +/- fraction of the delay
    max_retry_after_s: float = 30.0            # never sleep longer than this on a Retry-After


class BreakerSettings(Layered):
    enabled: bool = True
    failure_threshold: int = 5
    recovery_timeout_s: int = 60


class GatewaySettings(Layered):
    health_ttl_s: float = 30.0                 # cache provider health for this long
    trace_prompts: bool = False                # include prompts/outputs on spans (debug only)
    load_entry_points: bool = True             # pip plug-ins in group sajha.llm_providers
    use_db_providers: bool = True              # read keys/models from the llm_providers tables


class AskSettings(Layered):
    enabled: bool = True
    model: str = "default"
    max_steps: int = 6
    max_tool_calls: int = 10
    max_tokens: int = 50_000                   # all model calls of one ask
    timeout_s: float = 60.0
    shortlist: int = 12
    max_result_chars: int = 4000
    temperature: float = 0.0
    confirm_destructive: bool = True
    synthesize: bool = True                    # final structured-output call
    audit: bool = True
    mcp_tool_enabled: bool = False
    # sajha_ask has no caller identity for its inner calls: it may run what an anonymous MCP
    # caller may run (mcp.anonymous.*) plus these fnmatch patterns
    mcp_allowed_tools: List[str] = Field(default_factory=list)
    # the planning strategy (sajha/ai/planners.py): a registered name (react, plan_execute,
    # recipes, router; "model" is an alias of react) or package.module:Class
    planner: str = "react"
    # per-planner settings, keyed by planner name, each validated by that planner's config model
    planner_config: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class MemorySettings(Layered):
    """Conversation memory for multi-turn asks (sajha/ai/memory.py)."""
    enabled: bool = True
    history_turns: int = 6                     # most recent turns sent verbatim as context
    max_turn_chars: int = 2000                 # each stored answer is clipped to this
    summarize: bool = True                     # summarise turns older than the verbatim window
    summary_max_chars: int = 2000
    condense: bool = True                      # rewrite a follow-up into a standalone question
    model: str = "fast"                        # alias for the summary and rewrite calls
    retention_days: int = 30                   # conversations idle longer than this are deleted
    max_conversations_per_user: int = 200      # the oldest beyond this are deleted


class RagSource(Layered):
    name: str
    path: str                                  # a folder in the storage backend (storage-relative)
    pattern: str = "*.md"                      # glob of the files to index (md, markdown, txt, rst, html)
    title: str = ""


class RagSettings(Layered):
    """Retrieval over documents (sajha/ai/rag): SAJHA's own guides and admin-configured sources."""
    enabled: bool = True
    index_sajha_docs: bool = True              # docs/** guides (archive excluded)
    sources: List[RagSource] = Field(default_factory=list)
    uploads_dir: str = "data/rag/uploads"      # admin-uploaded files (storage-relative)
    embedding_model: str = "embedding"         # gateway alias; "none" = lexical (BM25) only
    store: Literal["auto", "memory", "pgvector"] = "auto"
    persist: bool = True                       # persist the in-process index through storage
    index_path: str = "data/rag/index.json"
    chunk_chars: int = 1200
    chunk_overlap: int = 150
    top_k: int = 5
    vector_weight: float = 0.5                 # the vector ranking's weight in the fusion (BM25's is 1)
    max_upload_bytes: int = 2_000_000
    build_on_start: bool = True                # build in a background thread at start-up


SECTION_MODELS: Dict[str, Type[Layered]] = {
    "policy": PolicySettings, "budgets": BudgetSettings, "cache": CacheSettings,
    "retry": RetrySettings, "breaker": BreakerSettings, "gateway": GatewaySettings,
    "ask": AskSettings, "memory": MemorySettings, "rag": RagSettings,
}
RESERVED_SECTIONS = set(SECTION_MODELS) | {"aliases", "providers", "tool_search"}


class AISettings:
    """The resolved ai.* configuration (gateway sections, aliases, ask) plus value sources."""

    def __init__(self, raw: Optional[Dict[str, Any]] = None, environ: Optional[Dict[str, str]] = None):
        self.raw = dict(raw or {})
        env = os.environ if environ is None else environ
        self.sources: Dict[str, Dict[str, str]] = {}
        for section, cls in SECTION_MODELS.items():
            cfg = self.raw.get(section) or {}
            if section == "cache":     # legacy keys shared with the old gateway
                cfg = {k: v for k, v in cfg.items() if k in cls.model_fields}
            model, src = resolve_layers(cls, section, cfg, environ=env)
            setattr(self, section, model)
            self.sources[section] = src
        # aliases: dict alias -> ordered candidates
        aliases = {k: list(v) for k, v in DEFAULT_ALIASES.items()}
        alias_src = {k: "default" for k in aliases}
        for k, v in (self.raw.get("aliases") or {}).items():
            aliases[k] = list(v) if isinstance(v, (list, tuple)) else [x.strip() for x in str(v).split(",")]
            alias_src[k] = "config"
        prefix = env_prefix("aliases")
        for name, value in env.items():
            if name.startswith(prefix):
                alias = name[len(prefix):].lower()
                aliases[alias] = _coerce_env(value, List[str])
                alias_src[alias] = f"env:{name}"
        self.aliases: Dict[str, List[str]] = aliases
        self.sources["aliases"] = alias_src

    def describe(self) -> Dict[str, Any]:
        out = {section: describe(getattr(self, section), self.sources[section]) for section in SECTION_MODELS}
        out["aliases"] = {k: {"value": v, "source": self.sources["aliases"].get(k, "default")}
                          for k, v in self.aliases.items()}
        return out
