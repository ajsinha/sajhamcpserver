"""
SAJHA MCP Server — computation graphs (Quantitative Planners §3.1).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A model writes a **computation graph** instead of an answer; SAJHA validates it and runs it. This
module is the pure part: the graph's schema, :func:`parse_graph` (every check that runs before
anything does) and :func:`evaluate` (operations in dependency order on the values read). It calls
no tools and no model; the ``graph_plan`` and ``compute`` stage types
(sajha/ai/planners_engine/quant_stages.py) do the calls.

The form (a structured reply)::

    {"nodes": {
        "cpi_now":   {"tool": "fred_cpi", "arguments": {"limit": 13},
                      "read": "$.data.observations[0].value", "unit": "index", "as_of": "2026-09"},
        "cpi_then":  {"tool": "fred_cpi", "arguments": {"limit": 13},
                      "read": "$.data.observations[12].value", "unit": "index"},
        "target":    {"value": 2, "unit": "percent"},                       # a figure the question states
        "inflation": {"op": "pct_change", "from": "cpi_then", "to": "cpi_now"}},
     "answer_with": ["inflation"],
     "why": "one sentence"}

A node is one of three kinds: a **tool read** (``tool``, ``arguments``, ``read``: a JSONPath into
the result, ``unit``: the declared unit, optional ``as_of``), a **constant** (``value``, ``unit``)
or an **operation** (``op``, its arguments by name as in ``ops.operations()``, or ``args`` for
positional ones). An argument that is a node name (or ``node.part`` for ``regression``) is a
reference; anything else is a literal. Validation: names are identifiers not already in the
workspace, at most ``ai.quant.max_graph_nodes`` nodes, every tool offered, every operation known,
every read path parses, no cycle, and the operations' unit checks pass on the declared units.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sajha.ai.quant.errors import QuantError, UnitError
from sajha.ai.quant.quantity import Quantity, Workspace, normalise_value
from sajha.ai.quant.units import parse_unit

NODE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MAX_ERRORS = 20
TOOL_KEYS = {"tool", "arguments", "read", "unit", "as_of", "why"}
VALUE_KEYS = {"value", "unit", "as_of", "why"}
OP_RESERVED = {"op", "args", "why"}

#: The JSON Schema a model's reply is checked against before :func:`parse_graph` validates it.
GRAPH_SCHEMA: Dict[str, Any] = {
    "type": "object", "title": "sajha.graph_plan", "additionalProperties": False,
    "required": ["nodes", "answer_with"],
    "properties": {
        "nodes": {"type": "object", "minProperties": 1, "additionalProperties": {
            "type": "object", "minProperties": 1,
            "properties": {"tool": {"type": "string"}, "arguments": {"type": ["object", "string"]},
                           "read": {"type": "string"}, "unit": {"type": "string"},
                           "as_of": {"type": "string"}, "op": {"type": "string"},
                           "value": {"type": ["number", "array"]}, "args": {"type": "array"},
                           "why": {"type": "string"}}}},
        "answer_with": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "string"}},
        "why": {"type": "string", "maxLength": 500}}}


@dataclass
class Node:
    name: str
    kind: str                                    # tool | value | op
    spec: Dict[str, Any]
    deps: List[str] = field(default_factory=list)
    arguments: Dict[str, Any] = field(default_factory=dict)     # a tool node's call arguments


@dataclass
class Graph:
    nodes: Dict[str, Node]
    order: List[str]                             # dependency order
    answer_with: List[str]
    why: str = ""

    def tool_nodes(self) -> List[Node]:
        return [self.nodes[n] for n in self.order if self.nodes[n].kind == "tool"]


def _base(ref: str) -> str:
    return ref.split(".", 1)[0]


def _is_ref(v: Any, names: Set[str]) -> bool:
    return isinstance(v, str) and (v in names or ("." in v and _base(v) in names))


def _refs(v: Any, names: Set[str]) -> List[str]:
    if _is_ref(v, names):
        return [v]
    if isinstance(v, list) and v and all(_is_ref(x, names) for x in v):
        return list(v)
    return []


def _arguments(raw: Any) -> Optional[Dict[str, Any]]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            v = json.loads(raw) if raw.strip() else {}
        except ValueError:
            return None
        return v if isinstance(v, dict) else None
    return None


def op_inputs(node: Node) -> Tuple[List[Any], Dict[str, Any]]:
    """An operation node's positional and keyword arguments as written."""
    args = list(node.spec.get("args") or [])
    kwargs = {k: v for k, v in node.spec.items() if k not in OP_RESERVED}
    return args, kwargs


def _find_cycle(nodes: Dict[str, Node], left: Set[str]) -> List[str]:
    """One cycle among ``left`` (the nodes a topological sort could not place), as a path."""
    start = sorted(left)[0]
    seen: List[str] = []
    cur = start
    while cur not in seen:
        seen.append(cur)
        nxt = [_base(d) for d in nodes[cur].deps if _base(d) in left]
        if not nxt:
            break
        cur = sorted(nxt)[0]
    if cur in seen:
        loop = seen[seen.index(cur):]
        return loop + [cur]
    return seen


def parse_graph(data: Any, *, offered: Optional[Iterable[str]] = None, max_nodes: int = 40,
                taken: Iterable[str] = ()) -> Tuple[Optional[Graph], List[str]]:
    """Validate a graph reply. Returns ``(graph, [])`` or ``(None, errors)``; each error names the
    node it is about and is written for the model. ``offered``: the tools offered to the run (None
    skips that check); ``taken``: workspace names the graph may not reuse."""
    from sajha.ai.quant.ops import operations
    errors: List[str] = []

    def err(msg: str) -> None:
        if len(errors) < MAX_ERRORS:
            errors.append(msg)

    if not isinstance(data, dict) or not isinstance(data.get("nodes"), dict) or not data["nodes"]:
        return None, ["the graph must be a JSON object with nodes (an object of named nodes) and answer_with"]
    raw_nodes: Dict[str, Any] = data["nodes"]
    if len(raw_nodes) > max_nodes:
        return None, [f"the graph has {len(raw_nodes)} nodes; at most {max_nodes} are allowed "
                      f"(ai.quant.max_graph_nodes): read fewer values or combine them in fewer steps"]
    offered_set = set(offered) if offered is not None else None
    taken_set = set(taken)
    known_ops = operations()
    names = set(raw_nodes)
    nodes: Dict[str, Node] = {}
    for name, spec in raw_nodes.items():
        where = f"node {name}"
        if not NODE_NAME.match(str(name)):
            err(f"{where}: a node name is letters, digits and '_' (starting with a letter or '_'), at most 64")
            continue
        if name in taken_set or any(t.startswith(name + ".") for t in taken_set):
            err(f"{where}: the workspace already has a quantity named {name}; choose another name")
            continue
        if not isinstance(spec, dict):
            err(f"{where}: must be an object")
            continue
        kinds = [k for k in ("tool", "op", "value") if k in spec]
        if len(kinds) != 1:
            err(f"{where}: give exactly one of tool (a tool read), value (a constant) or op (an operation)")
            continue
        kind = {"tool": "tool", "op": "op", "value": "value"}[kinds[0]]
        node = Node(name, kind, dict(spec))
        if kind == "tool":
            extra = set(spec) - TOOL_KEYS
            if extra:
                err(f"{where}: unknown keys {', '.join(sorted(extra))} for a tool read")
            tool = spec.get("tool")
            if not isinstance(tool, str) or not tool:
                err(f"{where}: tool must be a tool name")
            elif offered_set is not None and tool not in offered_set:
                err(f"{where}: the tool {tool} is not offered to this run; use one of the tools offered")
            args = _arguments(spec.get("arguments"))
            if args is None:
                err(f"{where}: arguments must be an object")
                args = {}
            node.arguments = args
            read = spec.get("read")
            if not isinstance(read, str) or not read.strip():
                err(f"{where}: read must be a JSONPath into the tool's result, such as $.data.value")
            else:
                from sajha.quality.jsonpath import JSONPathError, parse
                try:
                    parse(read)
                except JSONPathError as e:
                    err(f"{where}: the read path {read} does not parse: {e}")
            if "unit" not in spec:
                err(f"{where}: declare the unit of the value read (for example USD mn, percent, bp, index)")
            else:
                try:
                    parse_unit(spec.get("unit"))
                except UnitError as e:
                    err(f"{where}: {e}")
        elif kind == "value":
            extra = set(spec) - VALUE_KEYS
            if extra:
                err(f"{where}: unknown keys {', '.join(sorted(extra))} for a constant")
            try:
                normalise_value(spec.get("value"))
                parse_unit(spec.get("unit"))
            except QuantError as e:
                err(f"{where}: {e}")
        else:
            op = spec.get("op")
            if op not in known_ops:
                err(f"{where}: there is no operation {op!r}; the operations are: {', '.join(sorted(known_ops))}")
            if "args" in spec and not isinstance(spec.get("args"), list):
                err(f"{where}: args must be a list")
            else:
                pos, kw = op_inputs(node)
                for v in list(pos) + list(kw.values()):
                    node.deps.extend(_refs(v, names))
                for d in node.deps:
                    if _base(d) == name:
                        err(f"{where}: uses itself")
        nodes[name] = node
    answer_with = data.get("answer_with")
    if not isinstance(answer_with, list) or not answer_with:
        err("answer_with must list the node names whose values answer the question")
        answer_with = []
    for a in answer_with:
        if not _is_ref(a, names):
            err(f"answer_with: {a!r} is not a node of the graph")
    if errors:
        return None, errors
    # dependency order (Kahn); what cannot be placed is on a cycle
    indeg = {n: len({_base(d) for d in nodes[n].deps}) for n in nodes}
    users: Dict[str, List[str]] = {n: [] for n in nodes}
    for n, node in nodes.items():
        for d in {_base(d) for d in node.deps}:
            users[d].append(n)
    ready = sorted(n for n, k in indeg.items() if k == 0)
    order: List[str] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for u in sorted(users[n]):
            indeg[u] -= 1
            if indeg[u] == 0:
                ready.append(u)
    if len(order) < len(nodes):
        cycle = _find_cycle(nodes, set(nodes) - set(order))
        return None, [f"the graph has a cycle: {' -> '.join(cycle)}; a node cannot depend on itself, directly "
                      f"or through others"]
    graph = Graph(nodes, order, [str(a) for a in answer_with], str(data.get("why") or "")[:500])
    errors = unit_check(graph)
    return (None, errors) if errors else (graph, [])


def _placeholder(node: Node) -> Quantity:
    if node.kind == "value":
        return Quantity(node.spec.get("value"), parse_unit(node.spec.get("unit")), name=node.name)
    return Quantity(1.0, parse_unit(node.spec.get("unit")), name=node.name)


def _resolve(v: Any, known: Dict[str, Any]) -> Any:
    if isinstance(v, str) and v in known:
        return known[v]
    if isinstance(v, list) and v and all(isinstance(x, str) and x in known for x in v):
        return [known[x] for x in v]
    return v


def unit_check(graph: Graph) -> List[str]:
    """Run every operation on placeholders that carry the declared units (value 1 for a tool read),
    so a unit refusal is found before any tool runs. A refusal that depends on the values (a zero
    start, too few points) is not a unit error and is left to execution."""
    from sajha.ai.quant.ops import SIGNATURES, operation
    known: Dict[str, Any] = {}
    unknown: Set[str] = set()
    errors: List[str] = []
    for n in graph.order:
        node = graph.nodes[n]
        if node.kind != "op":
            known[n] = _placeholder(node)
            continue
        if any(_base(d) in unknown for d in node.deps):
            unknown.add(n)
            continue
        pos, kw = op_inputs(node)
        op = node.spec["op"]
        try:
            out = operation(op)(*[_resolve(a, known) for a in pos], **{k: _resolve(v, known) for k, v in kw.items()})
        except UnitError as e:
            errors.append(f"node {n}: {e}")
            unknown.add(n)
            continue
        except TypeError as e:
            errors.append(f"node {n}: the arguments do not fit {op}: {e}; its signature is {SIGNATURES.get(op, op)}")
            unknown.add(n)
            continue
        except QuantError as e:
            if e.code in ("bad_input", "missing_input"):
                errors.append(f"node {n}: {e}")
            unknown.add(n)
            continue
        except Exception:
            unknown.add(n)
            continue
        if isinstance(out, dict):
            for part, q in out.items():
                known[f"{n}.{part}"] = q
        else:
            known[n] = out
        if len(errors) >= MAX_ERRORS:
            break
    return errors


def evaluate(graph: Graph, ws: Workspace, reads: Dict[str, Any]) -> Tuple[List[str], Dict[str, str]]:
    """Put the graph's quantities in ``ws``: ``reads`` maps each tool node to its Quantity, or to a
    string saying why it failed. Constants are put as given; operations run in dependency order
    through ``ws.run`` (so lineage names their inputs). A node whose input failed fails with the
    reason. Returns ``(names put, {node: reason failed})``."""
    put: List[str] = []
    failed: Dict[str, str] = {}
    for n in graph.order:
        node = graph.nodes[n]
        try:
            if node.kind == "tool":
                got = reads.get(n)
                if not isinstance(got, Quantity):
                    failed[n] = str(got or "the tool was not run")
                    continue
                ws.put(n, got)
                put.append(n)
            elif node.kind == "value":
                q = Quantity.of(node.spec.get("value"), node.spec.get("unit"), node.spec.get("as_of"),
                                text="stated in the question")
                ws.put(n, q)
                put.append(n)
            else:
                bad = sorted({_base(d) for d in node.deps if _base(d) in failed})
                if bad:
                    failed[n] = f"needs {', '.join(bad)}, which failed"
                    continue
                pos, kw = op_inputs(node)
                known = {name: ws.get(name) for name in put}
                out = ws.run(node.spec["op"], *[_resolve(a, known) for a in pos], name=n,
                             **{k: _resolve(v, known) for k, v in kw.items()})
                put.extend([f"{n}.{p}" for p in out] if isinstance(out, dict) else [n])
        except QuantError as e:
            failed[n] = str(e)
        except TypeError as e:
            failed[n] = f"the arguments do not fit {node.spec.get('op')}: {e}"
    return put, failed


def read_value(data: Any, path: str) -> Any:
    """The value a read path selects: one scalar, or a list (a column) when it selects a list or
    several values. Raises QuantError when it selects nothing."""
    from sajha.quality.jsonpath import find
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            raise QuantError("the tool result is text, not JSON, so no path can be read from it", "bad_read")
    hits = find(data, path)
    if not hits:
        raise QuantError(f"the read path {path} matches nothing in the tool result", "bad_read")
    return hits[0] if len(hits) == 1 else hits
