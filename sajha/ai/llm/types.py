"""
SAJHA Intelligence Layer — provider-neutral message and request vocabulary.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Plain dataclasses. Nothing here imports a vendor SDK. These are the original types; the
canonical format is now OpenAI Chat Completions (canonical.py), and convert.py translates
between the two losslessly, so callers written against ChatRequest / ChatResponse keep
working while they move. New code should use the canonical types.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, Union

Role = Literal["system", "user", "assistant", "tool"]
FinishReason = Literal["stop", "tool_calls", "length", "content_filter", "error"]


# ── Message parts ────────────────────────────────────────────────

@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class ImagePart:
    data: bytes
    mime_type: str = "image/png"

    @property
    def b64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


@dataclass(frozen=True)
class ToolCallPart:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ToolResultPart:
    call_id: str
    content: Any
    is_error: bool = False
    name: str = ""          # tool name; some vendors (Gemini, Ollama) need it on the result

    def content_text(self) -> str:
        """The result as text, for vendors whose tool results are strings."""
        if isinstance(self.content, str):
            return self.content
        try:
            return json.dumps(self.content, default=str, ensure_ascii=False)
        except Exception:
            return str(self.content)


Part = Union[TextPart, ImagePart, ToolCallPart, ToolResultPart]


@dataclass
class Message:
    role: Role
    parts: List[Part] = field(default_factory=list)
    # provider round-trip state (e.g. Anthropic thinking blocks that must be echoed back on
    # the next turn of a tool loop); never sent to a different provider, never logged
    meta: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    # helpers
    @classmethod
    def user(cls, text: str) -> "Message":
        return cls("user", [TextPart(text)])

    @classmethod
    def system(cls, text: str) -> "Message":
        return cls("system", [TextPart(text)])

    @classmethod
    def assistant(cls, text: str = "", tool_calls: Optional[List[ToolCallPart]] = None) -> "Message":
        parts: List[Part] = [TextPart(text)] if text else []
        parts.extend(tool_calls or [])
        return cls("assistant", parts)

    @classmethod
    def tool_result(cls, call_id: str, content: Any, is_error: bool = False, name: str = "") -> "Message":
        return cls("tool", [ToolResultPart(call_id, content, is_error, name)])

    @property
    def text(self) -> str:
        return "".join(p.text for p in self.parts if isinstance(p, TextPart))

    @property
    def tool_calls(self) -> List[ToolCallPart]:
        return [p for p in self.parts if isinstance(p, ToolCallPart)]

    @property
    def tool_results(self) -> List[ToolResultPart]:
        return [p for p in self.parts if isinstance(p, ToolResultPart)]

    def to_dict(self) -> Dict[str, Any]:
        out = []
        for p in self.parts:
            if isinstance(p, TextPart):
                out.append({"type": "text", "text": p.text})
            elif isinstance(p, ImagePart):
                out.append({"type": "image", "mime_type": p.mime_type, "sha": hash(p.data)})
            elif isinstance(p, ToolCallPart):
                out.append({"type": "tool_call", "id": p.id, "name": p.name, "arguments": p.arguments})
            elif isinstance(p, ToolResultPart):
                out.append({"type": "tool_result", "call_id": p.call_id, "content": p.content,
                            "is_error": p.is_error})
        return {"role": self.role, "parts": out}


# ── Tools ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ToolSpec:
    """A tool offered to a model; built from an MCP tool's name, description and inputSchema."""
    name: str
    description: str
    input_schema: dict

    @classmethod
    def from_mcp(cls, tool) -> "ToolSpec":
        if isinstance(tool, dict):
            return cls(tool.get("name", ""), tool.get("description", "") or "",
                       tool.get("inputSchema") or tool.get("input_schema") or {"type": "object"})
        schema = {}
        try:
            schema = tool.input_schema or {}
        except Exception:
            schema = {}
        if not isinstance(schema, dict) or not schema:
            schema = {"type": "object", "properties": {}}
        return cls(tool.name, getattr(tool, "description", "") or "", schema)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


# ── Request context ─────────────────────────────────────────────

@dataclass
class RequestContext:
    """Who is asking and under which limits. Travels in ChatRequest.metadata."""
    user_id: str = ""
    roles: List[str] = field(default_factory=list)
    is_admin: bool = False
    trace_id: str = ""
    budget_key: str = ""                      # defaults to user_id
    can_use_tool: Optional[Callable[[str], bool]] = None   # RBAC check for the ask loop
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def budget_owner(self) -> str:
        return self.budget_key or self.user_id or "anonymous"


# ── Requests and responses ──────────────────────────────────────

@dataclass
class ChatRequest:
    messages: List[Message]
    system: str = ""
    tools: List[ToolSpec] = field(default_factory=list)
    tool_choice: str = "auto"                 # "auto" | "none" | "required" | <tool name>
    response_schema: Optional[dict] = None    # structured output: JSON Schema the reply must match
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = None
    stop: List[str] = field(default_factory=list)
    metadata: Optional[RequestContext] = None

    def canonical(self) -> Dict[str, Any]:
        """A JSON-able canonical form, used as the response-cache key."""
        return {
            "messages": [m.to_dict() for m in self.messages],
            "system": self.system,
            "tools": [t.to_dict() for t in self.tools],
            "tool_choice": self.tool_choice,
            "schema": self.response_schema,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "stop": list(self.stop),
        }


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens,
                     self.cached_tokens + other.cached_tokens, self.cost_usd + other.cost_usd)

    def to_dict(self) -> Dict[str, Any]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cached_tokens": self.cached_tokens, "total_tokens": self.total_tokens,
                "cost_usd": round(self.cost_usd, 6)}


@dataclass
class ChatResponse:
    message: Message
    finish_reason: str
    usage: Usage
    model: str
    provider: str
    latency_ms: int = 0
    raw: Any = None                 # provider payload, never logged
    cached: bool = False            # served from the gateway's response cache
    refusal: str = ""               # the model's refusal (finish_reason content_filter)
    notes: Dict[str, Any] = field(default_factory=dict)   # SAJHA markers: ignored, usage_estimated, ...

    @property
    def text(self) -> str:
        return self.message.text

    @property
    def tool_calls(self) -> List[ToolCallPart]:
        return self.message.tool_calls

    def json(self) -> Any:
        """Parse the text as JSON (structured output); tolerant of code fences."""
        return parse_json_text(self.text)


def parse_json_text(text: str) -> Any:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
        t = t.strip()
    try:
        return json.loads(t)
    except Exception:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            return json.loads(t[start:end + 1])
        raise


# ── Streaming events ────────────────────────────────────────────

@dataclass
class TextDelta:
    text: str
    type: str = "text_delta"


@dataclass
class ToolCallDelta:
    id: str
    name: str
    arguments_json_fragment: str
    index: int = 0
    type: str = "tool_call_delta"


@dataclass
class UsageEvent:
    usage: Usage
    type: str = "usage"


@dataclass
class Done:
    response: ChatResponse
    type: str = "done"


StreamEvent = Union[TextDelta, ToolCallDelta, UsageEvent, Done]


@dataclass
class EmbeddingResult:
    vectors: List[List[float]]
    model: str
    provider: str
    usage: Usage = field(default_factory=Usage)

    @property
    def dimensions(self) -> int:
        return len(self.vectors[0]) if self.vectors else 0
