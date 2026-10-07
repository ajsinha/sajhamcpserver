"""
SAJHA Intelligence Layer — the mock provider.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A full citizen of the registry: no network, no keys, deterministic, and the default when no
real provider is configured, so a fresh install can use the intelligence layer at once.

    mock-echo        replies with the last user message, prefixed; realistic token counts
    mock-scripted    plays a script (ordered replies or regex rules; text, tool calls,
                     structured output, errors), from YAML (scripts_dir) or set in a test;
                     ``mock-scripted:<name>`` plays the script loaded from <name>.yml
    mock-planner     deterministic tool use: scores the offered ToolSpecs against the
                     question's keywords, calls the best one (or two) with arguments filled
                     from the schema (defaults, numbers, symbols in the question), then
                     answers from the tool results
    mock-toolsmith   designs a tool from a description for Studio's "Describe a tool"
                     (structured output only; sajha/ai/llm/mock_toolsmith.py)
    mock-embed       deterministic embeddings from hashed word n-grams (default 256 dims)

The mock speaks the canonical Chat Completions format (chat_completions_create / _stream return
ChatCompletion and chat.completion.chunk objects), so tests and the offline default exercise the
same shapes real providers return. A script step may be ``{text}``, ``{json}``, ``{tool_calls}``,
``{refusal}`` (a content_filter finish with message.refusal), ``{error}`` or ``{sleep_ms}``.

Fault injection (config or per test): latency_ms [lo, hi] (seeded), fail_every N,
fail_with rate_limited | unavailable | auth | context_too_long | content_filtered.
Every call is priced at zero but reports token usage, so budgets and usage pages work.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import random
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Literal, Optional, Tuple, Union

from pydantic import Field

from sajha.ai.llm.errors import ERROR_BY_NAME, InvalidRequest, RateLimited
from sajha.ai.llm.model import (ChatModel, EmbeddingModel, HealthStatus, ModelCapabilities,
                                ModelDescriptor, estimate_tokens)
from sajha.ai.llm.provider import ProviderBase
from sajha.ai.llm.registry import register_provider
from sajha.ai.llm.settings import ProviderConfig
from sajha.ai.llm.canonical import (ChatCompletion, ChatCompletionChunk, ChatCompletionRequest, ChatMessage,
                                    Choice, ChoiceDelta, ChunkChoice, CompletionUsage, DeltaFunction, DeltaToolCall,
                                    ResponseSajha, ToolCall)
from sajha.ai.llm.convert import from_canonical_request
from sajha.ai.llm.types import ChatRequest, ToolCallPart, ToolSpec

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_NUMBER = re.compile(r"(?<![A-Za-z_])-?\d[\d,]*(?:\.\d+)?")
_SYMBOL = re.compile(r"\$?\b[A-Z]{1,5}(?:\.[A-Z]{1,2})?\b")
_STOP = {"what", "is", "the", "a", "an", "of", "to", "from", "for", "and", "or", "in", "on", "at", "by",
         "with", "me", "my", "please", "how", "much", "many", "give", "tell", "show", "calculate",
         "compute", "find", "get", "between", "value", "values", "using", "use", "do", "does", "it",
         "this", "that", "are", "was", "be", "can", "you", "i", "if", "per", "into", "as", "its"}
_NOT_SYMBOLS = {"I", "A", "AN", "THE", "AND", "OR", "OF", "TO", "IS", "IT", "WHAT", "HOW", "USD", "EUR",
                "GBP", "JPY", "CAPM", "IRR", "NPV", "DCF", "WACC", "PE", "EPS", "ETF", "API"}


class MockConfig(ProviderConfig):
    enabled: Union[Literal["auto"], bool] = True      # the out-of-the-box default provider
    latency_ms: List[int] = Field(default_factory=lambda: [0, 0])
    fail_every: int = 0
    fail_with: str = "rate_limited"
    retry_after_s: float = 0.0
    seed: int = 42
    scripts_dir: Optional[str] = "config/ai/mock_scripts"
    embed_dimensions: int = 256
    max_planner_tools: int = 2


def _stem(w: str) -> str:
    w = w.lower()
    for suf in ("ings", "ing", "ies", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def keywords(text: str) -> List[str]:
    out = []
    for w in _WORD.findall(text.replace("_", " ")):
        lw = w.lower()
        if lw in _STOP or len(lw) < 2:
            continue
        out.append(_stem(lw))
    return out


def extract_numbers(text: str) -> List[float]:
    vals = []
    for m in _NUMBER.findall(text):
        s = m.replace(",", "")
        try:
            v = float(s)
        except ValueError:
            continue
        vals.append(int(v) if v.is_integer() and "." not in s else v)
    return vals


def extract_symbols(text: str) -> List[str]:
    syms = []
    for m in _SYMBOL.findall(text):
        s = m.lstrip("$")
        if s not in _NOT_SYMBOLS and s not in syms:
            syms.append(s)
    return syms


class _Script:
    def __init__(self, steps: List[Dict[str, Any]], mode: str = "ordered", loop: bool = False):
        self.steps = list(steps)
        self.mode = mode
        self.loop = loop
        self.cursor = 0
        self.lock = threading.Lock()

    def next_step(self, last_user: str, stage: str = "") -> Dict[str, Any]:
        with self.lock:
            if self.mode == "rules":
                for st in self.steps:
                    if st.get("stage") and st["stage"] != stage:
                        continue          # a reply for one planner stage type (sajha/ai/planners_engine)
                    pat = st.get("match")
                    if pat is None or re.search(pat, last_user or "", re.I):
                        return st
                return {"text": "[mock-scripted: no rule matched]"}
            if self.cursor >= len(self.steps):
                if self.loop and self.steps:
                    self.cursor = 0
                else:
                    return {"text": "[mock-scripted: script exhausted]"}
            st = self.steps[self.cursor]
            self.cursor += 1
            return st


@register_provider
class MockProvider(ProviderBase):
    name = "mock"
    config_model = MockConfig
    requires_key = False
    catalog_key = "mock"
    # the mock declares every canonical feature except native n (so n > 1 exercises the
    # model's n-calls path)
    feature_defaults = {"seed": True, "parallel_tool_control": True, "strict_tools": True,
                        "reasoning_effort": True, "variable_dimensions": True}

    MODELS = {
        "mock-echo": ModelCapabilities(tools=False, structured_output=False, context_window=128_000,
                                       tags=frozenset({"deterministic", "fast", "cheap"})),
        "mock-scripted": ModelCapabilities(tools=True, structured_output=True, context_window=128_000,
                                           tags=frozenset({"deterministic"})),
        "mock-planner": ModelCapabilities(tools=True, structured_output=True, context_window=128_000,
                                          tags=frozenset({"deterministic", "fast", "cheap", "reasoning"})),
        # Studio "Describe a tool": designs a tool from a description (sajha/ai/llm/mock_toolsmith.py)
        "mock-toolsmith": ModelCapabilities(tools=False, structured_output=True, context_window=128_000,
                                            tags=frozenset({"deterministic"})),
    }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._calls = 0
        self._count_lock = threading.Lock()
        self._rng = random.Random(self.config.seed)
        self._scripts: Dict[str, _Script] = {}
        self._load_scripts()

    # scripts
    def _load_scripts(self):
        d = self.config.scripts_dir
        if not d:
            return
        p = Path(d)
        if not p.is_absolute():
            p = Path.cwd() / p
        if not p.is_dir():
            return
        import yaml
        for f in sorted(list(p.glob("*.yml")) + list(p.glob("*.yaml"))):
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    data = {"steps": data}
                self._scripts[f.stem] = _Script(data.get("steps") or [], data.get("mode", "ordered"),
                                                bool(data.get("loop", False)))
            except Exception as e:
                logger.warning(f"mock script {f.name} invalid: {e}")

    def set_script(self, steps: List[Dict[str, Any]], mode: str = "ordered", name: str = "default",
                   loop: bool = False) -> None:
        """Programmatic script for ``mock-scripted`` (name 'default') or ``mock-scripted:<name>``."""
        self._scripts[name] = _Script(steps, mode, loop)

    def script(self, name: str) -> _Script:
        s = self._scripts.get(name)
        if s is None:
            raise InvalidRequest(f"mock: no script named '{name}'", provider=self.name)
        return s

    # fault injection
    def inject(self) -> None:
        lo, hi = (list(self.config.latency_ms) + [0, 0])[:2]
        with self._count_lock:
            self._calls += 1
            n = self._calls
            delay = self._rng.uniform(lo, max(lo, hi)) if hi > 0 else 0
        if delay:
            time.sleep(delay / 1000.0)
        fe = self.config.fail_every
        if fe and n % fe == 0:
            cls = ERROR_BY_NAME.get(self.config.fail_with, RateLimited)
            msg = f"mock: injected {self.config.fail_with} on call {n}"
            if cls is RateLimited:
                raise RateLimited(msg, retry_after=self.config.retry_after_s, provider=self.name)
            raise cls(msg, provider=self.name)

    @property
    def calls(self) -> int:
        return self._calls

    # catalogue
    def list_models(self) -> List[ModelDescriptor]:
        out = [ModelDescriptor(mid, caps, source="builtin") for mid, caps in self.MODELS.items()]
        out += [ModelDescriptor(f"mock-scripted:{n}", self.MODELS["mock-scripted"], source="script")
                for n in self._scripts if n != "default"]
        dims = self.config.embedding_dimensions or self.config.embed_dimensions
        out.append(ModelDescriptor("mock-embed", ModelCapabilities(chat=False, embedding=True, streaming=False,
                                                                   dimensions=dims,
                                                                   tags=frozenset({"deterministic"})),
                                   kind="embedding", source="builtin"))
        return out

    def default_chat_model_id(self) -> str:
        return self.config.default_model or "mock-planner"

    def default_embedding_model_id(self) -> str:
        return self.config.default_embedding_model or "mock-embed"

    def chat_model(self, model_id: str = "", **options) -> ChatModel:
        model_id = model_id or self.default_chat_model_id()
        base = model_id.split(":", 1)[0]
        caps = self.MODELS.get(base)
        if caps is None:
            from sajha.ai.llm.errors import UnsupportedFeature
            raise UnsupportedFeature(f"mock has no model '{model_id}'", provider=self.name, model=model_id)
        if base == "mock-toolsmith":
            from sajha.ai.llm.mock_toolsmith import ToolsmithModel
            return ToolsmithModel(self, model_id, caps, **options)
        cls = {"mock-echo": EchoModel, "mock-scripted": ScriptedModel, "mock-planner": PlannerModel}[base]
        return cls(self, model_id, caps, **options)

    def embedding_model(self, model_id: str = "") -> EmbeddingModel:
        dims = self.config.embedding_dimensions or self.config.embed_dimensions
        return HashEmbeddingModel(self, model_id or "mock-embed", dims)

    def health(self) -> HealthStatus:
        if self.config.enabled is False:
            return HealthStatus("down", "disabled")
        return HealthStatus("ok", "mock (offline)")


# ── models ────────────────────────────────────────────────────────

class _MockChat(ChatModel):
    """The mock speaks the canonical format: ``_create`` returns a ChatCompletion and ``_stream``
    yields chat.completion.chunk objects, word by word, with tool-call arguments in two fragments.
    Subclasses decide the reply in ``_reply(legacy_request) -> (text, tool_calls, finish)`` (a
    lossless legacy view of the request, convenient for the keyword planner); a scripted step can
    also return a refusal."""

    def _reply(self, request: ChatRequest) -> Tuple[str, List[ToolCallPart], str]:
        raise NotImplementedError

    def _refusal(self) -> Optional[str]:
        return None

    def _create(self, request: ChatCompletionRequest) -> ChatCompletion:
        self.provider.inject()
        legacy = from_canonical_request(request)
        text, calls, finish = self._reply(legacy)
        refusal = getattr(self, "_last_refusal", None)
        self._last_refusal = None
        tcs = [ToolCall.of(c.id, c.name, c.arguments) for c in calls]
        msg = ChatMessage(role="assistant", content=text or None, tool_calls=tcs or None)
        if refusal:
            msg.refusal, msg.content, finish = refusal, None, "content_filter"
        out_tokens = estimate_tokens(text + (refusal or "") + "".join(json.dumps(c.arguments) + c.name for c in calls))
        usage = CompletionUsage.of(self.count_tokens(request), out_tokens)
        return ChatCompletion(model=self.id, choices=[Choice(message=msg, finish_reason=finish)], usage=usage,
                              sajha=ResponseSajha(provider=self.provider.name, cost_usd=0.0))

    def _stream(self, request: ChatCompletionRequest) -> Iterator[ChatCompletionChunk]:
        comp = self._create(request)
        base = dict(id=comp.id, created=comp.created, model=comp.model)
        first = True

        def delta(**kw):
            nonlocal first
            d = ChoiceDelta(role="assistant" if first else None, **kw)
            first = False
            return ChatCompletionChunk(**base, choices=[ChunkChoice(delta=d)])

        for w in re.findall(r"\S+\s*", comp.text):
            yield delta(content=w)
        for i, c in enumerate(comp.tool_calls):
            args = c.function.arguments
            mid = len(args) // 2
            yield delta(tool_calls=[DeltaToolCall(index=i, id=c.id, type="function",
                                                  function=DeltaFunction(name=c.function.name, arguments=args[:mid]))])
            yield delta(tool_calls=[DeltaToolCall(index=i, function=DeltaFunction(arguments=args[mid:]))])
        if comp.refusal:
            yield delta(refusal=comp.refusal)
        yield ChatCompletionChunk(**base, choices=[ChunkChoice(delta=ChoiceDelta(), finish_reason=comp.finish_reason)])
        yield ChatCompletionChunk(**base, choices=[], usage=comp.usage, sajha=comp.sajha)


def _last_user_text(request: ChatRequest) -> str:
    for m in reversed(request.messages):
        if m.role == "user" and m.text:
            return m.text
    return ""


class EchoModel(_MockChat):
    def _reply(self, request):
        text = _last_user_text(request)
        if request.response_schema:
            return json.dumps({"answer": f"echo: {text}", "citations": [], "caveats": []}), [], "stop"
        return f"echo: {text}", [], "stop"

    def prepare(self, req, stream=False):
        if req.output_kind:     # echo wraps itself in the ask schema; good enough for wiring tests
            prep = super().prepare(req.model_copy(update={"response_format": None}), stream)
            prep.request = prep.request.model_copy(update={"response_format": req.response_format})
            return prep
        return super().prepare(req, stream)


class ScriptedModel(_MockChat):
    def _reply(self, request):
        name = self.id.split(":", 1)[1] if ":" in self.id else "default"
        step = self.provider.script(name).next_step(_last_user_text(request), stage_of(request))
        if step.get("error"):
            cls = ERROR_BY_NAME.get(step["error"], InvalidRequest)
            msg = step.get("message") or f"mock-scripted: {step['error']}"
            if cls is RateLimited:
                raise RateLimited(msg, retry_after=step.get("retry_after", 0), provider=self.provider.name,
                                  model=self.id)
            raise cls(msg, provider=self.provider.name, model=self.id)
        if step.get("sleep_ms"):
            time.sleep(step["sleep_ms"] / 1000.0)
        calls = []
        for i, tc in enumerate(step.get("tool_calls") or []):
            calls.append(ToolCallPart(tc.get("id") or f"call_{i}_{abs(hash(tc['name'])) % 10_000}",
                                      tc["name"], dict(tc.get("arguments") or {})))
        if "json" in step:
            text = json.dumps(step["json"])
        else:
            text = step.get("text", "")
        if step.get("refusal"):
            self._last_refusal = step["refusal"]
        finish = step.get("finish_reason") or ("tool_calls" if calls else "stop")
        return text, calls, finish


class PlannerModel(_MockChat):
    """Keyword planner. Plans only from the user's question, never from tool output."""

    def _create(self, request: ChatCompletionRequest) -> ChatCompletion:
        mode = (request.metadata or {}).get("sajha_llm_mode")
        if mode:                                   # an LLM tool's call (sajha/ai/llm/mock_llm_tools.py)
            from sajha.ai.llm import mock_llm_tools
            text = mock_llm_tools.reply(mode, mock_llm_tools.last_user(request.messages), request.output_schema,
                                        mock_llm_tools.system_text(request.messages))
            if text is not None:
                self.provider.inject()
                msg = ChatMessage(role="assistant", content=text)
                usage = CompletionUsage.of(self.count_tokens(request), estimate_tokens(text))
                return ChatCompletion(model=self.id, choices=[Choice(message=msg, finish_reason="stop")], usage=usage,
                                      sajha=ResponseSajha(provider=self.provider.name, cost_usd=0.0))
        return super()._create(request)

    def _reply(self, request: ChatRequest):
        props = ((request.response_schema or {}).get("properties") or {})
        if "steps" in props:                       # a plan_execute planning call (sajha/ai/planners.py)
            return self._plan_steps(request), [], "stop"
        if "standalone_question" in props:         # conversation memory: rewrite a follow-up
            return json.dumps({"standalone_question": self._standalone(request)}), [], "stop"
        if "summary" in props and "answer" not in props:   # conversation memory: summarise older turns
            return json.dumps({"summary": self._summary(request)}), [], "stop"
        stage = stage_of(request)
        if stage in STAGE_REPLIES:                 # a planner stage (sajha/ai/planners_engine)
            return STAGE_REPLIES[stage](self, request), [], "stop"
        question = _last_user_text(request)
        made_calls, results = self._conversation_state(request)
        if made_calls:
            return self._answer(request, question, made_calls, results)
        if request.tools and request.tool_choice != "none":
            calls = self._plan(_item_question(question), request.tools, request.tool_choice)
            if calls:
                return "", calls, "tool_calls"
        return self._answer(request, question, [], {})

    def _plan_steps(self, request: ChatRequest) -> str:
        """A plan from the question's keywords: the tools ``_plan`` would call, as independent steps.
        A re-plan (tool results after the question) plans nothing more."""
        if not request.tools or any(m.tool_results for m in request.messages):
            return json.dumps({"steps": []})       # a re-plan: results are in; plan nothing more
        question = _last_user_text(request)
        steps = [{"id": f"s{i + 1}", "tool": c.name, "arguments": json.dumps(c.arguments), "depends_on": [],
                  "why": f"{c.name.replace('_', ' ')} for the question"}
                 for i, c in enumerate(self._plan(question, request.tools, "auto"))]
        return json.dumps({"steps": steps})

    @staticmethod
    def _standalone(request: ChatRequest) -> str:
        """Deterministic follow-up rewrite: a message with no topic of its own ("and from 100 to 150?")
        takes the previous question's wording with the new numbers and symbols put in."""
        users = [m.text for m in request.messages if m.role == "user" and m.text]
        if not users:
            return ""
        current = users[-1]
        previous = users[-2] if len(users) > 1 else ""
        own = [w for w in keywords(current) if w not in {"and", "now", "then", "also", "what", "about", "again"}]
        if not previous or len(own) >= 2:
            return current
        new_nums = [m.group(0) for m in _NUMBER.finditer(current)]
        new_syms = extract_symbols(current)
        out = previous
        if new_nums:
            olds = list(_NUMBER.finditer(previous))
            pieces, last = [], 0
            for i, m in enumerate(olds):
                pieces.append(previous[last:m.start()])
                pieces.append(new_nums[i] if i < len(new_nums) else m.group(0))
                last = m.end()
            pieces.append(previous[last:])
            out = "".join(pieces)
        if new_syms:
            for old_sym, new_sym in zip(extract_symbols(previous), new_syms):
                out = re.sub(r"\b" + re.escape(old_sym) + r"\b", new_sym, out)
        return out if (new_nums or new_syms) else current

    @staticmethod
    def _summary(request: ChatRequest) -> str:
        """An extractive summary: each 'User:' line, and the first sentence of each answer."""
        text = _last_user_text(request)
        out = []
        for line in text.splitlines():
            if line.startswith("Summary so far:"):
                out.append(line[len("Summary so far:"):].strip())
            elif line.startswith("User:"):
                out.append("Asked: " + line[5:].strip())
            elif line.startswith("SAJHA:"):
                first = re.split(r"(?<=[.!?])\s", line[6:].strip(), maxsplit=1)[0]
                out.append("Answered: " + _short(first, 200))
        return " ".join(out)

    @staticmethod
    def _conversation_state(request):
        # only tool calls made after the last user message count
        last_user = max((i for i, m in enumerate(request.messages) if m.role == "user"), default=-1)
        calls, results = [], {}
        for m in request.messages[last_user + 1:]:
            calls.extend(m.tool_calls)
            for r in m.tool_results:
                results[r.call_id] = r
        return calls, results

    def _score(self, q_terms: List[str], spec: ToolSpec) -> float:
        name_terms = [_stem(t) for t in spec.name.split("_") if t]
        desc_terms = keywords(spec.description)
        props = (spec.input_schema or {}).get("properties") or {}
        param_terms = [t for p in props for t in keywords(p)]
        qs = set(q_terms)
        score = 0.0
        score += 3.0 * len(qs & set(name_terms[1:] or name_terms))
        score += 1.0 * len(qs & set(desc_terms))
        score += 0.5 * len(qs & set(param_terms))
        # numbers in the question favour tools that take numbers
        return score

    def _plan(self, question: str, tools: List[ToolSpec], tool_choice: str) -> List[ToolCallPart]:
        if tool_choice not in ("auto", "required", "none"):
            tools = [t for t in tools if t.name == tool_choice] or tools
        q_terms = keywords(question)
        scored = sorted(((self._score(q_terms, t), i, t) for i, t in enumerate(tools)),
                        key=lambda x: (-x[0], x[1]))
        if not scored or (scored[0][0] <= 0 and tool_choice != "required"):
            return []
        best = scored[0][0]
        chosen = [scored[0][2]]
        limit = max(1, int(getattr(self.provider.config, "max_planner_tools", 2)))
        for s, _, t in scored[1:limit]:
            if best > 0 and s >= max(3.0, 0.9 * best):
                chosen.append(t)
        calls = []
        for i, spec in enumerate(chosen):
            args = fill_arguments(spec.input_schema or {}, question)
            digest = hashlib.sha1(f"{spec.name}{json.dumps(args, sort_keys=True)}".encode()).hexdigest()[:8]
            calls.append(ToolCallPart(f"call_{i + 1}_{digest}", spec.name, args))
        return calls

    def _answer(self, request, question, calls, results):
        lines, cites, caveats = [], [], []
        for c in calls:
            r = results.get(c.id)
            if r is None:
                caveats.append(f"{c.name} returned no result")
                continue
            if r.is_error:
                caveats.append(f"{c.name} failed: {_short(r.content_text(), 200)}")
                continue
            cites.append(c.id)
            lines.append(summarize_result(c, r.content))
        if lines:
            answer = " ".join(lines)
        elif calls:
            answer = "I could not get an answer: every tool call failed."
        elif request.tools:
            answer = f"None of the available tools matches the question: {question}"
        else:
            answer = f"mock-planner (no tools offered): {question}"
        if request.response_schema:
            return json.dumps({"answer": answer, "citations": cites, "caveats": caveats}), [], "stop"
        return answer, [], "stop"


# ── planner stages (sajha/ai/planners_engine/stages.py): one deterministic reply per stage type ──

def stage_of(request: ChatRequest) -> str:
    """The planner stage type a request comes from: the response schema's ``sajha.<stage>`` title,
    else its shape (plan, condense, draft), else act (tools offered) or complete."""
    schema = request.response_schema or {}
    title = str(schema.get("title") or "")
    if title.startswith("sajha."):
        return title[len("sajha."):]
    props = schema.get("properties") or {}
    if "steps" in props:
        return "plan"
    if "standalone_question" in props:
        return "condense"
    if "answer" in props and "citations" in props:
        return "synthesis"
    if schema:
        return "extract"
    return "act" if request.tools and request.tool_choice != "none" else "complete"


def _item_question(question: str) -> str:
    """A map-reduce item's question ("... Answer only for: AAPL"): plan for that item only."""
    head, sep, item = question.partition("Answer only for:")
    if not sep:
        return question
    for sym in extract_symbols(head):
        head = re.sub(r"\b" + re.escape(sym) + r"\b", "", head)
    return f"{head.strip()} {item.strip()}"


def _all_calls(request: ChatRequest):
    calls, results = [], {}
    for m in request.messages:
        calls.extend(m.tool_calls)
        for r in m.tool_results:
            results[r.call_id] = r
    return calls, results


def _question_of(request: ChatRequest) -> str:
    """The last user message that is the question (not a stage's review or per-item data message)."""
    q = ""
    for m in request.messages:
        if m.role == "user" and m.text and not m.text.startswith(("Per-item answers", "Question:")):
            q = m.text
    return q or _last_user_text(request)


def _reply_classify(model, request) -> str:
    """Rules first: a label named in the question, a multi-part question for plan_execute, the
    label whose menu line shares most words with the question; else the first label."""
    schema = request.response_schema or {}
    labels = [str(x) for x in (((schema.get("properties") or {}).get("label") or {}).get("enum") or [])]
    q = _last_user_text(request)
    low = q.lower()
    label, conf = (labels[0] if labels else ""), 0.55
    named = [lab for lab in labels if re.search(r"\b" + re.escape(lab.lower()) + r"\b", low)]
    if named:
        label, conf = named[0], 0.9
    elif "plan_execute" in labels and re.search(r"\b(and then|then|compare|versus|vs\.?|both|each of|as well as)\b"
                                                r"|\?.+\?", q, re.I | re.S):
        label, conf = "plan_execute", 0.8
    else:
        system = request.system or ""
        terms = set(keywords(q))
        best = 0
        for lab in labels:
            m = re.search(r"^" + re.escape(lab) + r": (.*)$", system, re.M)
            score = len(terms & set(keywords(m.group(1)))) if m else 0
            if score > best:
                label, conf, best = lab, 0.6, score
    return json.dumps({"label": label, "confidence": conf, "reason": f"mock: {label}"})


def _reply_critique(model, request) -> str:
    text = _last_user_text(request)
    m = re.search(r"Draft answer:\n(.*?)\n\n", text, re.S)
    draft = m.group(1).strip() if m else ""
    if draft:
        return json.dumps({"verdict": "pass", "issues": []})
    return json.dumps({"verdict": "revise", "issues": [{"criterion": "answers every part of the question",
                                                        "problem": "the draft is empty",
                                                        "suggestion": "answer from the tool results"}]})


def _reply_judge(model, request) -> str:
    ids = [str(x) for x in ((((request.response_schema or {}).get("properties") or {}).get("winner") or {})
                            .get("enum") or [])]
    return json.dumps({"winner": ids[0] if ids else "", "reason": "mock: the first candidate"})


def _reply_draft(model, request) -> str:
    """Compose from every result in the transcript, plus per-item answers when a foreach ran."""
    calls, results = _all_calls(request)
    text, _c, _f = model._answer(request, _question_of(request), calls, results)
    data = json.loads(text) if text.startswith("{") else {"answer": text, "citations": [], "caveats": []}
    items = [m.text for m in request.messages if m.role == "user" and (m.text or "").startswith("Per-item answers")]
    if items:
        lines = [ln[2:] for ln in items[-1].splitlines()[1:] if ln.startswith("- ")]
        data["answer"] = "; ".join(lines) if lines else data["answer"]
    return json.dumps(data)


def _reply_revise(model, request) -> str:
    text = _last_user_text(request)
    m = re.search(r"Draft answer:\n(.*?)\n\nTool results", text, re.S)
    calls, results = _all_calls(request)
    cites = [c.id for c in calls if c.id in results and not results[c.id].is_error]
    return json.dumps({"answer": (m.group(1).strip() if m else text), "citations": cites, "caveats": []})


def _reply_extract(model, request) -> str:
    """A custom draft schema: a list of items (symbols in the question, else words from the results)."""
    props = (request.response_schema or {}).get("properties") or {}
    q = _question_of(request)
    out: Dict[str, Any] = {}
    for k, p in props.items():
        t = (p or {}).get("type")
        if t == "array":
            out[k] = extract_symbols(q)[: int((p or {}).get("maxItems") or 50)]
        elif t == "string":
            out[k] = q[:200]
        elif t in ("number", "integer"):
            nums = extract_numbers(q)
            out[k] = nums[0] if nums else 0
        elif t == "boolean":
            out[k] = False
        else:
            out[k] = None
    return json.dumps(out)


def _reply_condense(model, request) -> str:
    return json.dumps({"standalone_question": model._standalone(request)})


STAGE_REPLIES = {"classify": _reply_classify, "critique": _reply_critique, "judge": _reply_judge,
                 "draft": _reply_draft, "revise": _reply_revise, "extract": _reply_extract,
                 "condense": _reply_condense}


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def summarize_result(call: ToolCallPart, content: Any) -> str:
    """A one-sentence, data-only summary: output fields (those not echoing an input)."""
    data = content
    if isinstance(content, str):
        try:
            data = json.loads(content)
        except Exception:
            return f"{call.name} returned: {_short(content, 300)}."
    if isinstance(data, dict) and isinstance(data.get("result"), dict) and len(data) <= 2:
        data = data["result"]
    if isinstance(data, dict) and isinstance(data.get("results"), list):     # a search: quote the best passage
        hits = [r for r in data["results"] if isinstance(r, dict) and r.get("text")]
        if hits:
            top = hits[0]
            where = " — ".join(x for x in (str(top.get("title") or ""), str(top.get("section") or "")) if x)
            body = re.sub(r"\s+", " ", str(top["text"])).strip()
            return f"{where + ': ' if where else ''}{_short(body, 400)} (from {call.name}, {len(hits)} passage(s))."
    if isinstance(data, dict):
        outputs = []
        for k, v in data.items():
            if k in call.arguments and call.arguments[k] == v:
                continue                      # an echoed input, not an output
            if isinstance(v, (int, float, str)) and not (isinstance(v, str) and len(v) > 200):
                outputs.append((k, v))
        outputs = outputs[:6]
        inputs = ", ".join(f"{k}={v}" for k, v in call.arguments.items())
        if outputs:
            body = "; ".join(f"{k.replace('_', ' ')} = {v}" for k, v in outputs)
            return f"{body} (from {call.name}{' with ' + inputs if inputs else ''})."
        return f"{call.name} returned {_short(json.dumps(data, default=str), 300)}."
    return f"{call.name} returned {_short(json.dumps(data, default=str), 300)}."


def _numbers_with_pos(text: str) -> List[Tuple[int, int, Any]]:
    out = []
    for m in _NUMBER.finditer(text):
        raw = m.group(0).replace(",", "")
        try:
            v = float(raw)
        except ValueError:
            continue
        out.append((m.start(), m.end(), int(v) if v.is_integer() and "." not in raw else v))
    return out


def _near_keyword(question: str, pname: str, nums, used: set):
    """The number nearest after (or just before) a mention of the parameter's name words."""
    low = question.lower()
    words = [w for w in pname.lower().split("_") if len(w) > 2 and w not in _STOP]
    best = None
    for w in words:
        stem = _stem(w)
        for m in re.finditer(r"\b" + re.escape(stem), low):
            for i, (s0, e0, v) in enumerate(nums):
                if i in used:
                    continue
                gap = s0 - m.end() if s0 >= m.end() else None
                back = m.start() - e0 if e0 <= m.start() else None
                score = gap if gap is not None and gap <= 25 else (back + 100 if back is not None and back <= 12 else None)
                if score is not None and (best is None or score < best[0]):
                    best = (score, i)
    return best[1] if best else None


def fill_arguments(schema: Dict[str, Any], question: str) -> Dict[str, Any]:
    """Fill a tool's arguments from schema defaults and the numbers / symbols in the question.

    Numbers go first to the numeric parameter whose name is mentioned next to them ("rate 5"),
    then to number arrays, then in order to the remaining required numeric parameters."""
    props: Dict[str, Any] = (schema or {}).get("properties") or {}
    required = list((schema or {}).get("required") or [])
    order = required + [p for p in props if p not in required]
    nums = _numbers_with_pos(question)
    used: set = set()
    symbols = extract_symbols(question)
    words = {w.lower() for w in _WORD.findall(question)}

    def typ_of(ps):
        t = ps.get("type")
        return next((x for x in t if x != "null"), None) if isinstance(t, list) else t

    args: Dict[str, Any] = {}
    # pass 1: numeric scalars by keyword proximity
    for name in order:
        ps = props.get(name) or {}
        if typ_of(ps) in ("number", "integer") and "enum" not in ps:
            i = _near_keyword(question, name, nums, used)
            if i is not None:
                used.add(i)
                v = nums[i][2]
                args[name] = int(v) if typ_of(ps) == "integer" else v
    # pass 2: number arrays take the unused numbers in order
    for name in order:
        ps = props.get(name) or {}
        if typ_of(ps) == "array" and (ps.get("items") or {}).get("type") in ("number", "integer"):
            rest = [i for i in range(len(nums)) if i not in used]
            if rest:
                args[name] = [nums[i][2] for i in rest]
                used.update(rest)
    # pass 3: everything else
    for name in order:
        if name in args:
            continue
        ps = props.get(name) or {}
        typ = typ_of(ps)
        if "enum" in ps and ps["enum"]:
            hit = next((e for e in ps["enum"] if str(e).lower() in words), None)
            if hit is not None:
                args[name] = hit
            elif "default" in ps:
                args[name] = ps["default"]
            elif name in required:
                args[name] = ps["enum"][0]
            continue
        if typ in ("number", "integer"):
            if "default" in ps and name not in required:
                args[name] = ps["default"]
                continue
            rest = [i for i in range(len(nums)) if i not in used]
            if rest:
                used.add(rest[0])
                v = nums[rest[0]][2]
                args[name] = int(v) if typ == "integer" else v
            elif "default" in ps:
                args[name] = ps["default"]
            continue
        if typ == "array":
            it = (ps.get("items") or {}).get("type")
            if it == "string" and symbols and any(k in name.lower() for k in ("symbol", "ticker")):
                args[name] = list(symbols)
            elif "default" in ps:
                args[name] = ps["default"]
            continue
        if typ == "string":
            lname = name.lower()
            if any(k in lname for k in ("symbol", "ticker")) and symbols:
                args[name] = symbols.pop(0)
            elif "default" in ps:
                args[name] = ps["default"]
            elif any(k in lname for k in ("query", "question", "text", "search")) or name in required:
                args[name] = question
            continue
        if "default" in ps:
            args[name] = ps["default"]
    return {k: args[k] for k in order if k in args}


class HashEmbeddingModel(EmbeddingModel):
    """Hashed word uni/bi-grams into ``dimensions`` buckets, L2-normalised."""

    def embed(self, texts: List[str]) -> List[List[float]]:
        self.provider.inject()
        dims = self.dimensions or 256
        out = []
        for text in texts:
            v = [0.0] * dims
            toks = [_stem(w) for w in _WORD.findall((text or "").lower().replace("_", " "))]
            grams = toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]
            for g in grams:
                h = hashlib.blake2b(g.encode("utf-8"), digest_size=8).digest()
                idx = int.from_bytes(h[:4], "little") % dims
                sign = 1.0 if h[4] & 1 else -1.0
                v[idx] += sign * (1.0 if " " not in g else 0.5)
            n = math.sqrt(sum(x * x for x in v))
            out.append([x / n for x in v] if n else v)
        return out
