"""
``sajha`` CLI — terminal output: tables, results, and the ask step stream.

Plain ASCII markers (no emoji); colour only on a TTY and never when
``NO_COLOR`` is set or ``--no-color`` is given.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import textwrap
from typing import Any, Dict, Iterable, List, Optional, Sequence, TextIO

_COLOR = {"dim": "2", "bold": "1", "red": "31", "green": "32", "yellow": "33", "blue": "34", "cyan": "36"}


class Out:
    def __init__(self, stream: TextIO = None, err: TextIO = None, color: Optional[bool] = None):
        self.stream = stream or sys.stdout
        self.err = err or sys.stderr
        if color is None:
            color = bool(getattr(self.stream, "isatty", lambda: False)()) and not os.environ.get("NO_COLOR")
        self.color = color

    def c(self, text: str, *styles: str) -> str:
        if not self.color or not styles:
            return text
        codes = ";".join(_COLOR[s] for s in styles if s in _COLOR)
        return f"\033[{codes}m{text}\033[0m"

    def print(self, *parts: Any, end: str = "\n"):
        self.stream.write(" ".join(str(p) for p in parts) + end)
        self.stream.flush()

    def error(self, message: str):
        self.err.write(self.c("error: ", "red", "bold") + message + "\n")
        self.err.flush()

    def note(self, message: str):
        self.err.write(self.c(message, "dim") + "\n")
        self.err.flush()

    def json(self, value: Any):
        self.print(json.dumps(value, indent=2, default=str, ensure_ascii=False))

    @property
    def width(self) -> int:
        return max(40, shutil.get_terminal_size((100, 24)).columns)


def first_line(text: Optional[str], limit: int = 0) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    if limit and len(line) > limit:
        line = line[: max(0, limit - 3)] + "..."
    return line


def table(out: Out, rows: Sequence[Sequence[str]], headers: Sequence[str] = ()):
    """Left-aligned columns; the last column is truncated to the terminal width."""
    if not rows:
        return
    cols = len(rows[0])
    widths = [max(len(str(r[i])) for r in list(rows) + ([headers] if headers else [])) for i in range(cols - 1)]
    used = sum(widths) + 2 * (cols - 1)
    last = max(20, out.width - used)
    if headers:
        out.print(out.c("  ".join(str(h).ljust(w) for h, w in zip(headers, widths + [0])).rstrip(), "bold"))
    for r in rows:
        cells = [str(r[i]).ljust(widths[i]) for i in range(cols - 1)]
        tail = str(r[-1])
        if len(tail) > last:
            tail = tail[: last - 3] + "..."
        out.print("  ".join(cells + [tail]).rstrip())


# ── tool results ─────────────────────────────────────────────────

def dump(model: Any) -> Any:
    """A pydantic SDK result (or anything) -> plain JSON-able data."""
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", by_alias=True, exclude_none=True)
    return model


def print_tool_result(out: Out, result: Any):
    data = dump(result)
    structured = data.get("structuredContent") if isinstance(data, dict) else None
    blocks = (data.get("content") or []) if isinstance(data, dict) else []
    if structured is not None:
        out.json(structured)
        return
    for block in blocks:
        kind = block.get("type")
        if kind == "text":
            text = block.get("text", "")
            try:
                out.json(json.loads(text))
            except (ValueError, TypeError):
                out.print(text)
        elif kind == "resource_link":
            out.print(f"[resource] {block.get('uri')}  {block.get('name') or ''}".rstrip())
        elif kind == "resource":
            res = block.get("resource") or {}
            out.print(res.get("text") if "text" in res else f"[resource] {res.get('uri')}")
        else:
            out.print(f"[{kind}] ({block.get('mimeType', '')})")


def print_schema(out: Out, schema: Dict[str, Any]):
    props = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or [])
    if not props:
        out.print("  (no arguments)")
        return
    rows = []
    for name, p in props.items():
        p = p if isinstance(p, dict) else {}
        kind = p.get("type") or ("enum" if "enum" in p else "any")
        if isinstance(kind, list):
            kind = "|".join(map(str, kind))
        flag = "required" if name in required else "optional"
        desc = first_line(p.get("description"))
        if "enum" in p:
            desc = (desc + " " if desc else "") + "one of: " + ", ".join(map(str, p["enum"]))
        if "default" in p:
            desc = (desc + " " if desc else "") + f"(default {json.dumps(p['default'])})"
        rows.append(("  " + name, kind, flag, desc))
    table(out, rows)


# ── ask: the step stream ─────────────────────────────────────────

class AskRenderer:
    """Turns ``POST /api/ai/ask`` step events into terminal lines as they arrive."""

    def __init__(self, out: Out, verbose: bool = False):
        self.out = out
        self.verbose = verbose
        self.streamed_answer = False
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[Dict[str, Any]] = None
        self.confirmations: List[Dict[str, Any]] = []
        self._mid_line = False

    def _line(self, text: str):
        if self._mid_line:
            self.out.err.write("\n")
            self._mid_line = False
        self.out.err.write(text + "\n")
        self.out.err.flush()

    def event(self, ev: Dict[str, Any]):
        c, kind = self.out.c, ev.get("type")
        if kind == "shortlist":
            names = [t.get("name") for t in ev.get("tools") or []]
            shown = ", ".join(names[:6]) + (f" (+{len(names) - 6})" if len(names) > 6 else "")
            self._line(c(f"  shortlist  {len(names)} tools: {shown}", "dim"))
        elif kind == "model":
            self._line(c(f"  model      {ev.get('model')} (step {ev.get('step')})", "dim"))
        elif kind == "tool_call":
            args = json.dumps(ev.get("arguments") or {}, ensure_ascii=False)
            if len(args) > 100 and not self.verbose:
                args = args[:97] + "..."
            self._line(c("  -> ", "cyan") + c(str(ev.get("name")), "bold") + c(f" {args}", "dim"))
        elif kind == "tool_result":
            ok = ev.get("ok")
            mark = c("ok  ", "green") if ok else c("FAIL", "red")
            summary = first_line(ev.get("summary"), 0 if self.verbose else 90)
            self._line(f"  {mark} {ev.get('name')} {c(str(ev.get('latency_ms', '?')) + 'ms', 'dim')} {summary}".rstrip())
        elif kind == "needs_confirmation":
            self.confirmations.append(ev)
            self._line(c("  ?  ", "yellow") + f"{ev.get('name')} needs confirmation: {ev.get('reason') or ''}".rstrip())
            self._line(c(f"     re-run with --confirm {ev.get('fingerprint')}", "yellow"))
        elif kind == "answer_delta":
            if not self.streamed_answer:
                self.out.stream.write("\n")
            self.streamed_answer = True
            self.out.stream.write(ev.get("text") or "")
            self.out.stream.flush()
        elif kind == "answer":
            if not self.streamed_answer:
                self.out.print("\n" + (ev.get("text") or ""))
            else:
                self.out.print("")
        elif kind == "confidence":
            value = ev.get("value")
            basis = "; ".join(map(str, ev.get("basis") or []))
            self._line(c(f"\n  confidence {value}" + (f"  ({basis})" if basis and self.verbose else ""), "dim"))
        elif kind == "error":
            self.error = ev
            self._line(c("  error ", "red") + f"{ev.get('code')}: {ev.get('message')}")
        elif kind == "done":
            self.result = ev.get("result")
        elif self.verbose:
            self._line(c(f"  {kind} {json.dumps(ev, default=str)}", "dim"))


def iter_sse(lines: Iterable[bytes]):
    """Parse a text/event-stream body into the JSON ``data`` of each event."""
    data: List[str] = []
    for raw in lines:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            if data:
                payload = "\n".join(data)
                data = []
                try:
                    yield json.loads(payload)
                except ValueError:
                    continue
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        if name == "data":
            data.append(value[1:] if value.startswith(" ") else value)
    if data:
        try:
            yield json.loads("\n".join(data))
        except ValueError:
            pass


def wrap(text: str, width: int, indent: str = "  ") -> str:
    return "\n".join(textwrap.wrap(text, width=width, initial_indent=indent, subsequent_indent=indent))
