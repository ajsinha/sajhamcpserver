"""
Example planning strategy, written as a model: fixed recipes for known questions.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

The worked example of docs/architecture/Extending the Intelligence Layer.md (section 4.4).
With the default ``react`` planner, the "planner" is whichever ChatModel the ``ai.ask.model``
alias resolves to, called once per step of the tool loop. So a custom strategy can be written
as a ChatModel and put first in the alias (section 4.5 shows the same idea as a Planner, and
the built-in ``recipes`` planner needs no alias trick):

    ai.aliases.default: [recipes, anthropic, mock/mock-planner]

A recipe is a regular expression over the question and the tool to call; its named groups
become the tool's arguments. A question no recipe matches raises UnsupportedFeature, and
the gateway moves to the next candidate in the alias (a real LLM), for that step and every
later one. The model only ever calls a tool the loop offered, so the caller's RBAC, the
shortlist, the limits and destructive-tool confirmation all still apply.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import Field

from sajha.ai.llm import ConfigurationError, UnsupportedFeature
from sajha.ai.llm.spi import (ChatModel, HealthStatus, Layered, ModelCapabilities, ModelDescriptor, ProviderBase,
                              ProviderConfig, estimate_tokens, register_provider)
from sajha.ai.llm.canonical import (ChatCompletion, ChatCompletionRequest, ChatMessage, Choice, CompletionUsage,
                                    ToolCall)

CALL_PREFIX = "recipe_"


class Recipe(Layered):
    name: str
    match: str                                         # regex over the question, case-insensitive
    tool: str                                          # the tool to call
    arguments: Dict[str, Any] = Field(default_factory=dict)   # fixed arguments, merged under the groups
    answer: str = ""                                   # e.g. "The change is {percentage_change}%."


class RecipeConfig(ProviderConfig):
    recipes: List[Recipe] = Field(default_factory=list)


class _Fields(dict):
    def __missing__(self, key):
        return "?"


def _coerce(value: str, schema: Dict[str, Any]) -> Any:
    t = schema.get("type")
    try:
        if t == "integer":
            return int(float(value.replace(",", "")))
        if t == "number":
            return float(value.replace(",", ""))
    except ValueError:
        pass
    return value


class RecipePlannerModel(ChatModel):
    """Written against the canonical format: ``_create`` takes a ChatCompletionRequest and returns
    a ChatCompletion; the base class adds the capability check, streaming and async."""

    def _create(self, request: ChatCompletionRequest) -> ChatCompletion:
        question = next((m.text for m in reversed(request.messages) if m.role == "user" and m.text), "")
        recipe, match = self.provider.find(question)
        if recipe is None:
            raise UnsupportedFeature("no recipe matches this question", provider=self.provider.name, model=self.id)
        calls, results = self._since_question(request)
        if not calls:                                  # step 1: plan
            offered = {t.name: t for t in request.tools or []} if request.wants_tools else {}
            spec = offered.get(recipe.tool)
            if spec is None:                           # not shortlisted, or the caller may not run it
                raise UnsupportedFeature(f"recipe {recipe.name}: {recipe.tool} was not offered",
                                         provider=self.provider.name, model=self.id)
            props = spec.parameters_or_default.get("properties") or {}
            args = dict(recipe.arguments)
            args.update({k: _coerce(v, props.get(k) or {}) for k, v in match.groupdict().items() if v is not None})
            digest = hashlib.sha1(json.dumps([recipe.name, args], sort_keys=True).encode()).hexdigest()[:8]
            msg = ChatMessage.assistant(None, [ToolCall.of(f"{CALL_PREFIX}{digest}", recipe.tool, args)])
            return self._response(request, msg, "tool_calls")
        if not all(c.id.startswith(CALL_PREFIX) for c in calls):
            # another model planned this question (we deferred at step 1): keep deferring
            raise UnsupportedFeature("not a recipe conversation", provider=self.provider.name, model=self.id)
        text, cited, caveats = self._answer(recipe, calls, results)
        if request.output_kind:                        # the synthesis call
            text = json.dumps({"answer": text, "citations": cited, "caveats": caveats})
        return self._response(request, ChatMessage.assistant(text), "stop")

    @staticmethod
    def _since_question(request: ChatCompletionRequest) -> Tuple[List[ToolCall], Dict[str, ChatMessage]]:
        last_user = max((i for i, m in enumerate(request.messages) if m.role == "user"), default=-1)
        calls, results = [], {}
        for m in request.messages[last_user + 1:]:
            calls.extend(m.tool_calls or [])
            if m.role == "tool":
                results[m.tool_call_id] = m
        return calls, results

    @staticmethod
    def _answer(recipe: Recipe, calls: List[ToolCall], results: Dict[str, ChatMessage]):
        lines, cited, caveats = [], [], []
        for c in calls:
            r = results.get(c.id)
            if r is None or r.is_error:
                caveats.append(f"{c.function.name} did not return a result")
                continue
            try:
                data = json.loads(r.text)
            except ValueError:
                data = {"result": r.text}
            fields = _Fields(data if isinstance(data, dict) else {"result": data})
            fields.setdefault("result", r.text)
            lines.append(recipe.answer.format_map(fields) if recipe.answer
                         else f"{c.function.name} returned {r.text}")
            cited.append(c.id)
        return (" ".join(lines) or "The recipe's tool call failed."), cited, caveats

    def _response(self, request: ChatCompletionRequest, msg: ChatMessage, finish: str) -> ChatCompletion:
        out = msg.text + "".join(c.function.arguments for c in msg.tool_calls or [])
        return ChatCompletion(model=self.id, choices=[Choice(message=msg, finish_reason=finish)],
                              usage=CompletionUsage.of(self.count_tokens(request), estimate_tokens(out)))


@register_provider
class RecipeProvider(ProviderBase):
    """A keyless, in-process provider whose one model is the recipe planner."""
    name = "recipes"
    config_model = RecipeConfig
    requires_key = False
    chat_model_class = RecipePlannerModel
    CAPABILITIES = ModelCapabilities(tools=True, structured_output=True, streaming=False, context_window=1_000_000,
                                     tags=frozenset({"deterministic", "local"}))

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        try:                                           # a bad regex fails at startup, not mid-ask
            self._compiled = [(r, re.compile(r.match, re.I)) for r in self.config.recipes]
        except re.error as e:
            raise ConfigurationError(f"recipes: invalid match pattern: {e}") from None

    def find(self, question: str) -> Tuple[Optional[Recipe], Optional[re.Match]]:
        for recipe, rx in self._compiled:
            m = rx.search(question or "")
            if m:
                return recipe, m
        return None, None

    def live_models(self) -> List[ModelDescriptor]:
        return [ModelDescriptor("recipe-planner", self.CAPABILITIES, source="builtin")]

    def default_chat_model_id(self) -> str:
        return self.config.default_model or "recipe-planner"

    def health(self) -> HealthStatus:
        if not self.active:
            return HealthStatus("down", "disabled")
        return HealthStatus("ok" if self._compiled else "degraded", f"{len(self._compiled)} recipe(s)")
